# Notes: fine-tuning, explained simply

## The one idea

Prompting is *telling* the model what to do, every single time. Fine-tuning is *training* it, so the behaviour lives in the weights and the instructions can shrink.

> Prompting = handing a new employee a long instruction sheet with every task.
> Fine-tuning = training the employee once, so a one-line request is enough.

Training costs real effort: data, compute, evaluation, and another model file to version. So the PDF's first rule is: **try prompting (and RAG) first, measure the gap, and only then fine-tune.**

## Full fine-tuning vs LoRA

A model is billions (here, 135 million) of numbers called *weights*.

- **Full fine-tuning** changes every weight. That's powerful, but it needs lots of memory, risks the model forgetting what it knew, and leaves you a whole new model to store.
- **LoRA (Low-Rank Adaptation)** freezes every original weight and adds small "adapter" matrices beside some layers. Only the adapters learn.

```
original layer:   output = W · x                (W frozen, never changes)
with LoRA:        output = W · x + B · A · x    (A and B are small and trainable)
```

`B` starts at zero, so before training the model behaves exactly like the original. In our run:
- 1.84 million trainable numbers versus 134.5 million frozen (1.35%)
- the adapter file is 7 MB; the base model is 270 MB
- one base model can serve many adapters, one per task or customer

**QLoRA** also compresses the frozen base to 4 bits to save memory. It isn't used here because its library doesn't support Apple Silicon.

## Data matters more than amount

The PDF: *a few hundred high-quality examples beat tens of thousands of noisy ones.* Our pipeline:

1. **Generate** examples from templates, with typos, slang and rambling.
2. **Validate** every label against the schema. Reject values like `"P5"` or a missing field.
3. **Business rules** the schema can't express: "the payments team owns billing", "P0 can't be low impact".
4. **Remove duplicates,** both exact copies and near-copies (overlapping 5-character chunks, Jaccard ≥ 0.85).
5. **Split by content hash,** *after* deduplication. If near-copies landed in both train and test, the test would be an open-book exam.

We injected 44 broken records on purpose; the cleaner caught all 44.

## The training loop, in plain words

For each batch of examples:
1. Feed in `prompt + correct JSON`.
2. Compute the **loss** only on the JSON tokens. Prompt tokens are masked with `-100`, because we want the model to learn to *write the answer*, not to repeat the question.
3. Nudge the LoRA weights (AdamW optimiser) to make the correct tokens more likely.
4. Every epoch, check the loss on validation examples the model never trains on.

## Three lessons this lab produced

**1. Low loss can hide wrong answers.** Validation loss fell from 2.91 to 0.19, which looks excellent. But loss is averaged over *every* token, and most tokens are easy: `{"`, field names, commas, a copied summary. The hard tokens, choosing `"auth"` versus `"billing"`, are a small share. The model produced perfect JSON and invented values like `"component": "pay_per_base"`. **Always score each field separately.**

**2. Constrained decoding is a different lever.** Instead of letting the model write freely, we fix the JSON skeleton and, for each field, ask: *which allowed value do you find most likely?* That guarantees valid output (PDF 4b, "constrained decoding").
- On the **base** model it fixed the format, but the values were still mostly wrong (0% exact). Format is not knowledge.
- On the **adapter**, component accuracy on realistic requests rose from 25% to 55%. Training gave the preference; decoding removed the invalid options.

**3. Tokenisation must match training exactly.** Our first constrained decoder always chose `"performance"`. The cause: in training, the model always saw a closing quote and comma merged into one token (`",`). We were scoring a lone closing quote, which the model had never seen there, and the penalty landed hardest on multi-token values. The fix was to score each value with its trailing comma, exactly as in training.

**4. More training can cost general ability.** Run v2 (6 epochs instead of 3) jumped to 98% component accuracy on test, but its answers to simple general questions fell from 6/12 to 2/12. That's catastrophic forgetting, even with LoRA, and exactly why the general slice exists.

## Reading the results table

- **Valid JSON / schema-valid:** can downstream code even parse it?
- **All fields exact:** strict and harsh; one wrong field is a fail.
- **Per-field accuracy:** where the model is weak (priority and impact are the hardest).
- **OOD slice:** 20 hand-written requests unlike the templates. A system that wins only on synthetic data has learned the templates, not the task. The rules baseline drops from 88% to 40% here.
- **General questions:** "capital of France?" and similar, asked before and after training, to catch **catastrophic forgetting**.
- **Prompt tokens:** the fine-tuned prompt is 5× shorter, which saves cost on every call.

## When should you fine-tune? (the honest answer from this lab)

| Situation | Prefer |
|---|---|
| A big API model already does it well and volume is low | Prompting (DeepSeek: 45% exact on OOD vs 0% for our small adapter) |
| You need guaranteed valid structure | Constrained decoding / JSON mode (cheap, immediate) |
| High volume, cost or latency matters, or data can't leave your machine | Fine-tune a small model, with *enough* good data and a held-out evaluation gate |
| You want tone, safety or preference behaviour | Preference tuning (DPO), a different lever from task SFT |

## Glossary

| Term | Meaning |
|---|---|
| SFT | Supervised fine-tuning: learn from (input, correct output) pairs |
| Epoch | One pass over the training set |
| Learning rate | How big each weight nudge is |
| Rank (r) | Size of the LoRA matrices: bigger means more capacity, more parameters |
| Adapter | The small trained add-on weights LoRA produces |
| Catastrophic forgetting | Losing general abilities while learning a narrow task |
| DPO | Training on "answer A is better than B" pairs, with no separate reward model |

## Interview question (from the PDF)

> *Answers are correct but verbose and inconsistent; prompt engineering helped but not enough.*

1. First, measure: what fraction is unparseable, and which fields are wrong?
2. Cheap fixes: JSON mode, a schema plus a validate-and-retry loop, or constrained decoding.
3. If that's still not enough: LoRA SFT on a few hundred to a few thousand *curated* (input, ideal output) pairs. Deduplicate, split by content, and keep a held-out set.
4. Gate the adapter on held-out format adherence **and** content accuracy (fixing the format can quietly hurt content), plus a general-capability check.
5. Version the adapter, A/B it against the current version, and keep a rollback path.
