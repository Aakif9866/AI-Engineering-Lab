import httpx
import pytest

from lab.core import providers


def _no_network(request):
    raise AssertionError(f"real network call attempted in tests: {request.url}")


@pytest.fixture(autouse=True)
def isolated_lab(tmp_path, monkeypatch):
    """Every test gets its own SQLite/artifacts dir, offline mode, hash embeddings, no network."""
    monkeypatch.setenv("LAB_VAR_DIR", str(tmp_path))
    monkeypatch.setenv("LAB_OFFLINE", "1")
    monkeypatch.setenv("LAB_EMBEDDER", "hash")
    monkeypatch.setenv("LAB_CAPTURE_CONTENT", "0")
    monkeypatch.setattr(providers, "transport", httpx.MockTransport(_no_network))
    monkeypatch.setattr(providers, "_sleep", lambda s: None)
    yield tmp_path


@pytest.fixture
def fake_provider(monkeypatch):
    """Enable the deepseek provider with a fake key; returns a function to install a response handler."""
    monkeypatch.setenv("LAB_OFFLINE", "0")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test0000000000000000secret")
    monkeypatch.setenv("LAB_DEFAULT_PROVIDER", "deepseek")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    def install(handler):
        monkeypatch.setattr(providers, "transport", httpx.MockTransport(handler))
    return install


def completion(text="", tool_calls=None, prompt_tokens=100, completion_tokens=20, cached=0):
    return httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": text, "tool_calls": tool_calls},
                     "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "prompt_cache_hit_tokens": cached},
    })
