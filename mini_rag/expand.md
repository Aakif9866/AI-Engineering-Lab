# expand.md: scaling mini_rag to hundreds of big files, fast retrieval, hard deadlines

Labels: **[Confirmed]** = true in today's code. **[Estimate]** = back-of-envelope, measure before trusting. Nothing here is built; it is a design.

## 0. The one-paragraph answer
The pipeline shape stays the same: **guards → hybrid retrieve → rerank → gate → LLM → verify**. What changes is where each piece runs. Indexing moves out of the request path into an incremental background pipeline. The brute-force Python/numpy search is replaced by real indexes (ANN for meaning, an inverted index for keywords). Models become services with caching and batching. State (rate limits, caches) moves out of process memory. Chunking becomes structure-aware, because "files of thousands of lines" means code/long docs, not 3-paragraph policies. `search(query, k)` and `ask()` keep their signatures, so callers don't change.

## 1. Define the target (numbers first)
Constraints given: hundreds of files, thousands of lines each, critical deadlines, fast retrieval.

| Scenario | Files × lines × chars/line | Raw text | Chunks (~500 chars, 15% overlap) | Embedding storage (384-d float32 = 1,536 B each) |
|---|---|---|---|---|
| Today | 6 docs | ~2 KB | 7 [Confirmed] | 10 KB (shape (7, 384) [Confirmed]) |
| **Target A** | 300 × 3,000 × 40 | ~36 MB | ~85k | ~130 MB |
| **Target B** (stretch) | 1,000 × 5,000 × 50 | ~250 MB | ~575k | ~880 MB |
| Beyond | 100k+ files | GBs | 10M+ | needs sharding |

"Critical deadlines" has two readings, and the design covers both:
1. **Runtime deadlines**: every question has a latency budget (Section 5).
2. **Delivery deadlines**: you have to ship in days/weeks, so Section 9 orders the work by return on effort.

## 2. What breaks first in the current code
Ranked by when it hurts, with evidence from the code.

| # | Where | Today | Why it breaks | Scale at which it hurts [Estimate] |
|---|---|---|---|---|
| 1 | `BM25Index.search` (`retrieve.py:65-75`) | Python loop over every chunk, every query word | O(chunks × words) in pure Python; no inverted index | ~20-50k chunks: 100 ms+ per query |
| 2 | `ingest.chunk_text` | Splits on blank lines, packs to 400 chars; a paragraph longer than 400 is **never split** [Confirmed] | Code and long prose have huge "paragraphs" or blank lines inside functions: chunks become giant or cut mid-function; no overlap | Immediately on real files |
| 3 | `DenseIndex.__init__` cache key (`retrieve.py:34`) | sha1 of **all** chunk text | Edit one line in one file → whole corpus re-embedded; also ignores model name [Confirmed] | When ingestion takes minutes |
| 4 | `_indexes()` `lru_cache` + Streamlit | Index built lazily in the first request, one process | Cold start blocks the first user; N workers = N copies in RAM | Cold start grows with corpus |
| 5 | `DenseIndex.search` brute force | `vecs @ q` over all rows | Fine to ~100k rows, slow past ~500k | ~100-500k chunks |
| 6 | `rerank` on CPU, `pool=6` | Cross-encoder per candidate | Pool of 6 hides retrieval weakness; at scale you need a pool of 30-100, so rerank latency grows | pool × ms/pair |
| 7 | `RateLimiter`, `limiter` in `pipeline.py` | In-memory dict | Not shared across workers; never evicts users [Confirmed] | Any multi-process deploy |
| 8 | `llm.chat` | One call, 30 s timeout, no retry, no streaming | Provider hiccup = failed question; user waits for the whole answer | Under load or deadline pressure |
| 9 | `is_retired` | String "retired" in title | No real metadata (version, date, owner) | Any real doc set |
| 10 | `MIN_SCORE=-9.0` | Tuned on ~10 probes | Reranker score scale depends on model + corpus | Whenever either changes |
| 11 | `evals.py`, `groundtruth.json` | 23 questions | Cannot detect regressions on 85k chunks | Immediately |

**Key insight:** at Target A (~85k chunks) brute-force numpy search is still fine (about 33M multiply-adds per query [Estimate]). The first real bottlenecks are the Python BM25 loop, chunking quality, full re-embedding, and reranker latency, not the vector search. Don't buy a vector database before measuring.

## 3. Target architecture

```
                        ┌────────────────────── INGESTION (offline, incremental) ──────────────────────┐
 Sources (git repo,     │ 1 Connector/crawler → 2 Change detector (content hash, path, commit)           │
 doc store, wiki)  ───► │ 3 Parser+chunker (per file type) → 4 Queue ─► 5 Embed workers (batched, GPU?)   │
                        │ 6 Upserts: metadata DB + vector index + keyword index  → 7 Index version swap   │
                        └──────────────────────────────────────────────────────────────────────────────┘
                                                              │ (alias swap = blue/green)
                                                              ▼
 User ─► API gateway ─► Auth + rate limit (shared Redis) ─► Query service (stateless, N replicas)
              │                                              │
              │      ┌───────────────────────────────────────┤
              │      ▼                         ▼                           ▼
              │  Query embed (cached)   Vector index (ANN/HNSW)    Keyword index (inverted/BM25)
              │      │   filters: tenant, ACL, project, status/version, freshness (applied INSIDE search)
              │      └──────────────► RRF merge (top 50-100) ──► Rerank service (batched, int8/GPU)
              │                                                      │ top 5-10 + parent context
              │                                  evidence gate ◄─────┘
              │                                       ▼
              │                      LLM gateway (provider fallback, retries, breaker, streaming)
              │                                       ▼
              └──────────────◄────── citation check ◄─┘          Observability: traces, metrics, logs
                                                                  Eval harness: offline in CI + online feedback
```

### Mapping today → scaled
| Today | Scaled replacement | Interface that stays |
|---|---|---|
| `ingest.load_chunks` | Ingestion pipeline (steps 1-7) | `Chunk` record (+ metadata fields) |
| `DenseIndex` | HNSW index in FAISS/hnswlib/pgvector/Qdrant | `search(query, k, filters)` |
| `BM25Index` | SQLite FTS5 / Postgres FTS / OpenSearch / Tantivy | `search(query, k, filters)` |
| `rrf`, `hybrid_search` | unchanged (pure function) | same |
| `rerank` | Reranker service with batching | same |
| `pipeline.ask` | Query service endpoint `POST /ask` | `Answer` (+ stream) |
| `RateLimiter` | Redis sliding window / token bucket | `allow(user)` |
| `llm.chat` | LLM gateway | `chat(messages, provider)` |
| `app.py` | Thin web client (or Streamlit calling the API) | n/a |

## 4. Ingestion for big files (where most of the quality is won)

**4.1 Structure-aware chunking** (replaces `chunk_text`)
| File type | Split on | Why |
|---|---|---|
| Code | functions/classes via tree-sitter; keep signature + docstring + path | A function is the natural unit; blank-line splitting cuts functions |
| Markdown/docs | headings, then paragraphs | Keep the heading path ("Billing > Refunds") |
| Config/JSON/YAML | top-level keys/blocks | |
| Anything oversized | sentence/line window with ~10-15% overlap | Fixes the "straddling" problem we skipped (no overlap today) |

**Parent–child retrieval:** embed small child chunks (precise match), but give the LLM the parent section (more context). Fixes "found the line but lost the surrounding rule."

**Contextual prefix:** generalise today's title prefix (`load_chunks` puts the title on each chunk): prefix `repo/path > Class > function` and file purpose.

**4.2 Metadata on every chunk** (replaces `is_retired` string hack): `doc_id, path, language, section_path, version, status (current/retired), updated_at, owner, tenant, acl_groups, content_hash`. Filtering and freshness become fields, not text tricks.

**4.3 Incremental indexing**
- Hash each file (and each chunk). Unchanged chunk → reuse its stored embedding. Only changed chunks are re-embedded. Fixes today's whole-corpus cache key.
- Deleted file → tombstone its chunks. Renamed file → same content hash, update path.
- **Idempotent upserts** keyed by `chunk_id = hash(doc_id, section, content_hash)`; safe to retry.
- Include `embedding_model_version` in the key so a model change invalidates correctly.

**4.4 Embedding throughput** [Estimate: bge-small on CPU ≈ 100-300 chunks/s per machine]
- Target A first full load: ~85k chunks → roughly 5-15 minutes on one CPU box. Target B: roughly 30-100 minutes → parallel workers or a GPU.
- Batch (e.g. 64-256 chunks), run workers off a queue, use backpressure, retry failed batches, dead-letter poison files.

**4.5 Zero-downtime reindex (critical for deadlines)**: build a new index version in the background, run the evals on it, then flip an alias (`current → v42`). Rollback = flip back.

**4.6 Freshness:** webhook or git-commit trigger per changed file; a nightly full reconcile catches missed events. Expose `index_age` in metrics.

## 5. Fast retrieval: latency budget and techniques

### Budget for a streamed answer, p95 target ~2 s to first token [Estimate, set your own SLO]
| Stage | Today | Target | How |
|---|---|---|---|
| Guards (rate limit, length, injection, PII) | <5 ms | <10 ms | keep regexes; Redis call ~1 ms |
| Query embedding | ~10-30 ms | <30 ms | small model, ONNX, cache repeated queries |
| Vector search | brute force | 5-20 ms | HNSW ANN, metadata pre-filter |
| Keyword search | Python loop | 5-20 ms | real inverted index |
| (above two run **in parallel**) | sequential | max(), not sum | `asyncio`/threads |
| RRF merge | ~1 ms | ~1 ms | unchanged |
| Rerank (pool 50) | few ms (pool 6) | 50-200 ms | int8 ONNX, batching, GPU (~10-30 ms), or a smaller pool |
| Gate + prompt assembly | ~1 ms | ~1 ms | |
| LLM | 1 s+ blocking | first token 300-800 ms | **stream** tokens; stricter `max_tokens`; shorter context |
| Citation check | ~1 ms | ~1 ms | run on the final text |

Retrieval (everything before the LLM) target: **< 150-300 ms p95**.

### Techniques, in order of payoff
1. **Real indexes.** Inverted index for BM25; HNSW for vectors (typical recall 95-99% vs brute force at a fraction of the time; tune `ef_search`). Evaluate recall against brute force on your own data.
2. **Filters inside the search**, not after: `tenant`, ACL groups, `status=current`, project. Cuts the search space and prevents leaks.
3. **Two-stage retrieval with a bigger pool:** retrieve 50-100, rerank down to 5-10. Pool size is the main speed/quality dial. (Today's pool of 6 out of 7 chunks means the reranker sees nearly everything, which will not hold at scale.)
4. **Parallelise** dense and keyword searches; **cache** query embeddings and, carefully, final answers for hot questions (cache key must include the user's ACL scope and index version).
5. **Cheaper reranking:** distilled or int8 model, GPU, or a score cutoff that skips reranking when the fused top result is already decisive.
6. **Stream the answer** so the user sees text while the LLM finishes; perceived latency drops a lot even if total time doesn't.
7. **Shard** only when one index no longer fits RAM or QPS: by tenant/project first (natural), by hash second.
8. **Memory math:** 575k × 1,536 B ≈ 880 MB for raw float32; quantisation (int8/PQ) cuts it 4-32× with a small recall cost; HNSW graph adds ~tens of bytes per link.

### When to choose what
| Need | Options | Pick when |
|---|---|---|
| Vector index | **hnswlib/FAISS** (embedded) · **pgvector** · **Qdrant/Milvus/Weaviate** · managed (Pinecone etc.) | Embedded: single service, ≤~1M vectors, least ops. pgvector: you already run Postgres and want metadata + vectors in one place. Dedicated DB: >1M vectors, heavy filtering, many writers, HA needs. Managed: you want zero ops and accept cost/lock-in |
| Keyword search | **SQLite FTS5** · **Postgres FTS** · **OpenSearch/Elasticsearch** · **Tantivy/Lucene** | FTS5/Postgres for tens of thousands to a few million chunks with minimal ops; OpenSearch when you need distributed search or its hybrid features |
| Embeddings | bge-small (today) → bge-base/large, or an API embedder | Move up only if evals show a recall gain worth the 2-5× cost. Any change = new `embedding_model_version` + full reindex via the alias swap |
| Reranker | MiniLM (today) → larger cross-encoder, hosted rerank API | When top-1 accuracy on your own eval set is the limit, not latency |

## 6. Quality at scale
- **Evals grow with the corpus:** ~300-1,000 questions, tagged by file type and difficulty (exact term, paraphrase, multi-chunk, "no answer", stale-vs-current, attack). Report Recall@k/MRR per slice. Gate deploys on thresholds in CI (today the evals run by hand).
- **Hold-out set:** don't tune `MIN_SCORE`, pool size, or prompts on the same questions you report.
- **Re-calibrate the evidence gate** after any model/corpus change, using score histograms of answerable vs unanswerable questions; consider per-collection thresholds. Today's gate already showed false refusals on wording changes.
- **Query rewriting** (expand abbreviations, resolve follow-ups), **multi-query** retrieval, and **multi-hop** (retrieve → read → retrieve again) for questions that span files.
- **Citation quality:** add a support check (does the cited chunk actually entail the claim?) with a small judge model, sampled in production.
- **Online signals:** thumbs, "no answer" rate, refusal rate, click-through on sources, latency percentiles; feed misses back into the eval set.

## 7. Reliability and failure design
| Failure | Detection | Handling | User impact |
|---|---|---|---|
| LLM provider slow/down | timeout, error rate | Retry once with jitter → **fall back to the other provider** (already two in `config.PROVIDERS`) → circuit breaker → degraded mode | Slightly slower, or passages-only answer (this mode exists: `status="no_llm"`) |
| Vector/keyword index node down | health checks | Replica failover; if one retriever fails, serve the other (RRF handles a single list) | Lower recall, still answers |
| Reranker down/slow | latency SLO | Skip rerank, use RRF order with a stricter gate | Slightly lower precision |
| Ingestion backlog | queue depth, `index_age` | Alert; serve the last good index version | Stale answers, visible freshness stamp |
| Bad index build | evals fail on the new version | Alias never flips | None |
| Traffic spike | QPS, queue time | Shared rate limits, request queue with a bound, shed load (429), cache hot queries | Some 429s instead of an outage |
| Poison document | ingestion errors | Dead-letter queue, skip file, alert | One file missing |

Principles: every external call has a **time budget** (not just a timeout) that is passed down; stateless query replicas; idempotent writes; **graceful degradation** is a feature (we already have `no_llm` and the evidence gate).

## 8. Security at scale
- **Authentication** (SSO/OIDC) and **authorization at retrieval time:** attach `acl_groups` to chunks and filter *inside* the index query. Never retrieve then hide; never rely on the LLM to withhold content.
- **Tenant isolation:** separate collections or mandatory `tenant` filter enforced server-side.
- **Indirect prompt injection:** once many people author documents, retrieved text is untrusted input. Keep the "sources are data" prompt, strip or flag instruction-like text at ingest, never give the LLM tools with side effects based on retrieved text.
- **PII/secrets in code files:** scan at ingest (keys, tokens) and exclude or redact before embedding or sending to a provider; keep today's question-side PII masking.
- **Rate limits and spend caps** per user and per tenant, in Redis; hard provider-side budget caps.
- **Audit log:** who asked what, which chunks were returned, which version of the index.

## 9. Delivering under deadlines: what to do first
Order by return on effort. Each tier assumes the previous one is done. (Durations are rough and depend on team size and how familiar the tools are.)

**Tier 1: days. Keep the codebase, swap the slow parts**
1. Profile one real query end to end (time each stage). Don't guess.
2. Replace `BM25Index` with SQLite FTS5 (or Tantivy). Same `search(query, k)`.
3. Replace brute force only if profiling says so: `hnswlib` or FAISS behind `DenseIndex`.
4. Content-hash incremental embeddings; include model name in the key.
5. Structure-aware chunker for your file types + overlap + path prefix.
6. Pool 30-50 for rerank; time it; cap the pool by your latency budget.
7. Bigger eval set from real questions; run it before and after each change.

**Tier 2: 1-3 weeks. Make it a service**
8. Split into API + background ingestion worker; Streamlit becomes a client.
9. Metadata (status, version, ACL) and filters inside searches; remove `is_retired`.
10. Redis for rate limits and query/embedding caches.
11. LLM gateway: retries, provider fallback, streaming.
12. Structured logs + latency/refusal/error metrics; dashboards and alerts.
13. Alias-swap reindexing with eval gating in CI.

**Tier 3: a quarter. Make it durable**
14. Auth/SSO and per-tenant isolation; audit logs.
15. Autoscaled query replicas; dedicated vector DB if profiling shows the embedded index is the limit; GPU or hosted reranker.
16. Query rewriting, multi-hop, citation-support judge, feedback loop into evals.

**Buy vs build under a deadline:** a managed vector/search service or hosted reranker saves weeks at the cost of money and lock-in. Hand-built pieces were right for learning; for a hard deadline, take the managed option for undifferentiated parts (vector store, queue) and spend your time on chunking, metadata, and evals, which decide answer quality.

## 10. Capacity and cost model (fill in with measured numbers)
- Embedding storage ≈ `chunks × dims × 4 B` (×0.25 with int8). Index RAM ≈ vectors + graph overhead (measure it).
- Ingest time ≈ `chunks ÷ (chunks/s per worker × workers)`.
- LLM cost per question ≈ `(system + 5-10 chunks × ~150 tokens + question) × input price + answer tokens × output price`. Today: 3 chunks of ≤409 chars, one call [Confirmed], cost not measured.
- Levers: fewer/shorter chunks to the LLM, answer cache, refuse early (the gate already avoids calls for off-topic questions), cheaper model for easy questions, prompt caching of the fixed system prompt.
- QPS planning: `peak QPS × p95 latency` ≈ concurrent requests per replica group; load-test to find the knee, don't assume.

## 11. How to validate each step (measure, don't assume)
| Change | Measure before/after |
|---|---|
| Real BM25 / ANN | p50/p95 retrieval ms; Recall@k vs old results (ANN vs brute force overlap) |
| New chunker | Recall@k and MRR on slices by file type; average chunk length distribution |
| Larger rerank pool | Top-1 accuracy vs added ms |
| Incremental embeddings | Time to reindex after changing one file |
| Streaming | Time to first token |
| Gate re-tune | False-refusal rate and false-answer rate on the answerable/unanswerable sets |
| Fallback provider | Failure injection test: kill the primary, confirm answers continue |

## 12. How to say it in an interview
"The pipeline already has the right shape, so scaling is mostly swapping implementations behind stable interfaces. For hundreds of large files I'd first profile, because at around 85k chunks the numpy search is still fine and my hand-written BM25 loop is the real bottleneck. Then I'd fix chunking for code and long docs, move to incremental indexing keyed by content hash, put filters like ACL and document status inside the index query, retrieve a pool of 50 to 100 and rerank to a handful, stream the answer, and put rate limits and caches in Redis. Under a tight deadline I'd do the cheap swaps first, expand the eval set so every change is measured, and use managed services for the parts that aren't differentiating. I'd keep the graceful degradation I already have: if the LLM fails, still return the passages."
