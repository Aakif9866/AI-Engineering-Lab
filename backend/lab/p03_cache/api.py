import json
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lab.core.config import var_dir
from lab.core.db import db, ensure, rows

from . import gateway as g
from .workload import compare, make_workload, threshold_sweep

router = APIRouter(prefix="/api/cache", tags=["03 CacheCraft"])


class ConfigIn(BaseModel):
    mode: str = Field("semantic", pattern="^(off|exact|semantic)$")
    threshold: float = Field(0.90, ge=0.0, le=1.0)
    reject_band: float = Field(0.10, ge=0.0, le=0.5)
    ttl_s: float = Field(3600, ge=1, le=7 * 86400)
    prompt_version: str = Field("faq-v1", max_length=40)
    provider: str | None = Field(None, pattern="^(deepseek|groq)$")
    temperature: float = Field(0.0, ge=0, le=2)
    scope_aware: bool = True
    dependency_check: bool = True


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    user_id: str = Field("u1", pattern="^u[0-9]{1,3}$")
    namespace: str = Field("faq", pattern=r"^[a-z0-9\-]{1,40}$")
    config: ConfigIn = ConfigIn()


@router.post("/ask")
def ask(body: AskIn):
    return g.ask(body.question, body.user_id, body.namespace, g.CacheConfig(**body.config.model_dump()))


@router.get("/kb")
def kb():
    return {"articles": list(g.articles().values()), "users": g.KB["users"]}


class EditIn(BaseModel):
    answer: str = Field(min_length=5, max_length=1000)
    purge: bool = True


@router.post("/kb/{article_id}")
def edit(article_id: str, body: EditIn):
    return g.edit_article(article_id, body.answer, body.purge)


@router.post("/kb-reset")
def kb_reset():
    g.reset_kb()
    return {"ok": True}


@router.get("/entries")
def entries(namespace: str = "faq"):
    ensure(g.SCHEMA)
    arts = g.articles()
    with db() as c:
        out = rows(c.execute("SELECT id, question, scope_key, fingerprint, answer, deps_json, label, created, ttl_s, hits, cost_usd, cost_kind, embedder "
                             "FROM cache_entries WHERE namespace=? ORDER BY created DESC LIMIT 200", (namespace,)))
    now = time.time()
    for e in out:
        e["age_s"] = round(now - e["created"], 1)
        e["expired"] = e["created"] + e["ttl_s"] < now
        e["deps_current"] = g._deps_current(e["deps_json"], arts)
    return out


@router.delete("/namespace/{namespace}")
def clear(namespace: str):
    return {"deleted": g.clear_namespace(namespace)}


@router.post("/purge-fingerprints")
def purge(body: AskIn):
    return {"deleted": g.purge_stale_fingerprints(body.namespace, g.CacheConfig(**body.config.model_dump()))}


@router.get("/events")
def events(limit: int = 60):
    ensure(g.SCHEMA)
    with db() as c:
        evs = rows(c.execute("SELECT * FROM cache_events WHERE run_id IS NULL ORDER BY id DESC LIMIT ?", (min(limit, 500),)))
        agg = rows(c.execute("SELECT event, COUNT(*) n, AVG(measured_ms) avg_ms, SUM(cost_usd) spent, SUM(cost_avoided_usd) avoided "
                             "FROM cache_events WHERE run_id IS NULL GROUP BY event"))
    return {"events": evs, "summary": agg}


@router.get("/workload/sample")
def workload_sample(n: int = 240, seed: int = 11):
    wl = make_workload(n, seed)
    return {"events": wl["events"], "first": wl["queries"][:25],
            "kinds": {k: sum(q["kind"] == k for q in wl["queries"]) for k in ("global", "personal", "volatile", "unrelated")}}


@router.get("/sweep")
def sweep():
    return threshold_sweep()


@router.get("/experiments")
def experiments():
    p = var_dir("results") / "p03_latest.json"
    return json.loads(p.read_text()) if p.exists() else None


class RunIn(BaseModel):
    n: int = Field(240, ge=40, le=2000)
    seed: int = 11


@router.post("/experiments/run")
def run(body: RunIn):
    if body.n > 600:
        raise HTTPException(400, "keep interactive runs under 600 queries; use the CLI for larger ones")
    return compare(body.n, body.seed)
