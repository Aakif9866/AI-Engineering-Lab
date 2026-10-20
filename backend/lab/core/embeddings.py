"""Local embedders. Each carries a `name` that is stored next to every vector it produced:
vectors from different embedders live in different spaces (PDF 1, "embedding model versioning"),
so indexes refuse to mix them.

- minilm: sentence-transformers/all-MiniLM-L6-v2 (384-d, ~90 MB, runs on CPU). Real semantic similarity.
- hash:   feature-hashed word + char n-grams. No download, deterministic, used by unit tests.
          It is lexical, so it is weak on paraphrases: experiments show that gap explicitly.
"""
import hashlib
import re

import numpy as np

from .config import env

_TOKEN = re.compile(r"[a-z0-9]+")


class HashEmbedder:
    name = "hash-v1-384"
    dim = 384

    def _features(self, text: str):
        words = _TOKEN.findall(text.lower())
        for w in words:
            yield "w:" + w, 1.0
            padded = f"#{w}#"
            for i in range(max(1, len(padded) - 3)):
                yield "c:" + padded[i:i + 4], 0.5
        for a, b in zip(words, words[1:]):
            yield f"b:{a}_{b}", 0.7

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, t in enumerate(texts):
            for feat, wt in self._features(t):
                h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "little")
                out[row, h % self.dim] += wt if (h >> 32) & 1 else -wt
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


class MiniLMEmbedder:
    name = "sentence-transformers/all-MiniLM-L6-v2"
    dim = 384

    def __init__(self):
        from sentence_transformers import SentenceTransformer  # heavy import, deferred
        try:  # cached copy first: avoids slow Hub round-trips on every process start
            self.model = SentenceTransformer(self.name, device="cpu", local_files_only=True)
        except Exception:
            self.model = SentenceTransformer(self.name, device="cpu")

    def embed(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True,
                                 show_progress_bar=False).astype(np.float32)


_cache: dict = {}
fallback_reason: str | None = None


def get_embedder(name: str | None = None):
    """Returns the requested embedder. If minilm cannot load, falls back to hash and records why
    in `fallback_reason` (surfaced in API responses) rather than failing silently."""
    global fallback_reason
    name = name or env("LAB_EMBEDDER", "minilm")
    if name not in _cache:
        if name == "minilm":
            try:
                _cache[name] = MiniLMEmbedder()
            except Exception as e:  # missing package or no cached model while offline
                fallback_reason = f"minilm unavailable ({type(e).__name__}: {str(e)[:120]}); using hash"
                _cache[name] = get_embedder("hash")
        else:
            _cache[name] = HashEmbedder()
    return _cache[name]


def cosine_top(query: np.ndarray, matrix: np.ndarray, k: int) -> list[tuple[int, float]]:
    """Exact (brute-force) cosine search over L2-normalised rows. Fine below ~1e5 vectors;
    an ANN index (HNSW/IVF-PQ) is the V2 step for larger corpora."""
    if len(matrix) == 0:
        return []
    sims = matrix @ query
    idx = np.argsort(-sims)[:k]
    return [(int(i), float(sims[i])) for i in idx]
