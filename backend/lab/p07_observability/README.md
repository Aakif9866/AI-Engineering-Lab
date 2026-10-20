# 07 · TraceLens: LLM observability

**In one sentence:** every request in the other six workspaces is recorded as a step-by-step trace, and TraceLens lets you search those traces, see how slow and expensive things are, get alerts, and notice when behaviour drifts, without storing private content by default.

## What gets recorded

Each request becomes a **trace**: a tree of **spans**, one per step (timings below are an example).

```
rag.ask                       (root span: the whole request, 412 ms)
├── rag.retrieve              (kind: retrieval, 9 ms)
└── rag.generate              (kind: generation)
    └── llm.deepseek          (kind: llm: tokens in/out, cached tokens, cost, retries)
```

The other workspaces create the same shape: cache decisions (`cache.hit_semantic`), guardrail checks (`guard.input`), tool calls (`tool.dispatch_unit`), evaluations, alerts. The instrumentation lives in `backend/lab/core/tracing.py`; TraceLens is the window onto it.

## Try it in the web app

Open **http://localhost:5173/tracelens**.

1. **Playground & retention:** press **Generate demo traffic**. It runs real offline requests in every module so there's data to look at.
2. **Traces:** filter by module, status or text, and click a trace to see its **waterfall** (which step took how long). Click a span for its details (tokens, cost, error). Set one trace as a baseline and open another to **compare** them step by step. Every "trace ↗" link elsewhere in the app opens here.
3. **Metrics:** request counts, error rate, LLM latency at **p50/p95/p99**, tokens, cost (only from real usage), retry rate, cache hit rate, the provider's prefix-cache tokens. Group by module, model, prompt version or span kind.
4. **Alerts & drift:** six alert rules. Edit a threshold, press **Evaluate now**, and watch one fire (only once per window). Drift compares the last hour against the previous week using **PSI**.
5. **Failures:** errors grouped by module and type, each linked to an example trace.
6. **Playground:** send one traced prompt to a real model (if a key is configured). **Purge** old spans.

## How it works

| File | What it does |
|---|---|
| `backend/lab/core/tracing.py` | `span()` / `event()`, automatic parent-child nesting, redaction before writing, the SQLite span table |
| `backend/lab/core/providers.py` | Every model call creates an `llm` span with real token usage, cost, retries |
| `metrics.py` | Trace search and trees, percentiles, cost, failure classes, PSI drift, alert rules, the dashboard overview |
| `api.py` | HTTP routes, playground, demo traffic, purge |

## Privacy defaults

- `LAB_CAPTURE_CONTENT=0` (default): prompts, answers and documents are stored only as **length + fingerprint**, e.g. `{"chars": 82, "sha256": "3f1a…"}`.
- `LAB_CAPTURE_CONTENT=1`: text is stored, but **emails, phones, card numbers and IBANs are hidden, and API keys and passwords are scrubbed** first.
- Configured API key values are removed word for word from every stored field and error message.
- Retention: **Purge** deletes spans older than `LAB_TRACE_RETENTION_DAYS` (default 14).

## Commands

```bash
cd backend
.venv/bin/python -m pytest tests/test_p07_observability.py tests/test_core.py
curl "http://127.0.0.1:8000/api/observability/metrics?window_h=24&group=module"
```

## Measured results (2026-10-20)

- Tests confirm that percentiles match numpy exactly, that PSI is under 0.1 for identical traffic and over 0.25 for shifted traffic, and that an alert fires once per window.
- A playground request containing an API key, a password and an email address stored **none** of them.
- Across the lab's development: 411 recorded LLM calls costing $0.054 (unverified DeepSeek price), with **73% of prompt tokens served from DeepSeek's prefix cache**.

## Limits and next steps

- Single-machine SQLite; no sampling (every span is kept); no OpenTelemetry export yet.
- **V2:** quality-versus-cost drift, one-click "replay this trace as a MissionReplay test", alerts tied to SignalLoop's release gate, an OTLP exporter.
