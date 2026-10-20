# Notes: LLM caching, explained simply

## The one idea

Model calls are slow (seconds) and cost money per token. If 60% of questions repeat, answering each one from scratch wastes most of your bill. A cache remembers answers and serves them again in milliseconds.

> A cache is a librarian's notebook: "someone asked this yesterday, here's what we told them."
> The danger: handing out yesterday's answer when the question was *slightly* different, the facts changed, or the answer was about someone else's account.

**A cache hit is not a correct answer.** It's only a reused one. This lab measures both.

## Three kinds of caching (the PDF's layers)

| Layer | Matches when… | Risk | Hit rate |
|---|---|---|---|
| **Exact** | Same question text, after lowercasing and trimming | None: the same input gets the same output | Low for chat; high for automated pipelines |
| **Semantic** | Question *meaning* is similar enough (embedding similarity ≥ threshold) | Serving the answer to a *different* question | High |
| **Prefix / KV** | The start of the prompt is identical (system prompt, documents) | None; done by the provider | Saves tokens on every call |

Use all three: exact first (free and safe), semantic second, with the provider's prefix cache underneath anything that still reaches the model.

## The cache key: everything that changes the answer

If any of these differ, the cached answer may be wrong, so all of them go into the key:

- the question (normalised)
- the provider and model (a different model gives a different answer)
- the **prompt version** (you changed the instructions)
- the temperature
- the system prompt (hashed)
- the namespace (a different tenant or product)
- **the user, for personal questions**

The classic trap the PDF warns about: "What's my balance?" cached once and then served to *everyone*. The workload proves it. Turn user scoping off and wrong answers jump from 5 to 14.

## Invalidation: the actually hard part

When the Pro price changes from $8 to $10, every cached answer that said "$8" is now a lie.

- **TTL (time to live)** alone: answers expire after N minutes. Simple, but you serve stale answers until then, and throw away good ones needlessly.
- **Version-hash dependencies** (what we do): each cached answer remembers *which articles, at which version,* it was built from. Before serving, check those versions. If an article changed, evict and re-ask.
  - *Eager:* on edit, delete dependent entries immediately.
  - *Lazy:* check at lookup time. We do both.

Turn dependency checking off in the workload, and the cache keeps serving "$8" after the price change.

## The threshold problem, with real numbers

Semantic caching needs a similarity cut-off. With the MiniLM embedder:

| Pair type | Typical similarity | Highest seen |
|---|---|---|
| True paraphrases (same answer) | 0.59 | 0.854 |
| **Look-alikes (different answer!)** | 0.67 | **0.986** |
| Unrelated questions | 0.08 | 0.669 |

Look-alikes are often *more* similar than true paraphrases. "Can I get a refund within 30 days?" and "…after 30 days?" differ by one word, so to the embedding they're almost the same sentence. **No single threshold separates them.** Set it high enough to block the look-alikes and you lose almost every paraphrase hit.

What production systems do about this:
- Keep known look-alike questions out of semantic matching (exact match only for them).
- Use a stricter threshold per topic.
- Add a cheap verification step (a small classifier or a re-ranker) before serving a semantic hit.
- **Monitor the false-hit rate**, not just the hit rate.

## What the "events" mean

| Event | Meaning |
|---|---|
| `hit_exact` | Same normalised question and key: served from cache |
| `hit_semantic` | Similar enough: served from cache |
| `miss` | Nothing close: called the model and stored the result |
| `rejected_match` | Something close but just under the threshold. Worth logging: these are your tuning data |
| `bypass` | A volatile question: never cached |
| `upstream_error` | The model call failed. Errors are never cached |

## Glossary

| Term | Meaning |
|---|---|
| Hit rate | Share of requests served from cache |
| False hit | A cache hit that gave the wrong answer |
| TTL | How long an entry may live |
| Namespace | A separate cache area per tenant or product |
| Write-through | Store every fresh answer in the cache as it is produced |
| Prefix caching | The provider reuses computation for an identical prompt start |

## Interview question (from the PDF)

> *An FAQ bot handles 100k queries a day; 60% are variations of 500 questions. Costs are unsustainable.*

1. Exact cache (normalised) first, then a semantic cache with a threshold tuned on labelled duplicate and non-duplicate pairs.
2. Key on model, prompt version, temperature and tenant; never share personal or time-sensitive answers.
3. Invalidate by content-version hash of the FAQ articles, plus a TTL tied to the update cadence.
4. Warm the cache with the top 500 questions.
5. Back-of-envelope: with a 60% hit rate, about 60% of model spend disappears and median latency drops from seconds to milliseconds.
6. Monitor hit rate **and** false-hit rate; a sudden hit-rate drop signals that user questions have shifted.
