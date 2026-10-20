import json

import httpx
import numpy as np
import pytest

from lab.core import providers, tracing
from lab.core.db import db
from lab.core.embeddings import HashEmbedder
from tests.conftest import completion


def all_spans():
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM spans ORDER BY start_ts")]


def test_spans_nest_and_share_trace():
    with tracing.span("root", module="rag") as root:
        with tracing.span("child", kind="retrieval") as child:
            tracing.event("cache.miss", kind="cache")
    spans = {s["name"]: s for s in all_spans()}
    assert {s["trace_id"] for s in spans.values()} == {root.trace_id}
    assert spans["child"]["parent_id"] == root.span_id
    assert spans["cache.miss"]["parent_id"] == child.span_id
    assert spans["child"]["module"] == "rag"  # inherited from parent
    assert spans["root"]["duration_ms"] >= spans["child"]["duration_ms"]


def test_content_not_stored_by_default_and_errors_recorded():
    with pytest.raises(ValueError):
        with tracing.span("x", question="my email is a@b.co", answer="secret plan"):
            raise ValueError("boom")
    s = all_spans()[0]
    assert "a@b.co" not in s["attrs_json"] and "secret plan" not in s["attrs_json"]
    assert json.loads(s["attrs_json"])["question"]["chars"] == len("my email is a@b.co")
    assert s["status"] == "error" and s["error"] == "boom"


def test_capture_mode_still_redacts_pii_and_secrets(monkeypatch):
    monkeypatch.setenv("LAB_CAPTURE_CONTENT", "1")
    with tracing.span("x", question="mail a@b.co key sk-abcdefghijklmnopqrstu", note="token=hunter2"):
        pass
    a = all_spans()[0]["attrs_json"]
    assert "a@b.co" not in a and "sk-abcdef" not in a and "hunter2" not in a
    assert "[EMAIL]" in a


def test_chat_success_records_usage_and_cost(fake_provider):
    fake_provider(lambda r: completion("hello", prompt_tokens=1000, completion_tokens=500, cached=200))
    res = providers.chat([{"role": "user", "content": "hi"}], module="test")
    assert res.text == "hello" and res.attempts == 1 and res.cached_tokens == 200
    # 800 uncached*0.14 + 200 cached*0.0028 + 500*0.28 per 1M
    assert res.cost_usd == pytest.approx((800 * 0.14 + 200 * 0.0028 + 500 * 0.28) / 1e6)
    assert "UNVERIFIED" in res.cost_source
    s = [x for x in all_spans() if x["kind"] == "llm"][0]
    assert s["input_tokens"] == 1000 and s["module"] == "test"


def test_chat_retries_rate_limit_then_succeeds(fake_provider):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1"}, json={}) if len(calls) == 1 else completion("ok")
    fake_provider(handler)
    res = providers.chat([{"role": "user", "content": "hi"}])
    assert res.attempts == 2 and len(calls) == 2
    assert any(s["kind"] == "retry" for s in all_spans())


def test_chat_gives_up_after_bounded_retries(fake_provider, monkeypatch):
    monkeypatch.setenv("LAB_MAX_RETRIES", "2")
    calls = []
    fake_provider(lambda r: (calls.append(1), httpx.Response(503, text="down"))[1])
    with pytest.raises(providers.ProviderError):
        providers.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 3


def test_client_error_not_retried_and_key_never_leaks(fake_provider):
    calls = []

    def handler(req):
        calls.append(req)
        assert req.headers["authorization"] == "Bearer sk-test0000000000000000secret"
        return httpx.Response(400, text="bad key sk-test0000000000000000secret")
    fake_provider(handler)
    with pytest.raises(providers.ProviderError) as e:
        providers.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1
    assert "sk-test0000000000000000secret" not in str(e.value)
    assert "sk-test0000000000000000secret" not in json.dumps(all_spans())


def test_offline_mode_refuses_calls():
    with pytest.raises(providers.ProviderUnavailable):
        providers.chat([{"role": "user", "content": "hi"}])
    assert providers.status()["default_provider"] is None


def test_hash_embedder_deterministic_and_normalised():
    e = HashEmbedder()
    v = e.embed(["refund policy for annual plans", "refund policy for annual plan", "volcano eruption"])
    assert np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-5)
    assert np.array_equal(v[0], e.embed(["refund policy for annual plans"])[0])
    assert v[0] @ v[1] > v[0] @ v[2]
