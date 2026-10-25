import os

import httpx

from config import DEFAULT_PROVIDER, PROVIDERS


class LLMError(Exception):
    """Message is safe to show to the user."""


def chat(messages: list[dict], provider: str | None = None, timeout: float = 30) -> str:
    name = provider or DEFAULT_PROVIDER
    if name not in PROVIDERS:
        raise LLMError(f"Unknown provider '{name}'. Choose one of: {', '.join(PROVIDERS)}.")
    cfg = PROVIDERS[name]
    key = os.getenv(cfg["key"])
    if not key:
        raise LLMError(f"The {name} API key is missing. Add {cfg['key']} to .env.")
    try:
        r = httpx.post(
            cfg["url"],
            headers={"Authorization": f"Bearer {key}"},
            json={"model": cfg["model"], "messages": messages, "temperature": 0},
            timeout=timeout,
        )
    except httpx.HTTPError:
        raise LLMError(f"Could not reach {name}. Check your connection and try again.") from None
    if r.status_code in (401, 403):
        raise LLMError(f"The {name} API key was rejected. Check {cfg['key']} in .env.")
    if r.status_code != 200:
        raise LLMError(f"{name} returned an error (HTTP {r.status_code}). Try again shortly.")
    return r.json()["choices"][0]["message"]["content"].strip()
