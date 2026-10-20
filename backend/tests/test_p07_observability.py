import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lab.core import tracing
from lab.core.db import db
from lab.p07_observability import metrics as m
from tests.conftest import completion


def put(name, kind="llm", module="rag", duration=100.0, status="ok", error_type=None, parent=None, trace=None, cost=None, tokens=(None, None), ts=None, **attrs):
    s = tracing.Span(name=name, kind=kind, module=module, trace_id=trace or name + "-t", parent_id=parent, attrs=attrs)
    s.status, s.error_type = status, error_type
    s.input_tokens, s.output_tokens = tokens
    s.cost_usd = cost
    if ts:
        s.start_ts = ts
    tracing._write(s, s.start_ts + duration / 1000, duration)
    return s


def test_percentiles_are_computed_from_recorded_durations():
    durs = list(range(10, 1010, 10))  # 100 llm spans, 10..1000 ms
    for i, d in enumerate(durs):
        put(f"call{i}", duration=float(d))
    t = m.metrics(None, "kind")["totals"]
    assert t["llm_p50_ms"] == pytest.approx(np.percentile(durs, 50), abs=0.1)
    assert t["llm_p95_ms"] == pytest.approx(np.percentile(durs, 95), abs=0.1)
    assert t["llm_p99_ms"] == pytest.approx(np.percentile(durs, 99), abs=0.1)


def test_cost_counts_only_actual_usage_and_reports_the_gap():
    put("a", cost=0.002, tokens=(100, 50))
    put("b", cost=None, tokens=(80, 20))
    t = m.metrics(None)["totals"]
    assert t["cost_usd"] == pytest.approx(0.002) and t["llm_calls_without_cost"] == 1 and t["tokens"] == 250


def test_trace_tree_and_search_status():
    with tracing.span("root", kind="request", module="rag") as root:
        with tracing.span("child", kind="retrieval"):
            pass
        with tracing.span("gen", kind="generation") as g:
            g.fail("invalid_citation", "bad ref")
    t = m.get_trace(root.trace_id)
    assert [s["name"] for s in t["spans"]] == ["root", "child", "gen"]
    assert [s["depth"] for s in t["spans"]] == [0, 1, 1] and not t["orphans"]
    found = m.search(module="rag")
    assert found[0]["status"] == "degraded" and found[0]["spans"] == 3 and "invalid_citation" in found[0]["error_types"]
    assert m.search(status="ok") == []


def test_failure_classification():
    put("x1", status="error", error_type="timeout", module="rag")
    put("x2", status="error", error_type="timeout", module="rag")
    put("x3", status="error", error_type="guardrail_block", module="trustboundary")
    f = m.failures(None)
    assert f[0] == {**f[0], "module": "rag", "error_type": "timeout", "count": 2}


def test_psi():
    rng = np.random.default_rng(0)
    base = list(rng.normal(100, 10, 2000))
    assert m.psi(base, list(rng.normal(100, 10, 2000))) < 0.1
    assert m.psi(base, list(rng.normal(140, 10, 2000))) > 0.25
    assert m.psi(base[:5], base[:5]) is None  # too little data to judge


def test_drift_windows_use_recorded_spans():
    now = time.time()
    for i in range(30):
        put(f"old{i}", duration=100.0 + i % 5, ts=now - 3 * 3600)
        put(f"new{i}", duration=900.0 + i % 5, ts=now - 60)
    d = m.drift(baseline_h=24, current_h=1)["series"]["llm_latency_ms"]
    assert d["verdict"] == "major shift" and d["baseline_n"] == 30 and d["current_n"] == 30


def test_alert_fires_once_per_window_and_can_be_tuned():
    for i in range(5):
        put(f"slow{i}", duration=20000.0)
    rule = next(r for r in m.rules() if r["metric"] == "llm_p95_ms")
    first = next(r for r in m.evaluate_alerts() if r["id"] == rule["id"])
    second = next(r for r in m.evaluate_alerts() if r["id"] == rule["id"])
    assert first["breached"] and first["fired_now"] and second["breached"] and not second["fired_now"]
    assert len([a for a in m.alert_history() if a["rule_id"] == rule["id"]]) == 1
    m.update_rule(rule["id"], threshold=60000)
    assert not next(r for r in m.evaluate_alerts() if r["id"] == rule["id"])["breached"]


def test_leading_indicator_retry_rate():
    put("call", kind="llm")
    put("retry", kind="retry", parent="x", trace="call-t")
    assert m.metrics(None)["totals"]["retry_rate"] == 1.0


def test_compare_traces_aligns_spans():
    with tracing.span("req", module="rag") as a:
        with tracing.span("step"):
            pass
    with tracing.span("req", module="rag") as b:
        with tracing.span("step") as s:
            s.fail("timeout", "slow")
        with tracing.span("extra"):
            pass
    rows = {r["span"]: r for r in m.compare_traces(a.trace_id, b.trace_id)["rows"]}
    assert rows["step#1"]["b_status"] == "error" and rows["extra#1"]["a_status"] == "absent"


def test_playground_is_traced_and_secrets_never_reach_storage(fake_provider, monkeypatch):
    from lab.api import app
    monkeypatch.setenv("LAB_CAPTURE_CONTENT", "1")
    fake_provider(lambda r: completion("Sure. My key is sk-test0000000000000000secret", prompt_tokens=10, completion_tokens=5))
    res = TestClient(app).post("/api/observability/playground", json={"prompt": "my api_key=hunter2 and email a@b.co"}).json()
    t = m.get_trace(res["trace_id"])
    assert [s["name"] for s in t["spans"]] == ["playground.request", "llm.deepseek"]
    with db() as c:
        dump = json.dumps([dict(r) for r in c.execute("SELECT * FROM spans")])
    assert "hunter2" not in dump and "sk-test0000000000000000secret" not in dump and "a@b.co" not in dump


def test_overview_counts_root_spans_per_workspace():
    put("r1", kind="request", module="cachecraft")
    put("r2", kind="request", module="cachecraft", status="error")
    put("r3", kind="request", module="cachecraft", status="error", error_type="guardrail_block")
    o = m.overview()["modules"]["cachecraft"]
    assert o["requests"] == 3 and o["errors"] == 1 and o["blocked"] == 1
