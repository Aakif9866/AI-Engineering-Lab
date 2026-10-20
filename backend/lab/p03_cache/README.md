# 03 · CacheCraft: LLM caching

**In one sentence:** before paying a model to answer a question, check whether we've already answered the same (or a similar) question, and reuse the answer only when that's safe.

## The scenario

The help center of a fictional note-taking app, "Nimbus Notes". 13 FAQ articles: refunds, pricing, storage, passwords, offline mode… Three users: `u1` on Pro, `u2` on Team, `u3` on Free. This is the PDF's interview case: *most traffic is the same few hundred questions in different words.*

Some questions are deliberate traps:
- **Look-alikes:** "refund *within* 30 days" vs "refund *after* 30 days" have opposite answers but nearly identical wording.
- **Personal:** "When does my plan renew?" has a different answer for each user.
- **Live:** "Is Nimbus down right now?" must never come from a cache.
- **Changing data:** the Pro price changes from $8 to $10 partway through the workload.

## Try it in the web app

Open **http://localhost:5173/cachecraft**.

1. **Gateway** tab:
   - Ask *"How much does the Pro plan cost?"*: you'll see a **miss** (the model was called and the answer stored).
   - Ask it again: **hit_exact**.
   - Ask *"What's the price of Nimbus Pro?"*, then lower the threshold until it becomes **hit_semantic**. Watch the similarity marker against the threshold line.
   - Ask the confusable refund pair with a low threshold: you'll get the *wrong* answer from cache. That's the danger.
   - Ask *"When does my plan renew?"* as `u1`, then as `u2`: each gets their own date. Turn off **User-scoped keys** and `u2` gets `u1`'s date (a leak).
   - *"Is Nimbus down right now?"* always shows **bypass**.
2. **Knowledge base** tab: change the Pro price, then ask about it again. The old cached answer is evicted (`dependency_changed`).
3. **Workload comparison** tab: run 240 labelled queries through 9 cache configurations and compare hit rate, *false* hits, latency and cost.
4. **Threshold tuning** tab: precision and recall at every threshold, and why no threshold is perfect.

## How it works

```
question ─► classify: volatile? personal? global?
         ─► exact lookup (key = question + model + prompt version + temperature + namespace [+ user])
         ─► semantic lookup (same key family, similarity ≥ threshold)
         ─► before serving any hit: expired?  source article changed?  → evict instead
         ─► miss: call the model, store the answer + the versions of the articles it used
```

| File | What it does |
|---|---|
| `gateway.py` | Scope detection, cache keys, exact and semantic lookup, TTL, dependency checks, events, and the upstream model (LLM or offline) |
| `workload.py` | The labelled 240-query traffic, the 9-mode comparison and the threshold sweep |
| `api.py` | HTTP routes for the web page |
| `backend/data/p03/kb.json` | Articles, paraphrases, look-alike groups and users |

## Commands

```bash
cd backend
.venv/bin/python -m lab.p03_cache.workload        # ~55 s with MiniLM
.venv/bin/python -m pytest tests/test_p03_cache.py
```

## Measured results (2026-10-20, MiniLM embeddings)

| Mode | Hit rate | Wrong answers served | Median latency* | Spend* |
|---|---|---|---|---|
| no cache | 0% | 0 | 813 ms | $0.00531 |
| exact only | 32% | 0 | 814 ms | $0.00377 |
| semantic, threshold 0.90 | 68% | 5 | 14 ms | $0.00157 |
| semantic, threshold 0.95 | 63% | 3 | 14 ms | $0.00186 |
| 0.90 **without** dependency check | 69% | **14** | 14 ms | $0.00149 |
| 0.90 **without** user scoping | 70% | **14** | 14 ms | $0.00149 |

\* Offline mode simulates an 800 ms model call (clearly labelled as modelled), and spend is estimated from configured prices. With a real provider, both are measured.

During development, real DeepSeek calls served **73% of prompt tokens from the provider's own prefix cache**, the layer underneath this one.

## Limits and next steps

- No threshold reaches zero wrong answers on this data (see NOTES.md for why).
- Personal and live questions are detected with word patterns, not a classifier.
- **V2:** a different threshold per topic, smarter expiry policies, and sending hard questions to a stronger model.
