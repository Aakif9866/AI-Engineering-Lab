"""Public deploys must never spend the owner's .env keys; visitors bring their own per request."""
from fastapi.testclient import TestClient

from lab.api import app
from lab.core import providers
from tests.conftest import completion


def _live(r):
    return {p["name"] for p in r.json()["providers"] if p["usable"]}


def test_public_mode_ignores_server_keys_and_uses_visitor_keys(fake_provider, monkeypatch):
    monkeypatch.setenv("LAB_PUBLIC", "1")
    c = TestClient(app)
    assert _live(c.get("/api/status")) == set()                     # owner's DEEPSEEK_API_KEY is ignored
    assert _live(c.get("/api/status", headers={"X-Groq-Key": "gsk-visitor"})) == {"groq"}
    assert _live(c.get("/api/status")) == set()                     # visitor key does not leak to the next request


def test_visitor_key_is_what_gets_sent(fake_provider, monkeypatch):
    monkeypatch.setenv("LAB_PUBLIC", "1")
    sent = []
    fake_provider(lambda req: sent.append(req.headers["authorization"]) or completion("ok"))
    token = providers.request_keys.set({"deepseek": "sk-visitor"})
    try:
        providers.chat([{"role": "user", "content": "hi"}], "deepseek")
    finally:
        providers.request_keys.reset(token)
    assert sent == ["Bearer sk-visitor"]


def test_local_mode_still_uses_env_keys(fake_provider, monkeypatch):
    monkeypatch.setenv("LAB_PUBLIC", "0")
    assert _live(TestClient(app).get("/api/status")) == {"deepseek"}


def test_public_mode_never_stores_prompt_text(monkeypatch):
    from lab.core import tracing
    monkeypatch.setenv("LAB_CAPTURE_CONTENT", "1")
    monkeypatch.setenv("LAB_PUBLIC", "1")
    assert tracing._clean({"input": "my private question"})["input"]["redacted"] is True
