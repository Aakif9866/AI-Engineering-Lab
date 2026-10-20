# 01 · Evidence Atlas: Retrieval-Augmented Generation

**In one sentence:** you ask a question about a pile of company documents, the system finds the few passages that matter, and the answer is built only from those passages, with a citation for every claim.

## The story in the data

A fictional logistics company, Meridian, had a refrigerator (unit R-17) fail at its Reno depot, putting 1,200 vaccine vials at risk. The 15 documents in `backend/data/p01/corpus/` are what an investigator would collect:

- **Policies:** current version 3 and an older, superseded version 2 that says different things
- **A contract:** marked *restricted*, so only investigators may see it
- **An incident report** with a wrong timestamp
- **Two emails that disagree:** the technician says the vendor was late, the vendor says it wasn't
- **Sensor logs and a phone log** that settle the argument
- **A rumour** from a chat channel that is simply false

That mix is deliberate. Real document collections have old versions, conflicts, secrets and noise.

## Try it in the web app

Open **http://localhost:5173/evidence-atlas**.

1. **Ask & inspect** tab: press **Retrieve & answer** on the pre-filled SLA question. You'll see:
   - the answer, with clickable `S1`, `S2`… citation chips that highlight the passage used
   - the retrieved passages, with every score that ranked them (BM25, dense, fused)
   - a verification table checking each answer sentence against its sources
2. Click **Compare strategies**. The same question runs through BM25 (keyword), dense (meaning) and hybrid retrieval side by side.
3. Try the **q21 · unanswerable** chip ("expiry date of the lot"). The offline generator answers wrongly; an LLM refuses. That's a lesson, not a bug (see NOTES.md).
4. Switch **Role** to `staff` and ask about the contract. Restricted documents vanish.
5. **Benchmark** tab: score the current settings on 24 labelled questions.
6. **Experiments** tab: see how chunk size, retrieval strategy and context size change the scores.
7. **Corpus & ingestion** tab: paste a new email, ingest it, and watch only *one* document get re-embedded.

If a DeepSeek key is configured, tick **Generate with LLM** to compare against the offline generator (one call, a fraction of a cent).

## How it works (the pipeline)

```
documents ─► parse metadata ─► chunk ─► index (BM25 + vectors)
question  ─► ACL filter ─► BM25 ranking ─┐
                         ─► vector ranking ┴► fuse (RRF) ─► rerank ─► demote old docs ─► fit context budget
          ─► evidence gate (enough evidence?) ─► generate with [S#] citations ─► verify citations & numbers
```

| File | What it does |
|---|---|
| `index.py` | Reads documents, splits them into chunks, builds the keyword and vector indexes, and re-indexes only changed documents |
| `retrieve.py` | The ranking strategies, the access filter, reranking, the freshness penalty and the context budget |
| `generate.py` | The evidence gate, the LLM and offline generators, and citation and groundedness checking |
| `pipeline.py` | `ask()`, which wires the steps into one traced request |
| `evaluate.py` | The benchmark, retrieval and answer metrics, and the experiment grid |
| `api.py` | HTTP routes used by the web page |

## Commands

```bash
cd backend
.venv/bin/python -m lab.p01_rag.evaluate          # offline experiment grid (~7 s)
.venv/bin/python -m lab.p01_rag.evaluate --llm    # adds the LLM generator comparison (~24 paid calls)
.venv/bin/python -m pytest tests/test_p01_rag.py
```

## Measured results (2026-10-20)

| | Offline extractive | DeepSeek |
|---|---|---|
| Correct on answerable questions | 75% | **100%** |
| Correctly refused unanswerable questions | 50% | **100%** |
| Wrongly refused answerable questions | 5% | 0% |
| Citations pointing at real passages | 100% | 100% |

Retrieval ranking quality (MRR, where 1.0 means the right document is always ranked first): keyword 0.925, meaning (MiniLM) 0.912, hybrid 0.950, **hybrid + rerank 0.975**.

## Limits and next steps

- 15 documents is small, so retrieval is nearly perfect and the generator is the weak link.
- The "is there enough evidence?" threshold was tuned on the same questions it's tested on.
- Groundedness is checked by word and number overlap, not by a model that understands meaning.
- **V2:** "as of date X" questions, automatic detection of conflicting sources, planted misleading documents, a meaning-based (NLI) groundedness check.
