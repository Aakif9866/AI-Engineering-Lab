"""Shared instrumentation: OpenTelemetry-shaped traces and spans persisted to SQLite.

Every module wraps its work in `span(...)`. Spans nest through a ContextVar, so a model call
made inside a retrieval step becomes its child automatically. Redaction happens here, before
anything is persisted (PDF 7: "redact at the tracing layer before it is persisted, not after").
"""
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .config import env, flag
from .db import db, ensure, rows
from .redaction import redact_pii, scrub_secrets

SCHEMA = """
CREATE TABLE IF NOT EXISTS spans(
  span_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, parent_id TEXT,
  name TEXT NOT NULL, kind TEXT NOT NULL, module TEXT NOT NULL,
  start_ts REAL NOT NULL, end_ts REAL, duration_ms REAL,
  status TEXT NOT NULL, error_type TEXT, error TEXT,
  attrs_json TEXT NOT NULL DEFAULT '{}',
  input_tokens INTEGER, output_tokens INTEGER, cached_tokens INTEGER,
  cost_usd REAL, cost_source TEXT
);
CREATE INDEX IF NOT EXISTS ix_spans_trace ON spans(trace_id);
CREATE INDEX IF NOT EXISTS ix_spans_start ON spans(start_ts);
CREATE INDEX IF NOT EXISTS ix_spans_module ON spans(module, kind);
"""

# Attribute keys that carry user/model content. Off by default: only length + hash are kept.
CONTENT_KEYS = {"input", "output", "prompt", "completion", "messages", "query", "question",
                "answer", "document", "text", "correction", "response", "arguments", "observation"}


@dataclass
class Span:
    name: str
    kind: str
    module: str
    trace_id: str
    parent_id: str | None
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    start_ts: float = field(default_factory=time.time)
    status: str = "ok"
    error_type: str | None = None
    error: str | None = None
    attrs: dict = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None
    cost_source: str | None = None
    _t0: float = field(default_factory=time.perf_counter)

    def set(self, **attrs) -> "Span":
        self.attrs.update(attrs)
        return self

    def usage(self, input_tokens=None, output_tokens=None, cached_tokens=None, cost_usd=None, cost_source=None):
        self.input_tokens, self.output_tokens, self.cached_tokens = input_tokens, output_tokens, cached_tokens
        self.cost_usd, self.cost_source = cost_usd, cost_source

    def fail(self, error_type: str, message: str = ""):
        """Mark a handled failure (e.g. a guardrail block) without raising."""
        self.status, self.error_type, self.error = "error", error_type, scrub_secrets(message)[:500]


_current: ContextVar[Span | None] = ContextVar("lab_span", default=None)


def current() -> Span | None:
    return _current.get()


def _protect(value, capture: bool):
    if isinstance(value, str):
        if not capture:
            return {"redacted": True, "chars": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()[:12]}
        return redact_pii(scrub_secrets(value))[0]
    if isinstance(value, (dict, list)):
        return _protect(json.dumps(value, default=str), capture)
    return value


def _clean(attrs: dict) -> dict:
    capture = flag("LAB_CAPTURE_CONTENT")
    out = {}
    for k, v in attrs.items():
        if k in CONTENT_KEYS:
            out[k] = _protect(v, capture)
        elif isinstance(v, str):
            out[k] = scrub_secrets(v)
        else:
            out[k] = v
    return out


def classify_error(exc: BaseException) -> str:
    if getattr(exc, "error_type", None):
        return exc.error_type
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "validation" in name:
        return "validation_error"
    return "exception"


def _write(s: Span, end_ts: float, duration_ms: float) -> None:
    ensure(SCHEMA)
    with db() as c:
        c.execute(
            "INSERT INTO spans VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s.span_id, s.trace_id, s.parent_id, s.name, s.kind, s.module, s.start_ts, end_ts, duration_ms,
             s.status, s.error_type, s.error, json.dumps(_clean(s.attrs), default=str),
             s.input_tokens, s.output_tokens, s.cached_tokens, s.cost_usd, s.cost_source),
        )


@contextmanager
def span(name: str, kind: str = "internal", module: str | None = None, **attrs):
    parent = _current.get()
    s = Span(name=name, kind=kind,
             module=module or (parent.module if parent else "standalone"),
             trace_id=parent.trace_id if parent else uuid.uuid4().hex,
             parent_id=parent.span_id if parent else None, attrs=dict(attrs))
    token = _current.set(s)
    try:
        yield s
    except BaseException as e:
        s.status, s.error_type, s.error = "error", classify_error(e), scrub_secrets(str(e))[:500]
        raise
    finally:
        _current.reset(token)
        _write(s, time.time(), (time.perf_counter() - s._t0) * 1000)


def event(name: str, kind: str = "event", status: str = "ok", error_type: str | None = None, **attrs) -> None:
    """A zero-duration child span: cache decisions, guardrail triggers, gate verdicts."""
    with span(name, kind=kind, **attrs) as s:
        if status != "ok":
            s.fail(error_type or status, attrs.get("reason", ""))


def get_trace(trace_id: str) -> list[dict]:
    ensure(SCHEMA)
    with db() as c:
        return rows(c.execute("SELECT * FROM spans WHERE trace_id=? ORDER BY start_ts", (trace_id,)))


def purge(days: float | None = None) -> int:
    ensure(SCHEMA)
    days = float(days if days is not None else env("LAB_TRACE_RETENTION_DAYS", "14"))
    with db() as c:
        return c.execute("DELETE FROM spans WHERE start_ts < ?", (time.time() - days * 86400,)).rowcount
