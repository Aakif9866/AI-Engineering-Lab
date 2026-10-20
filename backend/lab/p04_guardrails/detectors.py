"""Input guardrails: normalisation, hidden-content detection, PII redaction and an injection risk score.

The heuristic detector is fast and explainable but bypassable; the optional model detector
(Groq's Llama Prompt Guard 2) is a second signal. Neither is the security boundary; the
policy engine is. The adversarial report scores detection and enforcement separately for that reason.
"""
import base64
import re
import unicodedata

from lab.core import providers, tracing
from lab.core.redaction import redact_pii

MAX_CHARS = 20_000
_ZERO_WIDTH = re.compile(r"[​-‏⁠⁡-⁤﻿]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# (rule id, weight, pattern). Weights are combined as 1 - prod(1 - w): independent evidence accumulates.
RULES = [
    ("override_instructions", 0.75, r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|system)\b[^.\n]{0,20}\b(instructions?|rules|prompt|guidelines)\b"),
    ("role_reassignment", 0.5, r"\byou are (now|no longer)\b|\bact as (an? )?(admin|administrator|developer|system)\b|\bdeveloper mode\b|\bjailbreak\b"),
    ("prompt_probe", 0.5, r"\b(reveal|print|show|repeat)\b[^.\n]{0,30}\b(system prompt|hidden instructions|your instructions)\b"),
    ("fake_system_block", 0.6, r"(<\|im_start\|>|<\|system\|>|###\s*system|\[system\]|BEGIN SYSTEM|END SYSTEM|</?untrusted_document>)"),
    ("tool_invocation", 0.55, r"\b(call|invoke|use|run|execute)\b[^.\n]{0,20}\b(send_reply|export_customer_data|query_sales_db|create_ticket)\b"),
    ("exfil_send", 0.55, r"\b(send|forward|email|cc|bcc)\b[^.\n]{0,60}\b(to|at)\b[^.\n]{0,10}[\w.+-]+@(?!meridian\.example)[\w-]+\.[\w.]+"),
    ("exfil_markdown_image", 0.7, r"!\[[^\]]*\]\(https?://[^)]*[?&][^)]*=" ),
    ("secrecy", 0.4, r"\b(do not|don't|never)\b[^.\n]{0,20}\b(tell|inform|mention|reveal)\b[^.\n]{0,20}\b(user|anyone|operator|human)\b"),
    ("payment_redirect", 0.45, r"\b(new|updated|changed)\b[^.\n]{0,30}\b(bank|account|iban|wire|payment details)\b"),
    ("bulk_data_request", 0.45, r"\b(all|every|entire|full)\b[^.\n]{0,25}\b(customer|customers|user)\b[^.\n]{0,20}\b(data|records|emails|list|database|details)\b"),
    ("sql_in_text", 0.35, r"\b(drop\s+table|delete\s+from|union\s+select|;\s*--|sqlite_master|from\s+secrets)\b"),
]
_COMPILED = [(r, w, re.compile(p, re.I)) for r, w, p in RULES]


def normalise(text: str) -> tuple[str, list[str]]:
    """NFKC-normalise and remove invisible characters. Invisible text is itself a risk signal."""
    notes = []
    if _ZERO_WIDTH.search(text):
        notes.append("zero_width_characters")
    if _CONTROL.search(text):
        notes.append("control_characters")
    clean = _CONTROL.sub("", _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text)))
    return clean, notes


def _decoded_base64(text: str) -> list[str]:
    out = []
    for blob in re.findall(r"[A-Za-z0-9+/]{24,}={0,2}", text):
        try:
            s = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode("utf-8")
        except Exception:
            continue
        if s.isprintable() and len(s) > 10:
            out.append(s)
    return out


def heuristic_risk(text: str, hidden_notes: list[str]) -> dict:
    hits = []
    for scope, body in [("text", text)] + [("base64", b) for b in _decoded_base64(text)]:
        for rule, w, rx in _COMPILED:
            if m := rx.search(body):
                hits.append({"rule": rule, "weight": w, "where": scope, "match": m.group(0)[:80]})
    if "zero_width_characters" in hidden_notes:
        hits.append({"rule": "hidden_text", "weight": 0.35, "where": "text", "match": "invisible characters removed"})
    if any(h["where"] == "base64" for h in hits):
        hits.append({"rule": "encoded_instructions", "weight": 0.4, "where": "base64", "match": "instructions found inside base64"})
    p_safe = 1.0
    for h in {h["rule"]: h for h in hits}.values():  # each rule counts once
        p_safe *= 1 - h["weight"]
    return {"score": round(1 - p_safe, 3), "hits": hits}


def model_risk(text: str) -> dict:
    """Groq's meta-llama/llama-prompt-guard-2-86m, when a Groq key is configured. A signal only."""
    if not providers.available("groq"):
        return {"available": False, "reason": "GROQ_API_KEY not configured"}
    try:
        r = providers.chat([{"role": "user", "content": text[:2000]}], provider="groq",
                           model="meta-llama/llama-prompt-guard-2-86m", temperature=0.0, max_tokens=8,
                           reasoning_effort=None, module="trustboundary")
        try:
            score = float(r.text.strip())
        except ValueError:
            score = 1.0 if "malicious" in r.text.lower() or "injection" in r.text.lower() else 0.0
        return {"available": True, "score": round(score, 3), "raw": r.text.strip()[:40], "model": r.model}
    except providers.ProviderError as e:
        return {"available": False, "reason": f"{e.error_type}: detector call failed; heuristic signal used alone"}


def inspect(text: str, redact_kinds: set[str] | None, use_model: bool) -> dict:
    with tracing.span("guard.input", kind="guardrail", module="trustboundary") as sp:
        too_long = len(text) > MAX_CHARS
        clean, hidden = normalise(text[:MAX_CHARS])
        redacted, pii = redact_pii(clean, redact_kinds) if redact_kinds else (clean, [])
        h = heuristic_risk(clean, hidden)
        m = model_risk(clean) if use_model else {"available": False, "reason": "disabled"}
        score = max(h["score"], m.get("score", 0.0) if m.get("available") else 0.0)
        sp.set(risk=score, rules=[x["rule"] for x in h["hits"]], pii=len(pii), hidden=hidden)
        return {"too_long": too_long, "hidden": hidden, "text_for_model": redacted,
                "pii": [{"kind": f.kind, "value_masked": f.value[:2] + "…"} for f in pii],
                "heuristic": h, "model_detector": m, "risk": score}
