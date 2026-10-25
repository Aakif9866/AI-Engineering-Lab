import re
import time
from collections import defaultdict, deque

MAX_QUESTION_CHARS = 500

# ponytail: phrase list catches the common attacks only, add an LLM/classifier check if evals show misses
INJECTION = re.compile(
    r"ignore (all |any |the |your )?(previous|prior|above|earlier|these)?\s*(instructions|rules|prompt)"
    r"|disregard (all |any |the |your )?(previous|prior|above|earlier)?\s*(instructions|rules|prompt)"
    r"|forget (everything|all|your (rules|instructions))"
    r"|(reveal|show|print|repeat|tell me) (me )?(your|the) (system )?(prompt|instructions|rules)"
    r"|you are now|act as|pretend (to be|you)|developer mode|jailbreak|\bDAN\b",
    re.IGNORECASE,
)

# order matters: cards (long digit runs) before phones
PII = [
    ("CARD", re.compile(r"\b\d(?:[ -]?\d){12,15}\b")),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("PHONE", re.compile(r"\+?\d[\d\s().-]{7,}\d")),
]


def is_injection(text: str) -> bool:
    return bool(INJECTION.search(text))


def mask_pii(text: str) -> str:
    for label, pattern in PII:
        text = pattern.sub(f"[{label}]", text)
    return text


class RateLimiter:
    """Sliding window: at most `max_calls` per `window` seconds for each user."""

    # ponytail: in-memory, resets on restart and is per-process; use Redis if you run several servers
    def __init__(self, max_calls: int = 10, window: float = 60, clock=time.monotonic):
        self.max_calls, self.window, self.clock = max_calls, window, clock
        self.calls: dict[str, deque] = defaultdict(deque)

    def allow(self, user: str) -> bool:
        now, q = self.clock(), self.calls[user]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            return False
        q.append(now)
        return True
