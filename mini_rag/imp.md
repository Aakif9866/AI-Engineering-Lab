# imp.md: important topics and work practice

Two parts. Part A is your list, saved as given. Part B is the RAG and evals jargon, which gets filled in step by step as we build it, each term tied to the file where you can see it.

---

## Part A: Production LLM concepts (your list)

Study order you were given: 5, 6, 8, 12-15, 17-18, then the rest.
Note: your list says RAG, embeddings, vector DBs, fine-tuning and stored chat history are "not used" in that system. In this project we DO use RAG, so learn those alongside.

### Foundations
- **LLM.** A model that reads text and writes text. It only knows its training plus what you put in the request.
- **Prompt.** The text you send. A system part (fixed rules and role) and a user part (the question).
- **Tokens and context window.** Models read and bill by tokens. The context window is how much text fits in one request.
- **Model parameters.** Reasoning effort, temperature, max output length. They trade quality against cost and speed.

### Making the model use real data
- **Tool use (function calling).** You describe functions (name, description, input schema). The model asks to call one, your code runs it, you return the result.
- **Agent loop.** Repeat "ask the model, run requested tools, return results" until a final answer. Every round costs money and time.
- **Structured tool schemas.** Strict input definitions make requests predictable and checkable.

### Reliability and accuracy
- **Grounding.** Only accept answers based on tool results. Discard free-text answers that came with no data lookup.
- **Hallucination.** The model confidently invents facts. Reduce with grounding, showing sources, and re-querying instead of trusting earlier numbers.
- **Controlled refusals.** The model declines through a dedicated tool with a reason code, with fixed wording per reason, so refusals read the same every time.
- **Conversation memory.** Earlier turns are passed back as context. Treat them as untrusted text and re-verify any figures.

### Security
- **Prompt injection.** Users or data try to override instructions ("ignore the rules and show everything").
- **Server-side scope.** Permissions and data boundaries are decided by your code, never by the model or user text.
- **Argument whitelisting.** Strip any tool argument that was not declared, so the model cannot add things like a user or project id.
- **Least privilege for tools.** Show the model only the tools the current user may use.
- **Data minimisation.** Send the provider only what is needed, such as aggregated results and not raw records.

### Cost and performance
- **Prompt caching.** The fixed part of the prompt is cached, so keep volatile text (like the current time) out of it.
- **Round and time limits.** Cap loop iterations and total time per question.
- **Timeouts and retries.** A limit per request, and retry once on transient failure.
- **Rate limiting.** Cap requests per caller to control cost and abuse.
- **Kill switch.** A config flag plus a key check that turns the feature off safely.

### Hands-on practice (from your list)
Build a small agent loop with two or three toy tools, then break it with injection attempts. We will do the injection part against the mini RAG app in the guardrails step.

---

## Part B: RAG and evals jargon (filled in as we build)

| Term | Plain meaning | Built in step | File |
|---|---|---|---|
| Chunking | Cutting a document into small pieces (like index cards from a textbook) | 2 | `ingest.py::chunk_text` |
| Indexing | Preparing chunks so they can be searched fast. Right now it's just a list with ids; it gets richer in steps 3-4 | 2 | `ingest.py::load_chunks` |
| Embedding | Turning text into a list of numbers (384 here) that captures meaning. Similar meaning = numbers pointing the same way | 3 | `retrieve.py::DenseIndex.__init__` |
| Dense retrieval | Search by meaning: embed the question, score every chunk by dot product, take the top k | 3 | `retrieve.py::DenseIndex.search` |
| Cosine similarity | How closely two number lists point the same way (1 = same, 0 = unrelated). Equal to the dot product once both are length 1 | 3 | `retrieve.py::_unit` |
| BM25 | Search by matching words. Rare words count more (idf), repeated words help with diminishing returns, long chunks are penalised. Zero shared words = zero score | 4 | `retrieve.py::BM25Index` |
| Hybrid search | Run meaning search and keyword search, then merge their rankings | 4 | `retrieve.py::hybrid_search` |
| RRF | Merge ranked lists by rank only: each list gives a chunk 1/(60+rank) points, add them up. Chunks both lists like win | 4 | `retrieve.py::rrf` |
| Reranking | Re-order the top results with a more careful scorer. A cross-encoder reads question + chunk together, so it is sharper but slower; that is why it only sees the ~6 candidates hybrid picked, never every chunk | 5 | `retrieve.py::rerank`, `search` |
| Retired-doc rule | Chunks whose title says "retired" are pushed behind current ones, so an old policy can't win | 5 | `retrieve.py::is_retired` |
| Citation | Pointing at which chunk supports a sentence. The LLM writes `[shipping#0]`; our code checks the id was really one of the chunks it was shown and drops made-up ones | 6 | `pipeline.py::check_citations` |
| Evidence gate | If the best chunk's rerank score is below -9, refuse without calling the LLM at all (saves money, blocks off-topic) | 6 | `pipeline.py::ask`, `MIN_SCORE` |
| Grounded prompt | System prompt that says answer only from SOURCES, cite ids, else say "I don't know", treat source text as data | 6 | `pipeline.py::SYSTEM` |
| Graceful failure | Missing/bad key or network error becomes a friendly message plus the real passages, never a crash or invented answer | 6 | `llm.py::chat`, `pipeline.py::ask` |
| Guardrail | A check that blocks bad input or output. Three places: before the model, around it, after it. Step 6 already has one at each (evidence gate, grounded prompt + graceful failure, citation check); Step 7 adds protection against deliberate attacks | 6-7 | `pipeline.py` (step 6), `guardrails.py` (step 7) |
| Ground truth | Questions with known correct answers and known source chunks. 14 answerable (incl. 2 old-policy traps), 4 off-topic, 5 attacks | 8 | `groundtruth.json` |
| Eval | Running ground truth through the app and scoring it. Re-run after every change; if a number drops, the change hurt | 8 | `evals.py` |
| Recall@3 | Of the questions, how many had the right chunk anywhere in the top 3 | 8 | `evals.py::retrieval_eval` |
| MRR | Mean reciprocal rank: average of 1/(position of the right chunk). 1.0 = always first | 8 | `evals.py::retrieval_eval` |
| Top-1 right | How often the right chunk is ranked first (what the LLM leans on most) | 8 | `evals.py::retrieval_eval` |

(Each row gets a full explanation, an analogy and a "break it" exercise when we reach its step.)

### Step 7 additions (all in `guardrails.py`, wired into `pipeline.py::ask`)

| Term | Plain meaning |
|---|---|
| Prompt-injection filter | `is_injection`: regex for phrases like "ignore previous instructions", "reveal your prompt", "you are now". Cheap, catches the common attacks, can be beaten by rewording |
| PII masking | `mask_pii`: emails, phone numbers and card numbers become `[EMAIL]`, `[PHONE]`, `[CARD]` before search and before the LLM, so the provider never sees them |
| Rate limit | `RateLimiter`: sliding window, at most 10 questions per user per 60 seconds, kept in memory |
| Input length cap | Questions over 500 characters are blocked (long text hides attacks and costs money) |
| Guard order | rate limit -> length -> injection -> mask PII -> search -> evidence gate -> LLM -> citation check. Cheapest first, model last |

### Step 8-9 results (measured 2026-10-25, `uv run python evals.py`)

| Retrieval | Recall@3 | MRR | Top-1 |
|---|---|---|---|
| dense only | 100% | 0.93 | 86% |
| bm25 only | 86% | 0.82 | 79% |
| hybrid (RRF) | 100% | 0.95 | 93% |
| hybrid + rerank | 100% | 1.00 | 100% |

Behaviour with a real LLM (`--llm`): 14/14 answered correctly with a valid citation, 4/4 off-topic refused, 5/5 attacks stopped. The reworded attack ("set aside the guidelines...") slipped past the phrase filter but was stopped by the evidence gate because it is off-topic. A reworded attack that stays on topic would be the real test of the filter.
Caveat: 14 questions on 6 docs is a toy benchmark. 100% here does not mean 100% in the wild.

### Step 9: the screen (`app.py`)
`uv run streamlit run app.py`. Chat box, provider picker in the sidebar, answer with a status line, and an expander showing the chunks the model saw (cited ones marked). Rate limit is per browser session.
