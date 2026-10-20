"""CacheCraft gateway: exact cache -> semantic cache -> upstream model, with write-through.

Safety properties, each testable:
- The exact key covers everything that changes the answer: normalised question, provider, model,
  prompt version, temperature, system prompt, namespace and (for personal questions) the user.
- Semantic matches are only searched among entries with the same config fingerprint and scope.
- Each entry records the knowledge-base article versions it was built from; a hit whose
  dependencies changed is evicted instead of served (PDF 3: "invalidate keyed on a content version hash").
- Volatile questions (live status) bypass the cache entirely.
- `scope_aware` and `dependency_check` can be switched off on purpose to measure the failures they prevent.
"""
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass

import numpy as np

from lab.core import providers, tracing
from lab.core.config import DATA
from lab.core.db import db, ensure, rows
from lab.core.embeddings import get_embedder

KB = json.loads((DATA / "p03" / "kb.json").read_text())
SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries(
  id INTEGER PRIMARY KEY AUTOINCREMENT, namespace TEXT NOT NULL, exact_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
  scope_key TEXT NOT NULL, question TEXT NOT NULL, embedding BLOB, embedder TEXT, answer TEXT NOT NULL,
  deps_json TEXT NOT NULL, label TEXT, created REAL NOT NULL, ttl_s REAL NOT NULL, hits INTEGER DEFAULT 0,
  cost_usd REAL, cost_kind TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cache_key ON cache_entries(namespace, exact_key);
CREATE INDEX IF NOT EXISTS ix_cache_scope ON cache_entries(namespace, fingerprint, scope_key);
CREATE TABLE IF NOT EXISTS cache_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, run_id TEXT, namespace TEXT, user_id TEXT, question TEXT,
  event TEXT, similarity REAL, matched_question TEXT, entry_id INTEGER, measured_ms REAL, modelled_ms REAL,
  cost_usd REAL, cost_avoided_usd REAL, cost_kind TEXT, label TEXT, served_label TEXT, correct INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS cache_kb_edits(id TEXT PRIMARY KEY, answer TEXT NOT NULL, edited REAL);
"""
SYSTEM_PROMPT = "You are the Nimbus Notes help assistant. Answer in one or two sentences using only the FAQ articles provided. If they do not cover the question, say you can only help with Nimbus Notes questions."
_PERSONAL = re.compile(r"\b(my|mine)\b.*\b(plan|subscription|renew\w*|billing date|charged|invoice|balance|account balance|seats)\b|\b(when will i be charged)\b", re.I)
_VOLATILE = re.compile(r"\b(right now|currently|at the moment|today|outage|is .* down|service status)\b", re.I)


@dataclass
class CacheConfig:
    mode: str = "semantic"          # off | exact | semantic
    threshold: float = 0.90         # cosine similarity needed for a semantic hit
    reject_band: float = 0.10       # near-misses within this band are logged as rejected matches
    ttl_s: float = 3600.0
    prompt_version: str = "faq-v1"
    provider: str | None = None     # None = offline deterministic upstream
    temperature: float = 0.0
    scope_aware: bool = True        # include the user in keys for personal questions
    dependency_check: bool = True   # evict hits whose KB dependencies changed
    modelled_upstream_ms: float = 800.0  # offline upstream only; reported separately from measured time


def classify_scope(question: str) -> str:
    """volatile (never cache) > user (key by user) > global. Pattern-based and deliberately
    conservative: 'reset my password' is global because the answer does not depend on the account."""
    if _VOLATILE.search(question):
        return "volatile"
    if _PERSONAL.search(question):
        return "user"
    return "global"


def normalise(q: str) -> str:
    return re.sub(r"\s+", " ", q.lower()).strip().rstrip("?.! ")


# ---- knowledge base with versioning -------------------------------------------------------------
def articles() -> dict[str, dict]:
    ensure(SCHEMA)
    with db() as c:
        edits = {r["id"]: r["answer"] for r in c.execute("SELECT id, answer FROM cache_kb_edits")}
    out = {}
    for a in KB["articles"]:
        ans = edits.get(a["id"], a["answer"])
        out[a["id"]] = {**a, "answer": ans, "version": hashlib.sha256(ans.encode()).hexdigest()[:12], "edited": a["id"] in edits}
    return out


def edit_article(article_id: str, answer: str, purge: bool = True) -> dict:
    """Changing an article changes its version hash. With purge=True dependent entries are deleted
    eagerly; either way the lookup-time dependency check refuses to serve them."""
    if article_id not in {a["id"] for a in KB["articles"]}:
        raise ValueError(f"unknown article {article_id!r}")
    ensure(SCHEMA)
    with db() as c:
        c.execute("INSERT OR REPLACE INTO cache_kb_edits VALUES(?,?,?)", (article_id, answer, time.time()))
    purged = invalidate_article(article_id) if purge else 0
    tracing.event("cache.kb_edit", kind="cache", module="cachecraft", article=article_id, purged=purged)
    return {"article": articles()[article_id], "purged_entries": purged}


def reset_kb() -> None:
    ensure(SCHEMA)
    with db() as c:
        c.execute("DELETE FROM cache_kb_edits")


def invalidate_article(article_id: str) -> int:
    ensure(SCHEMA)
    with db() as c:
        ids = [r["id"] for r in c.execute("SELECT id, deps_json FROM cache_entries") if article_id in json.loads(r["deps_json"])]
        c.executemany("DELETE FROM cache_entries WHERE id=?", [(i,) for i in ids])
    return len(ids)


def clear_namespace(namespace: str) -> int:
    ensure(SCHEMA)
    with db() as c:
        return c.execute("DELETE FROM cache_entries WHERE namespace=?", (namespace,)).rowcount


def purge_stale_fingerprints(namespace: str, cfg: CacheConfig) -> int:
    """After a prompt/model change, entries under the old fingerprint can never be hit; reclaim them."""
    ensure(SCHEMA)
    with db() as c:
        return c.execute("DELETE FROM cache_entries WHERE namespace=? AND fingerprint<>?", (namespace, fingerprint(cfg, namespace))).rowcount


# ---- keys -----------------------------------------------------------------------------------------
def fingerprint(cfg: CacheConfig, namespace: str) -> str:
    model = providers.model_for(cfg.provider) if cfg.provider else "offline-faq-answerer-v1"
    parts = [namespace, cfg.provider or "offline", model, cfg.prompt_version, f"{cfg.temperature:.2f}",
             hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:8]]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def scope_key(scope: str, user_id: str, cfg: CacheConfig) -> str:
    return f"user:{user_id}" if scope == "user" and cfg.scope_aware else "*"


def exact_key(fp: str, skey: str, question: str) -> str:
    return hashlib.sha256(f"{fp}|{skey}|{normalise(question)}".encode()).hexdigest()


# ---- upstream -------------------------------------------------------------------------------------
_kb_index: dict = {}


def _route(question: str, k: int = 2) -> list[tuple[str, float]]:
    """Nearest articles by canonical question + title + answer, as an FAQ page is titled by its question.
    The paraphrases used by the workload are never indexed, so routing is not tuned to the test."""
    emb = get_embedder()
    arts = articles()
    key = (emb.name, tuple(a["version"] for a in arts.values()))
    if _kb_index.get("key") != key:
        ids = list(arts)
        _kb_index.update(key=key, ids=ids, m=emb.embed([f"{arts[i]['questions'][0]} {arts[i]['title']}. {arts[i]['answer']}" for i in ids]))
    sims = _kb_index["m"] @ emb.embed([question])[0]
    order = np.argsort(-sims)[:k]
    return [(_kb_index["ids"][i], float(sims[i])) for i in order]


def _estimate_cost(prompt_chars: int, completion_chars: int) -> float | None:
    prov = providers.default_provider() or "deepseek"
    usd, _ = providers.price_cost(prov, providers.model_for(prov), prompt_chars // 4, completion_chars // 4, 0)
    return usd


def upstream(question: str, user_id: str, cfg: CacheConfig) -> dict:
    arts = articles()
    routed = _route(question)
    top = [arts[i] for i, s in routed if s >= 0.25]
    deps = {a["id"]: a["version"] for a in top}
    user = KB["users"].get(user_id, {"renewal": "unknown (no such user)"})
    status_line = f"all systems operational as of {time.strftime('%H:%M:%S')}"
    ctx = "\n".join(f"[{a['id']}] {a['title']}: {a['answer'].format(renewal=user['renewal'], status=status_line)}" for a in top)
    t0 = time.perf_counter()
    if cfg.provider:
        r = providers.chat([{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": f"FAQ articles:\n{ctx or '(none)'}\n\nCustomer question: {question}"}],
                           provider=cfg.provider, temperature=cfg.temperature, max_tokens=500, module="cachecraft",
                           prompt_version=cfg.prompt_version)
        return {"answer": r.text.strip(), "deps": deps, "measured_ms": (time.perf_counter() - t0) * 1000, "modelled_ms": None,
                "cost_usd": r.cost_usd, "cost_kind": "actual", "cached_tokens": r.cached_tokens, "route": routed}
    if not top:
        ans = "I can only help with Nimbus Notes questions."
    else:
        ans = top[0]["answer"].format(renewal=user["renewal"], status=status_line)
    measured = (time.perf_counter() - t0) * 1000
    return {"answer": ans, "deps": {top[0]["id"]: top[0]["version"]} if top else {}, "measured_ms": measured,
            "modelled_ms": cfg.modelled_upstream_ms, "cost_usd": _estimate_cost(len(SYSTEM_PROMPT) + len(ctx) + len(question), len(ans)),
            "cost_kind": "estimated", "cached_tokens": None, "route": routed}


# ---- the gateway ------------------------------------------------------------------------------------
def _deps_current(deps: dict, arts: dict) -> bool:
    return all(arts.get(i, {}).get("version") == v for i, v in deps.items())


def _log(ev: dict) -> None:
    cols = ["ts", "run_id", "namespace", "user_id", "question", "event", "similarity", "matched_question", "entry_id",
            "measured_ms", "modelled_ms", "cost_usd", "cost_avoided_usd", "cost_kind", "label", "served_label", "correct", "detail"]
    with db() as c:
        c.execute(f"INSERT INTO cache_events({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [ev.get(k) for k in cols])


def ask(question: str, user_id: str = "u1", namespace: str = "faq", cfg: CacheConfig | None = None, *,
        label: str | None = None, run_id: str | None = None, now: float | None = None) -> dict:
    """Serve one request. `label` (ground-truth intent, workload only) lets us score whether a hit was correct."""
    cfg = cfg or CacheConfig()
    ensure(SCHEMA)
    now = now or time.time()
    t0 = time.perf_counter()
    scope = classify_scope(question)
    fp, skey = fingerprint(cfg, namespace), scope_key(scope, user_id, cfg)
    key = exact_key(fp, skey, question)
    arts = articles()
    res = {"question": question, "user_id": user_id, "namespace": namespace, "scope": scope, "scope_key": skey,
           "fingerprint": fp, "config": asdict(cfg), "similarity": None, "matched_question": None, "evicted": []}

    with tracing.span("cache.ask", kind="request", module="cachecraft", question=question, mode=cfg.mode, scope=scope) as sp:
        hit = None
        if cfg.mode != "off" and scope != "volatile":
            with db() as c:
                cands = rows(c.execute("SELECT * FROM cache_entries WHERE namespace=? AND fingerprint=? AND scope_key=?", (namespace, fp, skey)))
            live = []
            for e in cands:  # TTL and dependency checks happen before an entry may be served
                reason = "ttl_expired" if e["created"] + e["ttl_s"] < now else None
                if not reason and cfg.dependency_check and not _deps_current(e["deps_json"], arts):
                    reason = "dependency_changed"
                if reason:
                    with db() as c:
                        c.execute("DELETE FROM cache_entries WHERE id=?", (e["id"],))
                    res["evicted"].append({"question": e["question"], "reason": reason})
                    tracing.event("cache.evict", kind="cache", reason=reason)
                else:
                    live.append(e)
            exact = next((e for e in live if e["exact_key"] == key), None)
            if exact:
                hit, res["event"], res["similarity"] = exact, "hit_exact", 1.0
            elif cfg.mode == "semantic" and live:
                emb = get_embedder()
                pool = [e for e in live if e["embedder"] == emb.name]
                if pool:
                    q = emb.embed([question])[0]
                    sims = np.stack([np.frombuffer(e["embedding"], dtype=np.float32) for e in pool]) @ q
                    i = int(np.argmax(sims))
                    res["similarity"], res["matched_question"] = round(float(sims[i]), 4), pool[i]["question"]
                    if sims[i] >= cfg.threshold:
                        hit, res["event"] = pool[i], "hit_semantic"
                    elif sims[i] >= cfg.threshold - cfg.reject_band:
                        res["rejected_match"] = True
        if hit:
            with db() as c:
                c.execute("UPDATE cache_entries SET hits=hits+1 WHERE id=?", (hit["id"],))
            measured = (time.perf_counter() - t0) * 1000
            correct = None
            if label is not None:
                # Correct only if it answers the same intent with current data. Personal intents are
                # labelled per user ("my_renewal@u1"), so cross-user reuse fails this check too.
                correct = int(hit["label"] == label and _deps_current(hit["deps_json"], arts))
            res.update(answer=hit["answer"], entry_id=hit["id"], measured_ms=measured, modelled_ms=measured,
                       cost_usd=0.0, cost_avoided_usd=hit["cost_usd"], cost_kind=hit["cost_kind"], served_label=hit["label"],
                       correct=correct, deps=hit["deps_json"], cached_at=hit["created"])
        else:
            res["event"] = "bypass" if scope == "volatile" or cfg.mode == "off" else ("rejected_match" if res.get("rejected_match") else "miss")
            try:
                up = upstream(question, user_id, cfg)
            except providers.ProviderError as e:
                res.update(event="upstream_error", answer=None, error=str(e), measured_ms=(time.perf_counter() - t0) * 1000)
                sp.fail("upstream_error", str(e))
                _log({**res, "ts": now, "run_id": run_id, "label": label, "detail": str(e)})
                return res
            measured = (time.perf_counter() - t0) * 1000
            modelled = None if up["modelled_ms"] is None else measured - up["measured_ms"] + up["modelled_ms"]
            res.update(answer=up["answer"], measured_ms=measured, modelled_ms=modelled if modelled is not None else measured,
                       cost_usd=up["cost_usd"], cost_avoided_usd=0.0, cost_kind=up["cost_kind"], deps=up["deps"],
                       cached_tokens=up["cached_tokens"], route=up["route"], correct=None)
            if cfg.mode != "off" and scope != "volatile":  # write-through
                emb = get_embedder()
                vec = emb.embed([question])[0].astype(np.float32).tobytes()
                with db() as c:
                    cur = c.execute("INSERT OR REPLACE INTO cache_entries(namespace, exact_key, fingerprint, scope_key, question, embedding, embedder,"
                                    " answer, deps_json, label, created, ttl_s, cost_usd, cost_kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (namespace, key, fp, skey, question, vec, emb.name, up["answer"], json.dumps(up["deps"]), label,
                                     now, cfg.ttl_s, up["cost_usd"], up["cost_kind"]))
                    res["entry_id"] = cur.lastrowid
        tracing.event(f"cache.{res['event']}", kind="cache", similarity=res["similarity"], scope=scope)
        sp.set(event=res["event"], similarity=res["similarity"])
        _log({**res, "ts": now, "run_id": run_id, "label": label, "detail": json.dumps(res["evicted"]) if res["evicted"] else None})
        res["trace_id"] = sp.trace_id
        return res
