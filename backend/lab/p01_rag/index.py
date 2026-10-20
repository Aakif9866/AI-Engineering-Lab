"""Ingestion, chunking and indexing for Evidence Atlas.

Pipeline: documents (front-matter metadata + body) -> chunks -> BM25 postings + dense vectors.
`Index.sync()` is incremental: a document is re-chunked and re-embedded only when its content
hash changes (PDF 1: "diff-based re-embedding of changed documents only").
"""
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from lab.core import tracing
from lab.core.config import DATA
from lab.core.db import db, ensure
from lab.core.embeddings import get_embedder

CORPUS_DIR = DATA / "p01" / "corpus"
SCHEMA = """CREATE TABLE IF NOT EXISTS rag_docs(
  id TEXT PRIMARY KEY, title TEXT, type TEXT, date TEXT, version TEXT, status TEXT,
  access TEXT, author TEXT, body TEXT NOT NULL, ingested_at REAL);"""

STOP = set("a an and are as at be by for from has have he her his i in is it its of on or she that the "
           "their them they this to was were what when where which who why how with did does do under "
           "according based".split())
_TOK = re.compile(r"[a-z0-9]+(?:[-.:,][a-z0-9]+)*")


def tokens(text: str) -> list[str]:
    """Keeps identifiers intact ('vx-88213', '02:20', '11.4') and also emits their parts,
    so 'VX-88213' matches both 'vx-88213' and '88213'."""
    out = []
    for t in _TOK.findall(text.lower()):
        t = t.rstrip(".,:")
        if t in STOP or not t:
            continue
        out.append(t)
        if any(c in t for c in "-.:,"):
            out.extend(p for p in re.split(r"[-.:,]", t) if p and p not in STOP and len(p) > 1)
    return out


@dataclass
class Document:
    id: str
    title: str
    body: str
    meta: dict

    @property
    def hash(self) -> str:
        return hashlib.sha256((self.title + "\n" + self.body + str(sorted(self.meta.items()))).encode()).hexdigest()[:16]


def parse_document(raw: str, fallback_id: str = "") -> Document:
    """Extract front matter; for emails without front matter, lift From/Subject headers into metadata."""
    meta: dict = {}
    body = raw
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    else:
        for line in raw.splitlines()[:6]:
            m = re.match(r"(From|To|Subject|Date):\s*(.+)", line)
            if m:
                meta[m.group(1).lower()] = m.group(2).strip()
        if "subject" in meta:
            meta.setdefault("type", "email")
            meta.setdefault("title", meta["subject"])
            meta.setdefault("author", meta.get("from", ""))
    doc_id = meta.pop("id", fallback_id)
    title = meta.pop("title", doc_id)
    for k, d in (("access", "public"), ("status", "current"), ("type", "document"), ("date", ""), ("version", "1")):
        meta.setdefault(k, d)
    return Document(doc_id, title, body.strip(), meta)


def load_corpus() -> list[Document]:
    docs = {p.stem: parse_document(p.read_text(), p.stem) for p in sorted(CORPUS_DIR.glob("*.md"))}
    ensure(SCHEMA)
    with db() as c:  # documents ingested through the UI/API
        for r in c.execute("SELECT * FROM rag_docs"):
            meta = {k: r[k] for k in ("type", "date", "version", "status", "access", "author")}
            docs[r["id"]] = Document(r["id"], r["title"], r["body"], meta)
    return list(docs.values())


def save_document(doc: Document) -> None:
    ensure(SCHEMA)
    import time
    with db() as c:
        c.execute("INSERT OR REPLACE INTO rag_docs VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (doc.id, doc.title, doc.meta.get("type"), doc.meta.get("date"), doc.meta.get("version"),
                   doc.meta.get("status"), doc.meta.get("access"), doc.meta.get("author"), doc.body, time.time()))


def delete_document(doc_id: str) -> bool:
    ensure(SCHEMA)
    with db() as c:
        return c.execute("DELETE FROM rag_docs WHERE id=?", (doc_id,)).rowcount > 0


@dataclass
class Chunk:
    id: str
    doc_id: str
    title: str
    text: str
    meta: dict
    position: int


def chunk_document(doc: Document, size: int, overlap: int, strategy: str) -> list[Chunk]:
    """size/overlap are in words (~1.3 tokens each).
    fixed:   sliding window, ignores structure.
    section: split on blank lines / headings, then pack whole paragraphs up to `size` words,
             so a table row or a list item is never cut in half (layout-aware chunking)."""
    words = doc.body.split()
    if strategy == "fixed":
        step = max(1, size - overlap)
        pieces = [" ".join(words[i:i + size]) for i in range(0, max(1, len(words) - overlap), step)]
    elif strategy == "section":
        paras = [p.strip() for p in re.split(r"\n\s*\n", doc.body) if p.strip()]
        pieces, cur, n = [], [], 0
        for p in paras:
            w = len(p.split())
            if cur and n + w > size:
                pieces.append("\n".join(cur))
                # overlap = repeat the previous paragraph when it fits in the overlap budget
                last = cur[-1]
                cur, n = ([last], len(last.split())) if overlap and len(last.split()) <= overlap else ([], 0)
            cur.append(p)
            n += w
        if cur:
            pieces.append("\n".join(cur))
    else:
        raise ValueError(f"unknown chunking strategy {strategy!r}")
    return [Chunk(f"{doc.id}#c{i}", doc.id, doc.title, t, doc.meta, i) for i, t in enumerate(pieces) if t]


class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: list[Counter] = []
        self.df: Counter = Counter()

    def fit(self, texts: list[str]) -> "BM25":
        self.docs = [Counter(tokens(t)) for t in texts]
        self.df = Counter(t for d in self.docs for t in d)
        self.avgdl = sum(sum(d.values()) for d in self.docs) / max(1, len(self.docs))
        return self

    def idf(self, term: str) -> float:
        n = len(self.docs)
        return math.log(1 + (n - self.df.get(term, 0) + 0.5) / (self.df.get(term, 0) + 0.5))

    def scores(self, query: str) -> np.ndarray:
        q = tokens(query)
        out = np.zeros(len(self.docs), dtype=np.float32)
        for i, d in enumerate(self.docs):
            dl = sum(d.values())
            for t in q:
                f = d.get(t, 0)
                if f:
                    out[i] += self.idf(t) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return out


@dataclass
class IndexConfig:
    chunk_size: int = 120
    overlap: int = 20
    strategy: str = "section"
    embedder: str | None = None

    def key(self) -> tuple:
        return (self.chunk_size, self.overlap, self.strategy, self.embedder)


@dataclass
class Index:
    config: IndexConfig
    chunks: list[Chunk] = field(default_factory=list)
    vectors: np.ndarray = field(default_factory=lambda: np.zeros((0, 384), dtype=np.float32))
    doc_hashes: dict = field(default_factory=dict)
    embedder_name: str = ""
    bm25: BM25 = field(default_factory=BM25)
    last_sync: dict = field(default_factory=dict)

    def sync(self, docs: list[Document]) -> dict:
        emb = get_embedder(self.config.embedder)
        if self.embedder_name and self.embedder_name != emb.name:
            raise ValueError(f"index built with {self.embedder_name}, refusing to mix with {emb.name}; rebuild")
        self.embedder_name = emb.name
        with tracing.span("rag.index.sync", kind="indexing", module="rag", embedder=emb.name) as sp:
            incoming = {d.id: d for d in docs}
            changed = [d for d in docs if self.doc_hashes.get(d.id) != d.hash]
            removed = [i for i in self.doc_hashes if i not in incoming]
            drop = {d.id for d in changed} | set(removed)
            keep = [i for i, c in enumerate(self.chunks) if c.doc_id not in drop]
            new_chunks = [c for d in changed for c in chunk_document(d, self.config.chunk_size, self.config.overlap, self.config.strategy)]
            new_vecs = emb.embed([f"{c.title}\n{c.text}" for c in new_chunks]) if new_chunks else np.zeros((0, emb.dim), np.float32)
            self.chunks = [self.chunks[i] for i in keep] + new_chunks
            self.vectors = np.vstack([self.vectors[keep] if len(keep) else np.zeros((0, emb.dim), np.float32), new_vecs])
            self.bm25 = BM25().fit([f"{c.title} {c.text}" for c in self.chunks])  # cheap at this scale
            for d in changed:
                self.doc_hashes[d.id] = d.hash
            for i in removed:
                self.doc_hashes.pop(i)
            stats = {"docs_total": len(incoming), "docs_reembedded": len(changed), "docs_removed": len(removed),
                     "docs_unchanged": len(incoming) - len(changed), "chunks_embedded": len(new_chunks),
                     "chunks_total": len(self.chunks), "embedder": emb.name}
            sp.set(**stats)
            self.last_sync = stats
            return stats


_indexes: dict[tuple, Index] = {}


def get_index(config: IndexConfig) -> Index:
    idx = _indexes.setdefault(config.key(), Index(config))
    idx.sync(load_corpus())
    return idx
