"""TraceLens: queries over the shared span store (lab.core.tracing).

All numbers are computed from recorded spans. Cost is summed only from spans that carry an actual
usage-based cost, and the count of LLM spans without one is reported next to it.
"""
import json
import time
import uuid

import numpy as np

from lab.core import tracing
from lab.core.db import db, ensure, rows

MODULE_SLUG = {"rag": "evidence-atlas", "intentforge": "intentforge", "cachecraft": "cachecraft", "trustboundary": "trustboundary",
               "signalloop": "signalloop", "missionreplay": "missionreplay", "standalone": "tracelens"}
ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS obs_alert_rules(id TEXT PRIMARY KEY, name TEXT, metric TEXT, module TEXT, op TEXT, threshold REAL,
  window_min REAL, enabled INTEGER, leading INTEGER);
CREATE TABLE IF NOT EXISTS obs_alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, rule_id TEXT, value REAL, message TEXT);
"""
DEFAULT_RULES = [
    ("p95 LLM latency", "llm_p95_ms", None, ">", 8000, 60, 0),
    ("Request error rate", "error_rate", None, ">", 0.10, 60, 0),
    ("Cost per request", "cost_per_request_usd", None, ">", 0.01, 60, 0),
    ("Retry rate (leading)", "retry_rate", None, ">", 0.05, 60, 1),
    ("Cache hit rate (leading)", "cache_hit_rate", "cachecraft", "<", 0.30, 60, 1),
    ("Guardrail block rate", "guardrail_block_rate", "trustboundary", ">", 0.50, 60, 0),
]


def _spans(where: str = "1=1", args: tuple = ()) -> list[dict]:
    ensure(tracing.SCHEMA)
    with db() as c:
        return rows(c.execute(f"SELECT * FROM spans WHERE {where}", args))


def pct(xs, q):
    return round(float(np.percentile(xs, q)), 1) if xs else None


# ---- traces ------------------------------------------------------------------------------------------
def search(module: str | None = None, status: str | None = None, q: str | None = None, since_h: float | None = None,
           attr: str | None = None, limit: int = 100) -> list[dict]:
    where, args = ["parent_id IS NULL"], []
    if module:
        where.append("module=?"); args.append(module)
    if since_h:
        where.append("start_ts>=?"); args.append(time.time() - since_h * 3600)
    if q:
        where.append("(name LIKE ? OR trace_id LIKE ? OR attrs_json LIKE ?)"); args += [f"%{q}%"] * 3
    roots = _spans(" AND ".join(where) + " ORDER BY start_ts DESC LIMIT ?", (*args, limit * 3))
    if not roots:
        return []
    ids = [r["trace_id"] for r in roots]
    with db() as c:
        agg = {r["trace_id"]: dict(r) for r in c.execute(
            f"SELECT trace_id, COUNT(*) n, SUM(status='error') errors, SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)) tokens, "
            f"SUM(cost_usd) cost, SUM(kind='llm') llm_calls, GROUP_CONCAT(DISTINCT error_type) error_types FROM spans "
            f"WHERE trace_id IN ({','.join('?' * len(ids))}) GROUP BY trace_id", ids)}
    out = []
    for r in roots:
        a = agg[r["trace_id"]]
        st = "error" if r["status"] == "error" else ("degraded" if a["errors"] else "ok")
        if status and st != status:
            continue
        if attr and attr not in json.dumps(r["attrs_json"]):
            continue
        out.append({"trace_id": r["trace_id"], "name": r["name"], "module": r["module"], "start_ts": r["start_ts"], "duration_ms": r["duration_ms"],
                    "status": st, "spans": a["n"], "errors": a["errors"], "error_types": a["error_types"], "llm_calls": a["llm_calls"],
                    "tokens": a["tokens"] or None, "cost_usd": a["cost"], "attrs": r["attrs_json"]})
    return out[:limit]


def get_trace(trace_id: str) -> dict | None:
    spans = tracing.get_trace(trace_id)
    if not spans:
        return None
    by_parent: dict = {}
    for s in spans:
        by_parent.setdefault(s["parent_id"], []).append(s)
    ordered = []

    def walk(pid, depth):
        for s in sorted(by_parent.get(pid, []), key=lambda x: x["start_ts"]):
            ordered.append({**s, "depth": depth})
            walk(s["span_id"], depth + 1)
    walk(None, 0)
    orphans = [s for s in spans if s["parent_id"] and s["parent_id"] not in {x["span_id"] for x in spans}]
    t0 = min(s["start_ts"] for s in spans)
    for s in ordered:
        s["offset_ms"] = round((s["start_ts"] - t0) * 1000, 2)
    return {"trace_id": trace_id, "spans": ordered, "orphans": orphans,
            "summary": {"spans": len(spans), "errors": sum(s["status"] == "error" for s in spans),
                        "llm_calls": sum(s["kind"] == "llm" for s in spans),
                        "tokens": sum((s["input_tokens"] or 0) + (s["output_tokens"] or 0) for s in spans) or None,
                        "cost_usd": sum(s["cost_usd"] or 0 for s in spans) if any(s["cost_usd"] for s in spans) else None,
                        "duration_ms": ordered[0]["duration_ms"] if ordered else None}}


def compare_traces(a: str, b: str) -> dict:
    """Align two traces by span name and occurrence: what got slower, what failed, what appeared."""
    ta, tb = get_trace(a), get_trace(b)
    if not ta or not tb:
        raise ValueError("unknown trace")

    def keyed(t):
        seen: dict = {}
        out = {}
        for s in t["spans"]:
            seen[s["name"]] = seen.get(s["name"], 0) + 1
            out[f"{s['name']}#{seen[s['name']]}"] = s
        return out
    ka, kb = keyed(ta), keyed(tb)
    keys = list(dict.fromkeys(list(ka) + list(kb)))
    return {"a": ta["summary"], "b": tb["summary"], "rows": [
        {"span": k, "depth": (ka.get(k) or kb.get(k))["depth"], "a_ms": ka[k]["duration_ms"] if k in ka else None, "b_ms": kb[k]["duration_ms"] if k in kb else None,
         "a_status": ka[k]["status"] if k in ka else "absent", "b_status": kb[k]["status"] if k in kb else "absent"} for k in keys]}


# ---- metrics -----------------------------------------------------------------------------------------
def _since(window_h: float | None) -> float:
    return time.time() - window_h * 3600 if window_h else 0


def metrics(window_h: float | None = 24, group: str = "module") -> dict:
    assert group in ("module", "model", "kind", "prompt_version")
    spans = _spans("start_ts>=?", (_since(window_h),))
    roots = [s for s in spans if s["parent_id"] is None]
    llm = [s for s in spans if s["kind"] == "llm"]
    retries = [s for s in spans if s["kind"] == "retry"]
    cache = [s for s in spans if s["name"].startswith("cache.") and s["kind"] == "cache"]
    hits = sum(s["name"].startswith("cache.hit") for s in cache)
    lookups = sum(s["name"] in ("cache.hit_exact", "cache.hit_semantic", "cache.miss", "cache.rejected_match") for s in cache)
    guard_roots = [s for s in roots if s["module"] == "trustboundary"]

    def key(s):
        if group == "model":
            return s["attrs_json"].get("model") or "(none)"
        if group == "prompt_version":
            return s["attrs_json"].get("prompt_version") or "(none)"
        return s[group]
    pool = llm if group in ("model", "prompt_version") else roots if group == "module" else spans
    groups: dict = {}
    for s in pool:
        groups.setdefault(key(s), []).append(s)
    table = []
    for g, ss in sorted(groups.items()):
        d = [s["duration_ms"] for s in ss]
        costed = [s for s in ss if s["cost_usd"] is not None]
        table.append({"group": g, "count": len(ss), "errors": sum(s["status"] == "error" for s in ss),
                      "error_rate": round(sum(s["status"] == "error" for s in ss) / len(ss), 3),
                      "p50_ms": pct(d, 50), "p95_ms": pct(d, 95), "p99_ms": pct(d, 99),
                      "tokens": sum((s["input_tokens"] or 0) + (s["output_tokens"] or 0) for s in ss) or None,
                      "cost_usd": round(sum(s["cost_usd"] for s in costed), 6) if costed else None})
    llm_cost = [s["cost_usd"] for s in llm if s["cost_usd"] is not None]
    return {
        "window_h": window_h, "group": group, "table": table,
        "totals": {"requests": len(roots), "spans": len(spans), "errors": sum(s["status"] == "error" for s in roots),
                   "error_rate": round(sum(s["status"] == "error" for s in roots) / len(roots), 3) if roots else None,
                   "llm_calls": len(llm), "llm_p50_ms": pct([s["duration_ms"] for s in llm], 50), "llm_p95_ms": pct([s["duration_ms"] for s in llm], 95),
                   "llm_p99_ms": pct([s["duration_ms"] for s in llm], 99),
                   "tokens": sum((s["input_tokens"] or 0) + (s["output_tokens"] or 0) for s in llm) or None,
                   "cost_usd": round(sum(llm_cost), 6) if llm_cost else None, "llm_calls_without_cost": len(llm) - len(llm_cost),
                   "cached_prompt_tokens": sum(s["cached_tokens"] or 0 for s in llm) or None,
                   "retry_rate": round(len(retries) / len(llm), 3) if llm else None,
                   "cache_hit_rate": round(hits / lookups, 3) if lookups else None,
                   "guardrail_block_rate": round(sum(s["error_type"] == "guardrail_block" for s in guard_roots) / len(guard_roots), 3) if guard_roots else None},
    }


def timeseries(window_h: float = 24, buckets: int = 24) -> dict:
    start = _since(window_h)
    roots = _spans("parent_id IS NULL AND start_ts>=?", (start,))
    width = window_h * 3600 / buckets
    out = []
    for i in range(buckets):
        lo = start + i * width
        b = [s for s in roots if lo <= s["start_ts"] < lo + width]
        out.append({"t": lo, "requests": len(b), "errors": sum(s["status"] == "error" for s in b), "p95_ms": pct([s["duration_ms"] for s in b], 95)})
    return {"bucket_s": width, "points": out}


def failures(window_h: float | None = 24) -> list[dict]:
    """Failure classification: error spans grouped by (module, error_type), with an example each."""
    errs = _spans("status='error' AND start_ts>=?", (_since(window_h),))
    groups: dict = {}
    for s in errs:
        groups.setdefault((s["module"], s["error_type"] or "unclassified"), []).append(s)
    return sorted([{"module": m, "error_type": t, "count": len(v), "example": {"trace_id": v[-1]["trace_id"], "span": v[-1]["name"], "error": v[-1]["error"]}}
                   for (m, t), v in groups.items()], key=lambda x: -x["count"])


# ---- drift -------------------------------------------------------------------------------------------
def psi(baseline: list[float], current: list[float], bins: int = 10) -> float | None:
    """Population stability index with quantile bins from the baseline. <0.1 stable, 0.1-0.25 moderate, >0.25 major."""
    if len(baseline) < bins or len(current) < bins:
        return None
    edges = np.unique(np.quantile(baseline, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    b = np.histogram(np.clip(baseline, edges[0], edges[-1]), edges)[0] / len(baseline)
    c = np.histogram(np.clip(current, edges[0], edges[-1]), edges)[0] / len(current)
    b, c = np.clip(b, 1e-4, None), np.clip(c, 1e-4, None)
    return round(float(np.sum((c - b) * np.log(c / b))), 4)


def drift(baseline_h: float = 24 * 7, current_h: float = 1) -> dict:
    """Compare the most recent `current_h` hours against the preceding baseline window."""
    now = time.time()
    cur = _spans("start_ts>=?", (now - current_h * 3600,))
    base = _spans("start_ts>=? AND start_ts<?", (now - baseline_h * 3600, now - current_h * 3600))
    series = {
        "llm_latency_ms": lambda ss: [s["duration_ms"] for s in ss if s["kind"] == "llm"],
        "llm_input_tokens": lambda ss: [s["input_tokens"] for s in ss if s["kind"] == "llm" and s["input_tokens"]],
        "rag_question_chars": lambda ss: [s["attrs_json"]["question"]["chars"] for s in ss if s["name"] == "rag.ask" and isinstance(s["attrs_json"].get("question"), dict)],
        "request_latency_ms": lambda ss: [s["duration_ms"] for s in ss if s["parent_id"] is None],
    }
    out = {}
    for name, f in series.items():
        b, c = f(base), f(cur)
        v = psi(b, c)
        out[name] = {"psi": v, "baseline_n": len(b), "current_n": len(c), "baseline_median": pct(b, 50), "current_median": pct(c, 50),
                     "verdict": None if v is None else "stable" if v < 0.1 else "moderate shift" if v < 0.25 else "major shift"}
    return {"baseline_h": baseline_h, "current_h": current_h, "series": out}


# ---- alerts ------------------------------------------------------------------------------------------
def _ensure_rules():
    ensure(ALERT_SCHEMA)
    with db() as c:
        if not c.execute("SELECT 1 FROM obs_alert_rules LIMIT 1").fetchone():
            c.executemany("INSERT INTO obs_alert_rules VALUES(?,?,?,?,?,?,?,?,?)",
                          [("rule-" + uuid.uuid4().hex[:6], n, m, mod, op, th, w, 1, lead) for n, m, mod, op, th, w, lead in DEFAULT_RULES])


def rules() -> list[dict]:
    _ensure_rules()
    with db() as c:
        return rows(c.execute("SELECT * FROM obs_alert_rules ORDER BY name"))


def update_rule(rule_id: str, threshold: float | None = None, enabled: bool | None = None, window_min: float | None = None) -> dict:
    _ensure_rules()
    with db() as c:
        if threshold is not None:
            c.execute("UPDATE obs_alert_rules SET threshold=? WHERE id=?", (threshold, rule_id))
        if enabled is not None:
            c.execute("UPDATE obs_alert_rules SET enabled=? WHERE id=?", (int(enabled), rule_id))
        if window_min is not None:
            c.execute("UPDATE obs_alert_rules SET window_min=? WHERE id=?", (window_min, rule_id))
    return next(r for r in rules() if r["id"] == rule_id)


def _metric_value(metric: str, module: str | None, window_min: float):
    m = metrics(window_min / 60, "module")["totals"]
    if metric == "cost_per_request_usd":
        return round(m["cost_usd"] / m["requests"], 6) if m["cost_usd"] and m["requests"] else None
    if metric == "llm_p95_ms":
        return m["llm_p95_ms"]
    if metric == "error_rate" and module:
        row = next((r for r in metrics(window_min / 60, "module")["table"] if r["group"] == module), None)
        return row["error_rate"] if row else None
    return m.get(metric)


def evaluate_alerts() -> list[dict]:
    """Evaluate every enabled rule now; record a firing at most once per rule per window."""
    out = []
    for r in rules():
        if not r["enabled"]:
            continue
        v = _metric_value(r["metric"], r["module"], r["window_min"])
        breached = v is not None and (v > r["threshold"] if r["op"] == ">" else v < r["threshold"])
        fired = False
        if breached:
            with db() as c:
                recent = c.execute("SELECT 1 FROM obs_alerts WHERE rule_id=? AND ts>=?", (r["id"], time.time() - r["window_min"] * 60)).fetchone()
                if not recent:
                    c.execute("INSERT INTO obs_alerts(ts, rule_id, value, message) VALUES(?,?,?,?)",
                              (time.time(), r["id"], v, f"{r['name']}: {v} {r['op']} {r['threshold']} over {r['window_min']} min"))
                    fired = True
            tracing.event("alert.fired" if fired else "alert.still_breached", kind="alert", module="standalone", rule=r["name"], value=v)
        out.append({**r, "value": v, "breached": breached, "fired_now": fired, "no_data": v is None})
    return out


def alert_history(limit: int = 50) -> list[dict]:
    _ensure_rules()
    with db() as c:
        return rows(c.execute("SELECT a.*, r.name FROM obs_alerts a LEFT JOIN obs_alert_rules r ON r.id=a.rule_id ORDER BY a.ts DESC LIMIT ?", (limit,)))


def overview() -> dict:
    """Per-workspace activity for the dashboard, derived from spans only."""
    roots = _spans("parent_id IS NULL")
    out = {}
    for mod, slug in MODULE_SLUG.items():
        ss = [s for s in roots if s["module"] == mod]
        # A guardrail block is an intended outcome, not a failure: count it separately.
        out[slug] = {"module": mod, "requests": len(ss), "errors": sum(s["status"] == "error" and s["error_type"] != "guardrail_block" for s in ss),
                     "blocked": sum(s["error_type"] == "guardrail_block" for s in ss),
                     "p95_ms": pct([s["duration_ms"] for s in ss], 95), "last_ts": max((s["start_ts"] for s in ss), default=None)}
    return {"modules": out}
