import hashlib
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from ingest import Chunk, load_chunks

CACHE_DIR = Path(__file__).parent / ".cache"
MODEL = "BAAI/bge-small-en-v1.5"  # ~130 MB, downloaded on first use
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"  # ~80 MB, reads question + chunk together


@lru_cache
def _model() -> TextEmbedding:
    return TextEmbedding(MODEL)


def _unit(v: np.ndarray) -> np.ndarray:
    # length 1, so a plain dot product equals cosine similarity
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


class DenseIndex:
    """Chunks + one embedding per chunk. Search = which chunk vectors point the same way as the question."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        key = hashlib.sha1("\n".join(c.text for c in chunks).encode()).hexdigest()[:12]
        cache = CACHE_DIR / f"emb-{key}.npy"  # key changes whenever any chunk text changes
        if cache.exists():
            self.vecs = np.load(cache)
        else:
            self.vecs = _unit(np.array(list(_model().embed([c.text for c in chunks]))))
            CACHE_DIR.mkdir(exist_ok=True)
            np.save(cache, self.vecs)

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        q = _unit(np.array(list(_model().query_embed(query))[0]))
        scores = self.vecs @ q
        return [(self.chunks[i], float(scores[i])) for i in np.argsort(-scores)[:k]]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25Index:
    """Keyword search: a chunk scores high if it contains the question's words, rare words count more."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.tf = [Counter(tokenize(c.text)) for c in chunks]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg_len = sum(self.len) / len(chunks)
        df = Counter(w for t in self.tf for w in t)  # in how many chunks does each word appear
        n = len(chunks)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        scores = []
        for tf, length in zip(self.tf, self.len):
            s = 0.0
            for w in set(tokenize(query)):
                if w in tf:
                    norm = tf[w] + self.k1 * (1 - self.b + self.b * length / self.avg_len)
                    s += self.idf[w] * tf[w] * (self.k1 + 1) / norm
            scores.append(s)
        top = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        return [(self.chunks[i], scores[i]) for i in top if scores[i] > 0]  # 0 = no shared word


def rrf(*ranked_lists: list[Chunk], c: int = 60) -> list[tuple[Chunk, float]]:
    """Reciprocal rank fusion: each list gives a chunk 1/(c+rank) points; sum the points."""
    points: dict[str, float] = {}
    by_id: dict[str, Chunk] = {}
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            by_id[chunk.id] = chunk
            points[chunk.id] = points.get(chunk.id, 0.0) + 1 / (c + rank)
    return [(by_id[i], p) for i, p in sorted(points.items(), key=lambda x: -x[1])]


def hybrid_search(dense: DenseIndex, bm25: BM25Index, query: str, k: int = 3, pool: int = 10):
    lists = [[c for c, _ in idx.search(query, pool)] for idx in (dense, bm25)]
    return rrf(*lists)[:k]


@lru_cache
def _reranker() -> TextCrossEncoder:
    return TextCrossEncoder(RERANK_MODEL)


def is_retired(chunk: Chunk) -> bool:
    return "retired" in chunk.title.lower()


def rerank(query: str, candidates: list[Chunk], k: int = 3) -> list[tuple[Chunk, float]]:
    """Read question + chunk together (slower, sharper), re-sort, and push retired docs to the back."""
    scores = list(_reranker().rerank(query, [c.text for c in candidates]))
    ranked = sorted(zip(candidates, scores), key=lambda x: (is_retired(x[0]), -x[1]))
    return [(c, float(s)) for c, s in ranked[:k]]


def search(dense: DenseIndex, bm25: BM25Index, query: str, k: int = 3, pool: int = 6):
    """The full retrieval: hybrid picks a pool of candidates, the reranker picks the final k."""
    return rerank(query, [c for c, _ in hybrid_search(dense, bm25, query, k=pool)], k)


if __name__ == "__main__":
    chunks = load_chunks()
    dense, bm25 = DenseIndex(chunks), BM25Index(chunks)
    for q in ["how long until I get my money back?", "can I change my email?", "24 months", "do you ship to Mexico?"]:
        print(f"\nQ: {q}")
        print("  hybrid  :", [c.id for c, _ in hybrid_search(dense, bm25, q)])
        print("  reranked:", [(c.id, round(s, 1)) for c, s in search(dense, bm25, q)])
