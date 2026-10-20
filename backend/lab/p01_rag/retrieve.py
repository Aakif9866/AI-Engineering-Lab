"""Retrieval strategies: bm25 | dense | hybrid (RRF), optional rerank, ACL pre-filter, context budget."""
from dataclasses import dataclass, field

import numpy as np

from lab.core import tracing
from lab.core.embeddings import get_embedder

from .index import Chunk, Index, tokens

ROLE_ACCESS = {"staff": {"public"}, "investigator": {"public", "restricted"}}
RRF_K = 60


@dataclass
class RetrievalConfig:
    strategy: str = "hybrid"      # bm25 | dense | hybrid
    k: int = 5                    # max chunks passed to the generator
    candidates: int = 30          # first-stage candidate pool
    reranker: str = "overlap"     # none | overlap | cross-encoder
    context_budget: int = 600     # words of context the generator may receive
    prefer_current: bool = True   # demote superseded / unverified documents
    role: str = "investigator"


@dataclass
class Hit:
    chunk: Chunk
    score: float
    scores: dict = field(default_factory=dict)

    def as_dict(self, n: int | None = None) -> dict:
        c = self.chunk
        return {"ref": f"S{n}" if n else None, "chunk_id": c.id, "doc_id": c.doc_id, "title": c.title,
                "text": c.text, "date": c.meta.get("date"), "status": c.meta.get("status"),
                "access": c.meta.get("access"), "type": c.meta.get("type"),
                "score": round(self.score, 4), "scores": {k: round(v, 4) for k, v in self.scores.items()}}


def _rank(scores: np.ndarray, allowed: np.ndarray, n: int) -> list[int]:
    order = [int(i) for i in np.argsort(-scores) if allowed[i] and scores[i] > 0]
    return order[:n]


def idf_coverage(index: Index, query: str, text: str) -> float:
    """Fraction of the query's idf mass whose terms appear in `text`. Used by the overlap reranker
    and by the abstention gate; rare identifiers count for more than common words."""
    q = set(tokens(query))
    if not q:
        return 0.0
    t = set(tokens(text))
    total = sum(index.bm25.idf(w) for w in q)
    return sum(index.bm25.idf(w) for w in q if w in t) / total if total else 0.0


_cross = None


def _cross_encoder():
    global _cross
    if _cross is None:
        from sentence_transformers import CrossEncoder
        _cross = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device="cpu")
    return _cross


def retrieve(index: Index, query: str, cfg: RetrievalConfig) -> list[Hit]:
    with tracing.span("rag.retrieve", kind="retrieval", module="rag", strategy=cfg.strategy, query=query,
                      reranker=cfg.reranker, role=cfg.role, k=cfg.k) as sp:
        access = ROLE_ACCESS.get(cfg.role)
        if access is None:
            raise ValueError(f"unknown role {cfg.role!r}")
        # ACL is a hard pre-filter: restricted text never reaches ranking, the prompt or the UI.
        allowed = np.array([c.meta.get("access", "public") in access for c in index.chunks], dtype=bool)
        n = len(index.chunks)
        bm = index.bm25.scores(query) if cfg.strategy in ("bm25", "hybrid") else np.zeros(n)
        dense = np.zeros(n, dtype=np.float32)
        if cfg.strategy in ("dense", "hybrid") and n:
            dense = index.vectors @ get_embedder(index.config.embedder).embed([query])[0]

        if cfg.strategy == "bm25":
            order = _rank(bm, allowed, cfg.candidates)
            fused = {i: float(bm[i]) for i in order}
        elif cfg.strategy == "dense":
            order = _rank(dense + 1.0, allowed, cfg.candidates)  # shift: cosine can be negative
            fused = {i: float(dense[i]) for i in order}
        elif cfg.strategy == "hybrid":  # reciprocal rank fusion: robust to incomparable score scales
            fused = {}
            for ranking in (_rank(bm, allowed, cfg.candidates), _rank(dense + 1.0, allowed, cfg.candidates)):
                for r, i in enumerate(ranking):
                    fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r + 1)
        else:
            raise ValueError(f"unknown strategy {cfg.strategy!r}")

        hits = [Hit(index.chunks[i], s, {"bm25": float(bm[i]), "dense": float(dense[i]), "first_stage": s})
                for i, s in fused.items()]
        hits.sort(key=lambda h: -h.score)

        if cfg.reranker == "overlap":
            for h in hits:
                h.scores["coverage"] = idf_coverage(index, query, f"{h.chunk.title} {h.chunk.text}")
                h.score = h.scores["coverage"] + 0.1 * (h.score / (hits[0].scores["first_stage"] or 1))
        elif cfg.reranker == "cross-encoder" and hits:
            with tracing.span("rag.rerank", kind="rerank", model="cross-encoder/ms-marco-MiniLM-L-6-v2"):
                ce = _cross_encoder().predict([(query, f"{h.chunk.title}. {h.chunk.text}") for h in hits])
            for h, s in zip(hits, ce):
                h.scores["cross_encoder"] = float(s)
                h.score = float(s)
        if cfg.prefer_current:
            for h in hits:
                if h.chunk.meta.get("status") in ("superseded", "unverified"):
                    h.scores["freshness_penalty"] = 0.5
                    h.score = h.score * 0.5 if h.score > 0 else h.score - abs(h.score) * 0.5
        hits.sort(key=lambda h: -h.score)

        selected, used = [], 0  # context budget: stop before exceeding the word budget
        for h in hits:
            w = len(h.chunk.text.split())
            if len(selected) >= cfg.k or (selected and used + w > cfg.context_budget):
                break
            selected.append(h)
            used += w
        sp.set(candidates=len(hits), selected=len(selected), context_words=used,
               top_docs=[h.chunk.doc_id for h in selected])
        return selected
