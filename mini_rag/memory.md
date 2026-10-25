# memory.md: session handoff for mini_rag

Read this first in a new chat. It records who the user is, what was decided, what is done, and exactly where to resume.
Last updated: 2026-10-25. ALL 9 STEPS BUILT. Extra docs: `interview/` (15 interview-prep notes, git-excluded locally via parent .git/info/exclude) and `expand.md` (scaling design: 100s of big files, fast retrieval, deadlines). Corpus is 7 chunks (not 9). Remaining ideas, none required: try Groq live, overlap in chunking, harder attacks + more docs in groundtruth, commit to git (nothing in mini_rag/ committed yet).

## 1. The user and how to teach them

- Knows Python, React, TypeScript, and has built LLM apps. Uses `uv`, never `pip` (global rule).
- Understands the basic RAG flow: PDF -> text extraction -> embeddings -> vector DB; question -> embedding -> similarity match -> LLM writes the answer.
- Does NOT yet understand these (they are "just jargon" to them): **re-ranking, indexing, hybrid search, evals, BM25, ground truth**. Also wants guardrails (stop the LLM answering random or out-of-scope questions).
- Found the big existing lab (`backend/`, `frontend/`) "baffling": seven topics, tracing, DB all at once. So this mini project exists to learn from scratch.

### Teaching rules (the user insisted on these)
1. **One small step at a time.** UPDATED 2026-10-25: do the step first, then explain it briefly. NO checkpoint questions anymore (user: "ignore the checkpoint from now on, I'll go through it once"). Keep explanations short, beginner level, low on maths. Update this file and `imp.md` after every step.
2. **Ask before installs** (they rejected a combined setup command once). Writing files and running tests/safe commands inside this folder needs no "go".
3. **Keep informing them as you go**, with clarity on every piece.
4. **Checkpoint questions after every step** (code flow / why the design / what could go wrong). Wait for their answers. Correct misconceptions, let them retry, do not just hand over answers.
5. Define each jargon term in plain English, with an analogy, before using it repeatedly.
6. Append each newly taught term to `imp.md` right after it is built, tied to the file where it lives.
7. Plain language, short points, easy to follow.

## 2. The project being built (decisions already made)

A single small, production-style RAG app, built from scratch, in this folder (`mini_rag/`). Its own `uv` project. Does not touch the existing lab code.

| Decision | Choice |
|---|---|
| Documents | ~6 short fake company-support docs written by Claude (refund policy, shipping, account help), including deliberately tricky ones (old vs new policy) |
| Guardrails | Everything: off-topic refusal, prompt-injection blocking, PII masking, per-user rate limits, plus output citation check |
| Frontend | Basic Streamlit |
| LLM | Two providers, DeepSeek and Groq (both OpenAI-compatible, called with `httpx`), switchable. Keys come from `.env` |
| `.env` | The user will add it themselves. Do not read or print key values. Names used by the old lab: `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `GROQ_API_KEY`, `GROQ_MODEL`, `LAB_DEFAULT_PROVIDER` |
| Embeddings | `fastembed` (small local ONNX model, ~100 MB first download, no torch). Fallback to a simple hash embedder if the download fails |
| Dependencies planned | `streamlit httpx numpy fastembed` and dev `pytest` |
| Keyword search | Hand-written BM25 (~15 lines) so the user can read it |

## 3. Roadmap and status

| Step | What | Status |
|---|---|---|
| 1 | Project setup: `uv init --bare --name mini-rag --python 3.12`, `uv add streamlit httpx numpy fastembed`, `uv add --dev pytest` | **Done 2026-10-25.** Project and 4 libs were already present; `pytest` added as dev dep. Resources in `docs/resources/uv-commands.md`. Step 1 checkpoints answered (Q1 chunking, Q2 per-question call from our code, Q3 friendly message) |
| 2 | Fake docs + chunking (indexing) | **Built 2026-10-25** (`docs/company/*.md`, `ingest.py`, `tests/test_ingest.py`, 2 tests pass). Checkpoint questions asked, awaiting answers |
| 3 | Embeddings + similarity search (dense retrieval) | **Built 2026-10-25** (`retrieve.py::DenseIndex`, `tests/test_retrieve.py`, 4 tests pass, model bge-small downloaded, cache in `.cache/`). Checkpoint questions asked, awaiting answers. Observed: old refund policy scores 0.768 vs current 0.782; "change my email" ranks account-help#1 above #0 (right doc, wrong chunk) |
| 4 | BM25 + hybrid search merged with reciprocal rank fusion (RRF) | **Built 2026-10-25** (`retrieve.py`: BM25Index, rrf, hybrid_search; 7 tests pass). Step 3 Q1-Q3 answered (Q1/Q2 misread cache as the cause, re-explained; Q3 explained). Step 4 checkpoint questions asked, awaiting answers. Observed: hybrid fixed "change my email"; "24 months" hybrid ranks order-tracking#0 first (it is in both lists) over account-help#0 (BM25 #1 only) |
| 5 | Reranking the top results | **Built 2026-10-25** (`retrieve.py`: `rerank`, `is_retired`, `search` = hybrid pool of 6 -> cross-encoder `Xenova/ms-marco-MiniLM-L-6-v2` -> top 3; 9 tests pass). Fixed "24 months" and old-vs-new refund. Note: top rerank score for the out-of-scope "ship to Mexico?" was -6.9 vs +1.1 to +1.8 for good matches, so a score threshold can feed the refusal logic in steps 6-7 |
| 6 | LLM call with retrieved chunks: prompt, grounding, citations | **Built 2026-10-25** (`config.py` .env reader + provider table, `llm.py::chat` with friendly `LLMError`s, `pipeline.py::ask` -> `Answer(text, sources, citations, status)`; status = answered/refused/no_llm/ungrounded; 14 tests pass). Verified live with DeepSeek (default provider): real answer with valid citation, weather question refused with no LLM call. Groq not yet tried live. `MIN_SCORE=-9` chosen from measured scores |
| 7 | Guardrails (injection, off-topic, PII, rate limit, citation check) | **Built 2026-10-25** (`guardrails.py` + wired into `pipeline.py::ask(question, provider, user)`; new statuses `blocked`, `rate_limited`; 28 tests pass). Off-topic = the Step 6 evidence gate, no separate filter. Injection filter is a phrase list (known ceiling, `ponytail:` comment). Not yet tested live with real attacks beyond unit tests |
| 8 | Ground-truth test questions + evals (Recall@k, MRR, answer/refusal correctness, injection block) | **Built 2026-10-25** (`groundtruth.json` 23 items, `evals.py`; results in imp.md. Live DeepSeek run: 14/14, 4/4, 5/5) |
| 9 | Streamlit screen | **Built 2026-10-25** (`app.py`, `tests/test_app.py` via AppTest; server boot checked; `.gitignore` added so `.env` is never committed). 29 tests pass |
| 10 | `imp.md` grows throughout | seeded with the user's topic list |

Planned layout (flat package, small files): `config.py` (load .env), `llm.py` (providers), `ingest.py` (chunk + index), `retrieve.py` (bm25/dense/hybrid/rerank), `guardrails.py`, `pipeline.py` (`ask()`), `evals.py` + `groundtruth.json`, `app.py` (Streamlit), `docs/*.md`, `tests/`.

## 4. Where we are: pending checkpoint questions (Step 1)

The user has NOT answered these yet. Ask them again at the start of the new chat:
1. Between "text extraction" and "embeddings" there is a step. What is it, and why can't we embed a whole PDF as one block? (answer: chunking)
2. Where will the LLM run, in the Streamlit screen or in the Python code behind it? Once at startup or per question?
3. If the API key is missing or wrong, should the app crash, show a friendly message, or answer without the LLM? Why?

## 5. Facts learned about the existing repo (verified by reading code on 2026-10-25)

Repo root: `/Users/shaikyasin/Documents/AI/7 AI system Design models`. Existing lab, for reference only:
- Frontend (React/Vite) only renders. No model runs in the browser. Vite proxies `/api` to FastAPI on :8000.
- Backend `backend/lab/api.py` mounts 7 routers (`p01_rag` ... `p07_observability`). Shared code in `backend/lab/core/` (config, db, tracing, providers, embeddings, redaction, jobs).
- Where "AI" comes from: MiniLM embeddings run locally (pretrained, not trained here); the answering LLM is DeepSeek/Groq called live per request only if `use_llm` is on; offline mode uses a rule-based extractive answerer; P02 trains a tiny SmolLM2 with LoRA locally.
- RAG request path: `p01_rag/api.py::ask_route` -> `pipeline.py::ask` -> `index.get_index` -> `retrieve.retrieve` (ACL filter, BM25 + dense, RRF, rerank, freshness penalty) -> `generate.answer` (evidence gate, llm/extractive, verify).
- Useful as a reference for the mini project: `backend/lab/p01_rag/retrieve.py` (hybrid + RRF), `generate.py` (evidence gate, verify), `backend/data/p01/benchmark.json` (example ground truth), `backend/lab/core/providers.py` (provider client).

## 6. Environment notes

- Platform macOS, shell zsh. Use `uv` only.
- **claude-mem plugin is not working**: its worker needs the Bun runtime, which is not installed (log: `~/.claude-mem/logs/`). Offered to install via `curl -fsSL https://bun.sh/install | bash`; the user has not approved. Not needed for this project.
- Git: commits should end with the Co-Authored-By line from the session's attribution reminder. Nothing in `mini_rag/` has been committed.

## 7. What the new chat should do first

1. Read this file, `CLAUDE.md` and `imp.md`.
2. Tell the user in 3 lines where we are.
3. Ask the three Step 1 checkpoint questions, then wait.
4. After they answer and say go, run the Step 1 setup, explain the output, and continue the roadmap one step at a time.
