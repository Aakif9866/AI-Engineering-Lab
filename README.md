# AI Engineering Lab

Seven production LLM design patterns, each built as a working system with a labelled benchmark, failure cases, and tests. One local web app, one workspace per pattern. Everything runs offline; DeepSeek and Groq are used only when you turn them on.

The curriculum follows *Seven Design Patterns: A Technical Reference for AI Engineering Interviews and Production Systems* (the PDF in this folder). Each workspace implements one chapter and that chapter's interview case.

| # | Workspace | Pattern | PDF interview case it implements |
|---|---|---|---|
| 01 | **Evidence Atlas** | RAG | Q&A over company documents with weekly updates, citations and access control |
| 02 | **IntentForge** | Fine-tuning | Correct answers in an inconsistent format that downstream systems can't parse |
| 03 | **CacheCraft** | Caching | FAQ system with 100k queries a day, 60% variations of the same questions |
| 04 | **TrustBoundary** | Guardrails & Defensive UX | NL→SQL tool: injection, destructive SQL, least privilege, show before execute |
| 05 | **SignalLoop** | User feedback | Assistant whose quality has plateaued; design the flywheel |
| 06 | **MissionReplay** | Agentic evals | Agent with 85% success and clustered failures; diagnose with trajectory evals |
| 07 | **TraceLens** | LLM observability | Wrong agent answer you can't reproduce because only the final output was logged |

---

## Screenshots

| | |
|---|---|
| ![Overview: all seven workspaces with live traced-request stats](docs/screenshots/01-overview.png)<br>Overview: all seven workspaces with live traced-request stats | ![Evidence Atlas: hybrid retrieval, verified citations, per-passage scores](docs/screenshots/02-evidence-atlas-answer.png)<br>Evidence Atlas: hybrid retrieval, verified citations, per-passage scores |
| ![Evidence Atlas: 24-question benchmark, retrieval vs answer metrics](docs/screenshots/03-evidence-atlas-benchmark.png)<br>Evidence Atlas: 24-question benchmark, retrieval vs answer metrics | ![IntentForge: dataset cleaning, dedup and hash-based splits](docs/screenshots/04-intentforge-dataset.png)<br>IntentForge: dataset cleaning, dedup and hash-based splits |
| ![CacheCraft: no cache vs exact vs semantic on a labelled workload](docs/screenshots/05-cachecraft-workload.png)<br>CacheCraft: no cache vs exact vs semantic on a labelled workload | ![TrustBoundary: prompt injection blocked at the input guardrail](docs/screenshots/06-trustboundary-pipeline.png)<br>TrustBoundary: prompt injection blocked at the input guardrail |
| ![TrustBoundary: 30-case adversarial corpus, which layer stopped each attack](docs/screenshots/07-trustboundary-adversarial.png)<br>TrustBoundary: 30-case adversarial corpus, which layer stopped each attack | ![MissionReplay: scored agent trajectory, step by step](docs/screenshots/08-missionreplay-trajectory.png)<br>MissionReplay: scored agent trajectory, step by step |
| ![SignalLoop: clustered feedback review queue](docs/screenshots/09-signalloop-review-queue.png)<br>SignalLoop: clustered feedback review queue | ![TraceLens: span tree of an LLM agent run with tokens and cost](docs/screenshots/10-tracelens-trace.png)<br>TraceLens: span tree of an LLM agent run with tokens and cost |

---

## Quick start

**Prerequisites:** Python 3.10+, Node 18+, [uv](https://github.com/astral-sh/uv) (or pip), about 1.5 GB of disk for the ML extras and models. Built and tested on macOS (Apple M1, 8 GB RAM).

```bash
cp .env.example .env          # optional: add DEEPSEEK_API_KEY and/or GROQ_API_KEY
make setup                    # backend venv + core and ML deps + frontend deps
make models                   # optional: pre-download MiniLM (~90 MB) + SmolLM2-135M (~270 MB)

make dev                      # backend http://127.0.0.1:8000 (docs at /docs) + UI http://localhost:5173; Ctrl-C stops both
```

Prefer two terminals? `make backend` and `make frontend` run each half on its own.

Short on disk? `make setup-core` skips torch. Every workspace still works: embeddings fall back to a hash embedder (the header says so), and IntentForge offers dataset building and the rules baseline but no training.

Without `make` (the same commands spelled out):

```bash
cd backend && uv venv .venv --python 3.10 && uv pip install --python .venv/bin/python -r requirements.txt -r requirements-ml.txt
.venv/bin/uvicorn lab.api:app --port 8000
cd frontend && npm install && npm run dev
```

**Run the tests** (offline, no network, about 16 s): `make test`, which runs `pytest` in `backend/`. Result at handover: **117 passed**.

---

## Configuration (`.env` at the repo root)

| Variable | Default | Purpose |
|---|---|---|
| `DEEPSEEK_API_KEY` / `GROQ_API_KEY` | unset | Enable a provider. Never logged, never sent to the browser. |
| `DEEPSEEK_MODEL` / `GROQ_MODEL` | `deepseek-flash` / `openai/gpt-oss-20b` | Model ids, verified 2026-10-20 against each provider's model list |
| `LAB_DEFAULT_PROVIDER` | `deepseek` | Used when a workspace doesn't name one |
| `LAB_OFFLINE` | `0` | `1` = never call a paid API, even with keys present |
| `LAB_CAPTURE_CONTENT` | `0` | Store prompt and output text in traces (PII and secrets redacted first). Off = length + hash only |
| `LAB_TRACE_RETENTION_DAYS` | `14` | Age used by TraceLens → Purge |
| `LAB_HTTP_TIMEOUT_S` / `LAB_MAX_RETRIES` | `60` / `2` | Per-request timeout; bounded retries on 429/5xx (honours `Retry-After`) |
| `LAB_EMBEDDER` | `minilm` | `minilm` (sentence-transformers) or `hash` (no download, lexical) |
| `LAB_TORCH_DEVICE` | `cpu` | `mps`/`cuda` for training if you have memory headroom (see Troubleshooting) |

---

## Architecture

```
frontend/  React 18 + TypeScript + Vite + Tailwind 3 + react-router 6     (design: frontend-design-aesthetic skill)
   └─ /api proxied to ↓
backend/   FastAPI
   lab/core/           shared: config · providers (DeepSeek+Groq, one httpx client) · SQLite · tracing + redaction · embeddings · jobs
   lab/p01_rag/        index (chunking, BM25, vectors, incremental sync) · retrieve (hybrid RRF, rerank, ACL) · generate (gate, citations, verify) · evaluate
   lab/p02_finetune/   schema · data (generate, clean, dedup, split) · model (LoRA loop, constrained decoding) · train · evaluate
   lab/p03_cache/      gateway (keys, exact → semantic, TTL, dependency invalidation, events) · workload (labelled traffic, sweep)
   lab/p04_guardrails/ detectors · policy (roles, tools, taint) · sqlguard (3-layer least privilege) · pipeline · adversarial
   lab/p05_feedback/   service (collect, curate, freeze, gate, promote, delete, retain)
   lab/p06_agent_evals/ sim (deterministic world + tools) · agents (careful, reckless, LLM) · evaluate (trajectory metrics, judge)
   lab/p07_observability/ metrics (search, percentiles, cost, failures, PSI drift, alerts)
   data/   committed fixtures: corpus, benchmarks, KB, adversarial corpus, scenarios
   var/    runtime state (gitignored): lab.db, datasets, adapters, results, job logs
```

**Shared instrumentation is the spine.** Every module wraps its work in `tracing.span(...)`. Spans nest through a `ContextVar`, so a model call inside a RAG request inside a SignalLoop request becomes a correctly parented child without any plumbing. Provider calls create `llm` spans with actual token usage and cost. Redaction happens before anything is written. MissionReplay stores agent trajectories as traces, so evals and observability share one schema (PDF 7).

**Dependencies, and why each exists** (pinned in `backend/requirements*.txt`):

| Package | Why |
|---|---|
| fastapi, uvicorn, pydantic | HTTP API; pydantic models are also the schemas for tool arguments and model outputs |
| httpx | Both providers speak the OpenAI chat-completions protocol, so one small client covers them; no vendor SDKs |
| numpy | Vectors, exact cosine search, percentiles, PSI |
| torch, transformers, peft | Real LoRA fine-tuning of SmolLM2-135M-Instruct (optional extra) |
| sentence-transformers | Local MiniLM embeddings; optional cross-encoder reranker (optional extra) |
| pytest | Tests |
| react-router-dom, tailwindcss | Frontend routing and the design system's utility classes. No chart or component libraries: charts are small SVG components |

Deliberately **not** used: vector databases (about 50 chunks fit an exact numpy scan; ANN is on the V2 list), LangChain or agent frameworks (the loops are short and inspectable), Redis (SQLite covers single-node state), TRL (the training loop is 30 explicit lines).

**Providers** (verified 2026-10-20). DeepSeek: base `https://api.deepseek.com`, models `deepseek-flash` and `deepseek-v4-pro` (confirmed live through `GET /models`). Groq: base `https://api.groq.com/openai/v1`, production models `openai/gpt-oss-20b`, `openai/gpt-oss-120b` and `meta-llama/llama-prompt-guard-2-86m`. Groq prices come from its official model table; DeepSeek prices could not be confirmed from the official page and are marked **unverified** everywhere they appear (`backend/lab/core/pricing.json`). Groq was verified live on 2026-10-20 in every workspace (results below).

---

## The seven workspaces

Every "measured" number below was produced by the code in this repository on 2026-10-20 (Apple M1, 8 GB, CPU), and can be reproduced with the command given. Paid runs used DeepSeek `deepseek-flash`.

### 01 · Evidence Atlas: RAG

An investigation corpus of 15 documents about a cold-chain failure at a fictional logistics company. It includes current and superseded policies, a restricted contract, an incident report, **conflicting accounts** (a technician's email against the vendor's), sensor and phone logs, and an unverified rumour.

- **Pipeline:** front-matter and email-header extraction → fixed or section-aware chunking → BM25 + MiniLM vectors → hybrid **reciprocal rank fusion** → idf-coverage or cross-encoder rerank → freshness demotion → context budget → generation.
- **Access control** is a hard pre-filter: restricted text never reaches ranking, the prompt, or the UI.
- **Incremental indexing:** documents are content-hashed and only changed ones are re-embedded. Indexes refuse to mix vectors from different embedders.
- **Abstention:** a pre-generation evidence gate (lexical coverage *or* dense similarity, calibrated on the benchmark), plus the LLM's own abstention.
- **Verification:** every `[S#]` must resolve to a provided passage, quotes must be verbatim, and each sentence's words and numbers must appear in what it cites.
- **Benchmark:** 24 labelled questions (factoid, identifier, temporal, version conflict, multi-hop, paraphrase, 4 unanswerable). Retrieval is scored with Recall@k, MRR and nDCG, separately from answer accuracy, abstention, citation validity and groundedness.

```bash
python -m lab.p01_rag.evaluate                  # offline grid: chunking × retrieval × context budget
python -m lab.p01_rag.evaluate --llm            # adds the LLM generator comparison (~24 calls)
```

**Measured:**
- Retrieval MRR: BM25 0.925, dense (MiniLM) 0.912, dense (hash) 0.793, hybrid 0.950, hybrid + rerank 0.975.
- Answers (hybrid + rerank, k=5): offline extractive generator 75% accuracy and 50% correct abstention; **DeepSeek 100% accuracy, 100% correct abstention, 0% false abstention, 100% valid citations**.
- Lexical groundedness 0.86: it flags correct *derived* claims ("5 hours 20 minutes later") because they are computed, not quoted.

Two bugs were found by measurement and fixed: the lexical gate over-abstained on paraphrases, and reasoning tokens truncated an answer mid-sentence (now detected through `finish_reason`).

**Limits:** small corpus (retrieval sits near ceiling); gate threshold tuned on the evaluation set; lexical, not NLI, groundedness. **V2:** temporal (as-of) retrieval, contradiction pairing across sources, injected misleading documents, NLI groundedness, held-out calibration, iterative retrieval.

### 02 · IntentForge: fine-tuning

Turns messy product-change requests into a strict 7-field decision schema (enums, a boolean and a summary, with business rules such as "the owner team must own the component").

- **Data:** about 700 synthetic examples from seeded templates, with ~8% deliberately corrupted and ~10% duplicated. Cleaning catches every injected problem (schema, business rule, exact duplicate, near duplicate by character 5-gram Jaccard). Splits are assigned by content hash, *after* deduplication, so near-copies can't leak into test.
- **Training:** a **real LoRA SFT run** on `HuggingFaceTB/SmolLM2-135M-Instruct` (r=16, α=32, q/k/v/o projections), with an explicit training loop and the loss masked to the target JSON. Every run records the trainable and frozen parameter counts, the adapted modules, the base revision hash, the dataset hash, and a **checksum of a frozen base weight before and after** as proof that it did not move.
- **Systems compared on the same held-out slices:** keyword rules, the base model with a long instruction prompt, the adapter with a one-line prompt, **schema-constrained decoding** (each enum value chosen by likelihood) on both base and adapter, and optionally DeepSeek prompted in JSON mode. Slices: synthetic test, a **hand-written out-of-distribution slice**, and a general-capability slice to check for forgetting.

```bash
python -m lab.p02_finetune.data                       # build + clean + split
python -m lab.p02_finetune.train --epochs 3           # ~5 min on M1 CPU
python -m lab.p02_finetune.evaluate --system adapter:<run-id>   # also: rules, base_prompted, base_constrained, adapter_constrained:<run-id>, api:deepseek
```

**Measured:** two real LoRA runs on CPU.

| System | Schema-valid | All fields exact (test / OOD) | Component (OOD) | General Qs (forgetting) | Prompt tokens |
|---|---|---|---|---|---|
| rules | 100% | 88% / 40% | 95% | – | – |
| base_prompted (SmolLM2 + long prompt) | 28% | 0% / 0% | 0% | 6/12 | 285 |
| base_constrained | 100% | 0% / 0% | 10% | 6/12 | 285 |
| adapter run-v1 (3 epochs, lr 2e-4) | 44% | 2% / 0% | 25% | 5/12 | **57** |
| adapter_constrained run-v1 | 100% | 2% / 0% | 55% | 5/12 | 57 |
| **adapter run-v2 (6 epochs, lr 3e-4)** | 100% | **30% / 10%** | **85%** | **2/12** | 57 |
| DeepSeek prompted (JSON mode, $0.011) | 97% | 54% / **45%** | 95% | – | 306 |

Run v1: 1,843,200 trainable parameters (1.35%), 134.5M frozen, validation loss 2.91 → 0.19 in 272 s; the frozen-weight checksum was identical before and after.

What the numbers say:
- **Format is learned first.** v1 always produced JSON with the right keys, but invented enum values. Constrained decoding fixed validity, and component accuracy rose from 25% to 55%.
- **Longer training learned the mapping.** v2 reached 98% component accuracy on test and 85% on OOD.
- **But catastrophic forgetting appeared.** General-question accuracy fell from 6/12 to 2/12. This is the PDF's warning made concrete: always evaluate a general-capability slice, and mix general examples into the training data.
- **Baseline first.** A prompted API model still leads on realistic (OOD) requests at 45% exact match, and the hard fields for every system are priority and impact.

**Limits:** a 135M model is small; the data is synthetic; QLoRA isn't available on Apple Silicon. **V2:** hard-negative mining, quantisation, confidence calibration, confidence-aware routing between adapter and API model, DPO from SignalLoop preference pairs.

### 03 · CacheCraft: LLM caching

An FAQ gateway for a fictional note-taking app, with **exact → semantic → upstream** and write-through.

- **Exact key:** normalised question + provider + model + prompt version + temperature + system prompt hash + namespace + (for personal questions) the user.
- **Semantic lookup:** only within the same fingerprint and scope, with a configurable threshold and a "rejected match" band logged just below it.
- **Invalidation:** each entry stores the **content-version hashes** of the knowledge-base articles it was built from. Editing an article evicts exactly the dependent entries, either eagerly or at lookup time.
- **Volatile questions** (live status) bypass the cache. TTL applies. Provider prefix-cache tokens are recorded from real usage.
- **Workload:** a labelled 240-query stream mixing paraphrases, filler-wrapped repeats, **confusable siblings** (refund *within* vs *after* 30 days), personal questions from three users, volatile and unrelated questions, and a mid-stream price change. Every hit is scored for correctness against the true intent and data version.

```bash
python -m lab.p03_cache.workload      # 9 modes + threshold sweep
```

**Measured (MiniLM, offline upstream with modelled 800 ms latency, estimated cost):**

| Mode | Hit rate | False hits | p50 latency | Est. spend |
|---|---|---|---|---|
| no cache | 0% | 0 | 813 ms | $0.00531 |
| exact only | 32% | 0 | 814 ms | $0.00377 |
| semantic @0.90 | 68% | 5 (3%) | 14 ms | $0.00157 |
| semantic @0.95 | 63% | 3 (2%) | 14 ms | $0.00186 |
| @0.90 without dependency check | 69% | **14** | 14 ms | $0.00149 |
| @0.90 without user scoping | 70% | **14** | 14 ms | $0.00149 |

**No threshold reaches zero false hits.** Confusable pairs reach 0.986 similarity, above every true paraphrase pair (max 0.854). That is the PDF's "the threshold is the entire design problem", measured. A real DeepSeek call during development showed 768 of 1018 prompt tokens served from the provider's prefix cache.

**Limits:** pattern-based personalisation detection; sweep tuned on the same paraphrases. **V2:** adaptive per-intent thresholds, workload-aware TTLs, routing by miss difficulty.

### 04 · TrustBoundary: guardrails and defensive UX

Triage of untrusted email and documents that proposes tool actions: read-only SQL, tickets, replies, export.

- **Input:** size limits, NFKC normalisation, zero-width and control-character detection, base64-decoded instruction scanning, a weighted heuristic injection score, an optional Groq Prompt Guard signal, and PII redaction *before* the model sees the text.
- **Model output:** untrusted content is spotlighted in delimiters; output passes a strict schema with **generate → validate → retry (2) → fail closed**.
- **Policy engine (the actual boundary):** role → tool grants, exact tool names, strict argument schemas (one recipient, no smuggled lists), recipient and link rules, PII-in-reply checks, taint (flagged inputs disable high-risk tools), and risk-tiered friction (outbound email and P1 tickets wait for **human approval**, re-checked against the reviewer's role).
- **SQL least privilege in three independent layers:** a textual validator, a `mode=ro` + `query_only` connection, and a **SQLite authorizer callback** that denies sensitive column reads during execution.
- **Output:** PII redaction, markdown-beacon stripping, and defanging of hostile hosts.
- **Corpus:** 30 adversarial and benign cases. The report scores **detection and enforcement separately** and attributes which layer stopped each attack.

```bash
python -m lab.p04_guardrails.adversarial                # offline, simulated compromised model
python -m lab.p04_guardrails.adversarial --mode llm     # DeepSeek as the planner (~25 calls)
```

**Measured:**
- Offline compromised planner: **30/30 enforcement, 45% detection, 0% benign false positives.** `SELECT * FROM customers` passes the textual validator and is stopped by the engine authorizer.
- DeepSeek planner: the first run scored 28/30. It exposed one checker flaw (DeepSeek *refused* the embedded attacks, which my expectations treated as "attack not attempted") and **one real gap**: DeepSeek reported a beacon as a plain-text URL, which the output guardrail didn't catch. Both were fixed with regression tests. After those fixes, 8 runs with the DeepSeek planner: 6 scored 30/30 and 2 scored 29/30. The failing case in those two early runs was not captured; all 6 later runs, with failure output recorded, scored 30/30. LLM-planner results vary from run to run, which is why the corpus should be run repeatedly.

**V2:** versioned policies, learned risk scoring, adversarial regression generation, a red-team dashboard over time.

### 05 · SignalLoop: user feedback

A research assistant over the Evidence Atlas corpus.

- **Collection:** ratings, structured categories, comments, **edit-in-place corrections**, implicit signals (regenerate, copy, edit similarity) and per-item training consent. User ids are stored only as salted hashes, and PII is redacted at intake.
- **Curation:** a review queue with cross-interaction duplicate detection, issue clustering by category plus question similarity, severity scoring, PII and **poisoning** flags (an injection-like correction can't be approved), and approval with required facts. Approval is the **only** path into a dataset, and every example keeps its provenance.
- **Release:** **frozen, content-hashed eval sets** (24 seed items for cold start plus approved feedback; tampering is detected). Candidate-vs-production **release gate:** no accuracy regression > 2 points, no drop in abstention, 100% valid citations, reported failures not worse, no PII in answers. Promotion is refused by the backend without a passing gate; rollback is allowed.
- **Privacy and governance:** deletion cascades to derived examples and invalidates frozen sets that contained them. Retention controls are included, and analytics cover participation, J-curve, top-user share (bias) and flywheel latency.

**Measured (tests):** a hybrid + rerank candidate passes the gate against the BM25 baseline. A candidate with the abstention gate disabled is **blocked** (abstention regresses) and its promotion returns 403.

**V2:** prioritised improvement recommendations, active-learning selection, controlled export of fine-tuning data to IntentForge.

### 06 · MissionReplay: agentic evaluations

A **deterministic** emergency-response simulator with nine validated tools. The world changes while the agent acts: casualties rise, a road closes, a unit becomes unavailable, a routing call times out. Six scenarios target specific failure modes: stale observations, unverified evacuation, a false gas alarm, flaky tools, a tight budget, and a duplicate report that should trigger *no* dispatch.

- **Scored on the trajectory, never on the final message:** success predicates on final state, tool recall over required calls, **action precision**, argument validity, safety violations (with severities), **grounding** (dispatching a unit never observed as available; booking more patients than any report showed), efficiency against a reference, and redundant info calls.
- An optional LLM judge gives per-step scores, stored separately and labelled model-graded. Every run is a trace in TraceLens.

```bash
python -m lab.p06_agent_evals.evaluate                                   # careful vs reckless
python -m lab.p06_agent_evals.evaluate --agents llm --repeats 3 --temperature 0.7
```

**Measured:**
- Deterministic *careful* agent: 6/6 pass. It recovered from a stale-data dispatch in S4, which is recorded as a warning.
- *Reckless* agent: 0/6, with 5 safety violations, precision 0.54 and recall 0.73.
- **DeepSeek tool-calling agent:** 6/6 at temperature 0.2 ($0.0035), and **17/18 at temperature 0.7** ($0.0094). The one failure dispatched units for the duplicate report, a failure a single run would probably have missed.

**Limits:** six scenarios (the PDF suggests 30 to 50); not yet hard enough to separate strong models. **V2:** stochastic scenarios, fault campaigns, adversarial tool results, regression scenarios generated from reviewed failures.

### 07 · TraceLens: LLM observability

The span store every other workspace writes to.

- **Traces:** search, a waterfall view with span inspection, trace comparison, and JSON export.
- **Metrics:** p50/p95/p99 by module, model, prompt version or span kind; error rates; tokens; **cost only from actual usage**, with the number of LLM calls lacking cost data shown alongside.
- **Signals:** provider prefix-cache tokens, retry rate and cache hit rate as leading indicators; failure classification; **PSI drift** between a baseline and the current window.
- **Alerts:** configurable thresholds, evaluated locally and de-duplicated per window.
- **Operations:** retention purge, a standalone traced playground, and an offline demo-traffic generator.
- **Privacy:** content capture is off by default (length plus hash). When on, PII and secrets are redacted before writing, and configured API key values are scrubbed verbatim from every attribute and error. Guardrail blocks are reported separately from errors.

**Measured (tests):** percentiles match numpy on controlled spans; PSI is below 0.1 for identical distributions and above 0.25 for shifted ones; an alert fires once per window and clears after re-tuning; a playground call carrying a key, a password and an email stores none of them.

**V2:** quality-versus-cost drift, trace-to-eval replay into MissionReplay, regression alerts tied to release gates, OTLP export.

---

## Testing

`make test` runs **117 tests** offline in about 16 s. An autouse fixture gives every test its own SQLite and state directory, forces offline mode and the hash embedder, and installs an HTTP transport that **fails the test if anything reaches the network**. Provider behaviour (success, usage and cost, 429 retry, bounded give-up, non-retryable 4xx, key never leaked) is tested against mocked transports.

| Module | What the tests prove |
|---|---|
| core | span nesting; content off by default; PII and secret redaction in capture mode; retry/backoff; no key leakage |
| RAG | identifier-preserving tokens; chunking invariants; incremental sync; embedder mixing refused; ACL; freshness demotion; invalid citations, unsupported numbers and fake quotes flagged; abstention; metric maths |
| Fine-tuning | deterministic generation; every injected bad record caught; leakage-free reproducible splits; parser strictness; per-field scoring; **LoRA training changes only adapter weights** (tiny Llama, no download); full `train.run()` path; constrained decoding always schema-valid |
| Caching | normalisation; config, namespace and user isolation; volatile bypass; TTL; lazy and eager invalidation; stale and cross-user hits detected as false; upstream errors not cached; real usage reused; sweep monotonicity |
| Guardrails | SQL rejections (parametrised); authorizer catches `SELECT *`; read-only connection; hidden and encoded instructions; benign bait; role, recipient, link and PII rules; taint; retry then fail closed; spotlighting; approval re-check; logging; full corpus; defanging |
| Feedback | pseudonymisation; nothing auto-included; PII redaction; duplicates; review rules; poisoning refused; clustering; hash tamper detection; gate blocks safety regression; promotion refused; rollback; deletion cascade; retention |
| Agentic evals | determinism; timeline and faults; argument validation; careful passes all; reckless penalised for the right reasons; **a confident final message alone fails**; grounding; one span per tool call; native tool calls |
| Observability | percentiles; actual-only cost; trace trees; failure classes; PSI; drift windows; alert de-duplication; retry rate; trace comparison; **secrets never stored**; blocked vs errors |

---

## Groq (`openai/gpt-oss-20b`) vs DeepSeek (`deepseek-flash`), measured live

| Workspace | Groq | DeepSeek |
|---|---|---|
| RAG benchmark: accuracy / correct abstention | 95% / 100% | 100% / 100% |
| IntentForge prompted baseline: exact match (test / OOD) | 34% / 40% ($0.0078) | 54% / 45% ($0.011) |
| TrustBoundary adversarial corpus (LLM planner) | 30/30 | 30/30 in 6 of 8 runs |
| MissionReplay agent, 6 scenarios | **1/6** | 6/6 |
| Prompt Guard detector (Groq only) | classic injection 0.999; polite exfiltration 0.0005 (missed; the heuristic caught it) | – |

Testing against Groq found three real problems, all fixed with regression tests:
1. **Malformed tool calls.** `gpt-oss` sometimes emits tool-call arguments that aren't valid JSON, and Groq rejects them server-side with HTTP 400 `tool_use_failed`. The agent used to abort; now the error is recorded as an invalid-argument step and fed back so the model can retry.
2. **Typographic Unicode.** `gpt-oss` writes `R‑17`, `30 minutes` and `【S1】`, which made correct answers fail string checks and citations go unparsed. Model output is now canonicalised. Before the fix, Groq's RAG accuracy read 75% instead of 95%.
3. **Environment variable name.** The key was set as `GROQ_API`; the lab expects `GROQ_API_KEY` (see `.env.example`).

The Groq agent's low score is real model behaviour, not an integration fault: in S4 it confirmed the chlorine hazard and then concluded "no evacuation required"; in S5 it never booked a hospital bed.

## Cost and API handling

- Keys are read only from the environment, never logged, never returned by the API (`/api/status` exposes only configured or usable flags), and scrubbed from error messages and spans.
- Every paid action in the UI is an explicit toggle labelled as paid. Unit tests never make real calls.
- Costs are shown only when both a price and real usage exist, labelled "usage × verified price" or "usage × UNVERIFIED price". Offline estimates are labelled "estimated".
- Real spend while building and verifying this lab, from recorded spans: **411 LLM calls, $0.054** at the unverified DeepSeek price (plus the IntentForge API baseline below). **73% of all prompt tokens** (319,737 of 436,907) were served from DeepSeek's automatic prefix cache, which is the PDF's prefix/KV caching (3c) showing up in real usage.

## Documents

Each workspace has two plain-language guides in its module folder: **README.md** (what it is, how to use it in the web app, how it works, measured results) and **NOTES.md** (the concepts explained simply, a glossary, lessons from building it, and the PDF interview question):

| Workspace | Guides |
|---|---|
| 01 Evidence Atlas | [README](backend/lab/p01_rag/README.md) · [NOTES](backend/lab/p01_rag/NOTES.md) |
| 02 IntentForge | [README](backend/lab/p02_finetune/README.md) · [NOTES](backend/lab/p02_finetune/NOTES.md) |
| 03 CacheCraft | [README](backend/lab/p03_cache/README.md) · [NOTES](backend/lab/p03_cache/NOTES.md) |
| 04 TrustBoundary | [README](backend/lab/p04_guardrails/README.md) · [NOTES](backend/lab/p04_guardrails/NOTES.md) |
| 05 SignalLoop | [README](backend/lab/p05_feedback/README.md) · [NOTES](backend/lab/p05_feedback/NOTES.md) |
| 06 MissionReplay | [README](backend/lab/p06_agent_evals/README.md) · [NOTES](backend/lab/p06_agent_evals/NOTES.md) |
| 07 TraceLens | [README](backend/lab/p07_observability/README.md) · [NOTES](backend/lab/p07_observability/NOTES.md) |


- [docs/LEARNING_PATH.md](docs/LEARNING_PATH.md): ten sessions pairing PDF chapters with lab exercises and code to read
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md): symptoms, causes and fixes, most of them hit while building this

## Known limitations (whole lab)

- Single-user local application: no authentication. Roles in TrustBoundary are selected in the UI to demonstrate backend enforcement.
- SQLite and in-process indexes are sized for a laptop. Every module states its own scaling path in V2.
- DeepSeek prices are unverified (see Architecture).
- Deployment is out of scope.
