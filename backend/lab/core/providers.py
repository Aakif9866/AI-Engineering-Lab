"""One client for both providers. DeepSeek and Groq both expose OpenAI-compatible
/chat/completions, so a single httpx implementation covers them; no SDK needed.

Verified 2026-10-20: DeepSeek base https://api.deepseek.com (models via GET /models: deepseek-flash,
deepseek-v4-pro); Groq base https://api.groq.com/openai/v1 (production: openai/gpt-oss-20b, -120b).
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import tracing
from .config import env, offline
from .redaction import scrub_secrets

PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "key_env": "DEEPSEEK_API_KEY",
                 "model_env": "DEEPSEEK_MODEL", "default_model": "deepseek-flash"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
             "model_env": "GROQ_MODEL", "default_model": "openai/gpt-oss-20b"},
}
PRICING = json.loads((Path(__file__).parent / "pricing.json").read_text())

transport: httpx.BaseTransport | None = None   # tests inject httpx.MockTransport here
_sleep = time.sleep                             # tests replace to avoid real backoff waits


class ProviderError(Exception):
    error_type = "provider_error"


class ProviderUnavailable(ProviderError):
    error_type = "not_configured"


class RateLimited(ProviderError):
    error_type = "rate_limit"


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str
    latency_ms: float
    attempts: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None
    cost_source: str | None = None
    tool_calls: list = field(default_factory=list)
    finish_reason: str | None = None
    trace_id: str | None = None


def _key(name: str) -> str:
    k = env(PROVIDERS[name]["key_env"])
    return "" if k.startswith("your-") else k


def model_for(name: str) -> str:
    return env(PROVIDERS[name]["model_env"]) or PROVIDERS[name]["default_model"]


def available(name: str | None = None) -> bool:
    if offline():
        return False
    return bool(_key(name)) if name else any(_key(n) for n in PROVIDERS)


def default_provider() -> str | None:
    if offline():
        return None
    pref = env("LAB_DEFAULT_PROVIDER", "deepseek")
    if pref in PROVIDERS and _key(pref):
        return pref
    return next((n for n in PROVIDERS if _key(n)), None)


def status() -> dict:
    return {
        "offline_forced": offline(),
        "default_provider": default_provider(),
        "providers": [
            {"name": n, "configured": bool(_key(n)), "usable": available(n), "model": model_for(n),
             "price": PRICING.get(n, {}).get(model_for(n))}
            for n in PROVIDERS
        ],
    }


def price_cost(provider: str, model: str, inp: int | None, out: int | None, cached: int | None):
    """Cost from *actual* usage x configured price. Returns (None, reason) when either is missing."""
    p = PRICING.get(provider, {}).get(model)
    if p is None or inp is None or out is None:
        return None, "unavailable: no price configured" if p is None else "unavailable: no usage returned"
    cached = cached or 0
    usd = ((inp - cached) * p["input"] + cached * p.get("cached_input", p["input"]) + out * p["output"]) / 1e6
    return usd, "usage x verified price" if p.get("verified") else "usage x UNVERIFIED price"


def chat(messages: list[dict], provider: str | None = None, model: str | None = None, *,
         temperature: float = 0.2, max_tokens: int = 800, json_mode: bool = False,
         tools: list | None = None, reasoning_effort: str | None = "low",
         module: str | None = None, prompt_version: str | None = None) -> ChatResult:
    provider = provider or default_provider()
    if not provider or not available(provider):
        raise ProviderUnavailable(f"provider '{provider or 'none'}' is not configured (offline mode)")
    cfg = PROVIDERS[provider]
    model = model or model_for(provider)
    body: dict = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    retries = int(env("LAB_MAX_RETRIES", "2"))
    timeout = float(env("LAB_HTTP_TIMEOUT_S", "60"))

    with tracing.span(f"llm.{provider}", kind="llm", module=module, provider=provider, model=model,
                      prompt_version=prompt_version, messages=messages, json_mode=json_mode) as sp:
        t0 = time.perf_counter()
        last: Exception | None = None
        with httpx.Client(base_url=cfg["base_url"], timeout=timeout, transport=transport) as client:
            for attempt in range(1, retries + 2):
                try:
                    r = client.post("/chat/completions", json=body,
                                    headers={"Authorization": f"Bearer {_key(provider)}"})
                except httpx.TimeoutException as e:
                    last = ProviderError(f"timeout after {timeout}s")
                    last.error_type = "timeout"
                    wait = min(2 ** attempt, 8)
                else:
                    if r.status_code == 200:
                        break
                    detail = scrub_secrets(r.text[:300])
                    if r.status_code == 429:
                        last = RateLimited(f"{provider} rate limited (429): {detail}")
                        wait = min(float(r.headers.get("retry-after", 2 ** attempt)), 20)
                    elif r.status_code >= 500:
                        last = ProviderError(f"{provider} server error {r.status_code}: {detail}")
                        wait = min(2 ** attempt, 8)
                    else:  # 4xx other than 429: retrying will not help
                        raise ProviderError(f"{provider} rejected request ({r.status_code}): {detail}")
                if attempt <= retries:
                    tracing.event("llm.retry", kind="retry", attempt=attempt, reason=str(last))
                    _sleep(wait)
            else:
                raise last  # type: ignore[misc]

        data = r.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})
        u = data.get("usage") or {}
        cached = u.get("prompt_cache_hit_tokens")  # DeepSeek
        if cached is None:
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")  # OpenAI-style (Groq)
        inp, out = u.get("prompt_tokens"), u.get("completion_tokens")
        cost, source = price_cost(provider, model, inp, out, cached)
        res = ChatResult(text=msg.get("content") or "", provider=provider, model=model,
                         latency_ms=(time.perf_counter() - t0) * 1000, attempts=attempt,
                         input_tokens=inp, output_tokens=out, cached_tokens=cached,
                         cost_usd=cost, cost_source=source, tool_calls=msg.get("tool_calls") or [],
                         finish_reason=choice.get("finish_reason"), trace_id=sp.trace_id)
        sp.usage(inp, out, cached, cost, source)
        sp.set(output=res.text, attempts=attempt, finish_reason=res.finish_reason,
               tool_calls=len(res.tool_calls))
        return res
