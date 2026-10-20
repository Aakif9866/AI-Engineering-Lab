"""Secret scrubbing and PII detection/redaction, shared by tracing, guardrails and feedback.

Regex detection is a deliberate, documented floor: it is fast and deterministic but misses
names, addresses and obfuscated values. Treat it as one layer, not a guarantee.
"""
import os
import re
from dataclasses import dataclass

_SECRET_RES = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxai-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b(\s*[:=]\s*)(\S+)"),
]
_KEY_ENVS = ("DEEPSEEK_API_KEY", "GROQ_API_KEY")


def scrub_secrets(text: str) -> str:
    if not text:
        return text
    for name in _KEY_ENVS:  # exact configured values first: catches keys with unknown formats
        val = os.environ.get(name, "")
        if len(val) >= 8:
            text = text.replace(val, "[SECRET]")
    for rx in _SECRET_RES:
        text = rx.sub(lambda m: (m.group(1) + m.group(2) + "[SECRET]") if m.lastindex == 3 else "[SECRET]", text)
    return text


@dataclass
class PIIFinding:
    kind: str
    start: int
    end: int
    value: str


_PII_RES = {
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "card": re.compile(r"\b(?:\d[ \-]?){13,19}\b"),
    "phone": re.compile(r"(?<![\w-])(?:\+?\d{1,3}[ .\-]?)?(?:\(\d{3}\)|\d{3})[ .\-]\d{3}[ .\-]\d{4}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
}


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def detect_pii(text: str, kinds: set[str] | None = None) -> list[PIIFinding]:
    found: list[PIIFinding] = []
    taken: list[tuple[int, int]] = []
    for kind, rx in _PII_RES.items():  # dict order = priority; earlier kinds win overlaps
        if kinds and kind not in kinds:
            continue
        for m in rx.finditer(text or ""):
            if kind == "card":
                digits = re.sub(r"\D", "", m.group())
                if not (13 <= len(digits) <= 19 and _luhn(digits)):
                    continue
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            found.append(PIIFinding(kind, m.start(), m.end(), m.group()))
    return sorted(found, key=lambda f: f.start)


def redact_pii(text: str, kinds: set[str] | None = None) -> tuple[str, list[PIIFinding]]:
    findings = detect_pii(text, kinds)
    out = text
    for f in reversed(findings):
        out = out[: f.start] + f"[{f.kind.upper()}]" + out[f.end:]
    return out, findings


if __name__ == "__main__":
    t, f = redact_pii("mail a.b@x.io, call 415-555-0134, card 4111 1111 1111 1111, ssn 123-45-6789, order 1234567890123")
    assert [x.kind for x in f] == ["email", "phone", "card", "ssn"], f
    assert "4111" not in t and "order 1234567890123" in t
    assert scrub_secrets("api_key=abc123 Bearer abcdefghijklmnop") == "api_key=[SECRET] [SECRET]"
    print("ok")
