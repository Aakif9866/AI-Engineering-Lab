import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lab.core.config import var_dir

from . import index as ix
from .evaluate import BENCH, run_benchmark, run_grid
from .index import IndexConfig, get_index
from .pipeline import ask
from .retrieve import RetrievalConfig

router = APIRouter(prefix="/api/rag", tags=["01 Evidence Atlas"])


class IndexIn(BaseModel):
    chunk_size: int = Field(120, ge=20, le=1000)
    overlap: int = Field(20, ge=0, le=300)
    strategy: str = Field("section", pattern="^(fixed|section)$")
    embedder: str | None = Field(None, pattern="^(minilm|hash)$")


class RetrievalIn(BaseModel):
    strategy: str = Field("hybrid", pattern="^(bm25|dense|hybrid)$")
    k: int = Field(5, ge=1, le=20)
    candidates: int = Field(30, ge=5, le=200)
    reranker: str = Field("overlap", pattern="^(none|overlap|cross-encoder)$")
    context_budget: int = Field(600, ge=50, le=5000)
    prefer_current: bool = True
    role: str = Field("investigator", pattern="^(staff|investigator)$")


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    index: IndexIn = IndexIn()
    retrieval: RetrievalIn = RetrievalIn()
    use_llm: bool = False
    provider: str | None = None
    min_coverage: float = Field(0.35, ge=0, le=1)


class IngestIn(BaseModel):
    raw: str = Field(min_length=10, max_length=50_000)
    id: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-]{2,40}$")


def _doc_summary(d: ix.Document, source: str) -> dict:
    return {"id": d.id, "title": d.title, **d.meta, "words": len(d.body.split()), "source": source, "hash": d.hash}


@router.get("/corpus")
def corpus():
    files = {p.stem for p in ix.CORPUS_DIR.glob("*.md")}
    return [_doc_summary(d, "fixture" if d.id in files else "ingested") for d in ix.load_corpus()]


@router.get("/doc/{doc_id}")
def doc(doc_id: str):
    d = next((d for d in ix.load_corpus() if d.id == doc_id), None)
    if not d:
        raise HTTPException(404, "no such document")
    return {**_doc_summary(d, ""), "body": d.body}


@router.post("/ingest")
def ingest(body: IngestIn):
    import time
    d = ix.parse_document(body.raw, body.id or f"DOC-{int(time.time())}")
    if body.id:
        d.id = body.id
    if d.id in {p.stem for p in ix.CORPUS_DIR.glob("*.md")}:
        raise HTTPException(409, "fixture documents are read-only; choose another id")
    ix.save_document(d)
    stats = get_index(IndexConfig()).last_sync
    return {"document": _doc_summary(d, "ingested"), "index_sync": stats}


@router.delete("/doc/{doc_id}")
def delete(doc_id: str):
    if not ix.delete_document(doc_id):
        raise HTTPException(404, "only ingested documents can be deleted")
    return {"deleted": doc_id, "index_sync": get_index(IndexConfig()).last_sync}


@router.post("/ask")
def ask_route(body: AskIn):
    return ask(body.question, IndexConfig(**body.index.model_dump()), RetrievalConfig(**body.retrieval.model_dump()),
               use_llm=body.use_llm, provider=body.provider, min_coverage=body.min_coverage)


@router.get("/benchmark")
def benchmark():
    return BENCH


class EvalIn(BaseModel):
    index: IndexIn = IndexIn()
    retrieval: RetrievalIn = RetrievalIn()
    use_llm: bool = False
    provider: str | None = None


@router.post("/evaluate")
def evaluate(body: EvalIn):
    return run_benchmark(IndexConfig(**body.index.model_dump()), RetrievalConfig(**body.retrieval.model_dump()),
                         use_llm=body.use_llm, provider=body.provider)


@router.get("/experiments")
def experiments():
    p = var_dir("results") / "p01_latest.json"
    return json.loads(p.read_text()) if p.exists() else None


@router.post("/experiments/run")
def run_experiments(embedder: str | None = None):
    return run_grid(embedder)
