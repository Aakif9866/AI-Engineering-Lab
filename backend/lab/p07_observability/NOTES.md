# Notes: LLM observability, explained simply

## The one idea

**Evaluations** tell you what your system will *probably* do before you ship. **Observability** tells you what it *actually* did, for a specific user, on a specific request, right now.

> A customer says "your assistant gave me a wrong answer yesterday".
> If you only logged the final answer, you can't tell whether search found the wrong document, the cache served a stale answer, a guardrail rewrote it, or the model hallucinated.
> With a trace, you open that request and see every step.

## Traces and spans

- A **span** is one timed step with a name, a kind (retrieval, llm, tool, cache, guardrail…), a status (ok or error), and details (model, tokens, cost).
- A **trace** is all the spans of one request, arranged as a tree: a root span with child spans for each step.

Every span records its **parent**. In our code that's automatic: the current span lives in a `ContextVar`, so any span opened inside another becomes its child, even across modules. A SignalLoop request that calls the RAG pipeline, which calls DeepSeek, produces one connected tree with no extra plumbing.

This is the OpenTelemetry model; tools like LangSmith, Langfuse and Phoenix add LLM-specific details on top of it.

## The numbers that matter

**Latency percentiles, not averages.**
- p50: half of requests are faster than this
- p95: 1 in 20 is slower
- p99: 1 in 100 is slower

Averages hide the slow tail, and the tail is what users complain about. One 30-second request among ninety-nine 1-second ones barely moves the average, but that user is furious.

**Cost: only from real usage.** Cost = tokens actually used × price. If either is unknown, we show "unavailable", plus a count of how many calls had no cost data. We never fill in guesses. DeepSeek's prices are labelled *unverified* because we couldn't confirm them from the official page.

**Error rate**, and errors are classified (timeout, rate limit, validation error, tool error…). A guardrail *block* is counted separately from errors, because blocking an attack is success, not failure.

## Leading vs lagging indicators

- **Lagging:** user complaints, cost overruns. By the time you see them, it already hurts.
- **Leading:** **retry rate rising** (the provider is struggling), **cache hit rate falling** (users started asking new kinds of questions). These warn you hours earlier.

Our alert rules include both kinds. Each rule fires **once per window**, so one ongoing problem doesn't send 500 pages.

## Drift: noticing slow change

Some problems never show up in a single request: answers slowly getting longer, latency creeping up, questions changing style. We compare the **distribution** of a value (latency, tokens, question length) between a baseline period and now, using **PSI (population stability index)**:

1. Split the baseline values into 10 equal-sized buckets.
2. See what share of *recent* values falls into each bucket.
3. Add up how far the shares moved: `PSI = Σ (now − before) × ln(now / before)`.

| PSI | Meaning |
|---|---|
| < 0.1 | Stable |
| 0.1 to 0.25 | Moderate shift: look into it |
| > 0.25 | Major shift: something changed (a new model version, new users, a broken step) |

## Privacy: redact *before* writing

Full prompt and answer logs are great for debugging but dangerous: they contain customers' personal data and sometimes secrets. Rules we follow:

1. **Off by default.** Store the text's length and fingerprint only.
2. **When on, redact first.** Emails, phones, cards and IBANs are replaced with `[EMAIL]` and so on *before* anything reaches the database.
3. **Secrets never.** API keys, bearer tokens and `password=…` are scrubbed, including the exact configured key values.
4. **Retention.** Delete old traces on a schedule.

## Same schema as evaluations

MissionReplay stores agent runs as traces in this same table. That means a production trace could become a test case, which the PDF calls the most common missing link in real systems: "if your eval harness and your production tracing log different fields, you can't replay a production trajectory into your eval pipeline."

## Glossary

| Term | Meaning |
|---|---|
| Trace | All the steps of one request |
| Span | One timed step |
| Root span | The top step: the whole request |
| p95 | 95% of requests are faster than this |
| SLO | A target ("p95 under 3 s"), with an alert when it's broken |
| PSI | A number for how much a distribution shifted |
| Sampling | Recording full detail for only some requests, to save cost at scale |
| Retention | How long data is kept before deletion |

## Interview question (from the PDF)

> *A customer reports a wrong agent answer from yesterday; your logs only show the final response. Redesign observability, and diagnose with what you have.*

1. **Now:** use what exists (time window, user, final answer) to narrow candidates; check provider status, deploys and config changes at that time; try to reproduce with the same prompt version.
2. **Redesign:** full tracing with a root span and child spans for retrieval, every model call, every tool call and every guardrail check, each with inputs (redacted), outputs, latency, tokens and versions.
3. **Replayability:** the trace schema equals the eval schema, so the incident becomes a regression test.
4. **Cost and privacy:** redact at write time; sample full traces at high volume, but always keep errors and anomalies in full; set retention.
5. **Distinguish** *preventing* failures (evals, gates) from *detecting* them (observability, alerts on leading indicators). You need both.
