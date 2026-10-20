# 02 · IntentForge: fine-tuning

**In one sentence:** we teach a small open model to turn messy product requests into a strict JSON "decision" by actually changing (a few of) its weights, and we measure honestly whether that beat simpler options.

## The task

Input, as people actually write it:

> "hey team, password reset flow keeps failing - it shows a blank screen. affects every customer. production is down because of this."

Required output, exactly these 7 fields and nothing else:

```json
{"change_type": "bug_fix", "component": "auth", "priority": "P0", "customer_impact": "high",
 "requires_migration": false, "owner_team": "platform", "summary": "Fix password reset flow: blank screen"}
```

This mirrors the PDF's interview case: the content may be right, but the *format* is inconsistent, and downstream code breaks.

## Try it in the web app

Open **http://localhost:5173/intentforge**.

1. **Dataset pipeline:** see how 700 generated examples became 601 clean ones. Records rejected for each reason are listed with examples. All 44 deliberately corrupted records were caught.
2. **Train (LoRA):** press **Start real LoRA training**. A live loss curve appears; it takes about 5 minutes on a laptop CPU. When it finishes, the "What was actually trained" box shows how many weights changed (1.35%) and the proof that the base weights did not.
3. **Baseline vs fine-tuned:** press each system button and compare the columns. Switch the slice selector between *test* (synthetic) and *OOD* (hand-written, realistic). Click **outputs** to see every prediction field by field.

## The systems compared

| System | What it is |
|---|---|
| `rules` | Keyword matching an engineer could write in an afternoon (instant, offline) |
| `base_prompted` | The untrained SmolLM2-135M with a long instruction prompt and an example |
| `adapter:<run>` | The same model plus our trained LoRA adapter and a one-line prompt |
| `base_constrained` | Base model, but each field is *forced* to be one of the allowed values |
| `adapter_constrained:<run>` | Adapter plus forced allowed values |
| `api:deepseek` | A large API model prompted in JSON mode (paid, about a cent) |

## How it works

| File | What it does |
|---|---|
| `schema.py` | The output contract (pydantic), business rules, a strict parser and per-field scoring |
| `data.py` | Generates messy requests, injects bad and duplicate records, cleans them, and splits by content hash |
| `model.py` | Loads the model, builds prompts, attaches LoRA, runs the training loop, and does constrained decoding |
| `train.py` | Runs a training job and writes `status.json` (live progress) and `metadata.json` (proof of what changed) |
| `evaluate.py` | Runs any system on the test, OOD and general-knowledge slices |
| `api.py` | HTTP routes; training and evaluation run as background processes |

Artifacts land in `backend/var/p02/`: the dataset, `runs/<id>/adapter` (7 MB) and `evals/*.json`.

## Commands

```bash
cd backend
.venv/bin/python -m lab.p02_finetune.data --n 700 --seed 7
.venv/bin/python -m lab.p02_finetune.train --epochs 3            # ~5 min on M1 CPU
.venv/bin/python -m lab.p02_finetune.evaluate --system rules
.venv/bin/python -m lab.p02_finetune.evaluate --system adapter:run-v1
.venv/bin/python -m pytest tests/test_p02_finetune.py
```

## Measured results (2026-10-20)

**Run v1:** LoRA r=16 on 120 attention modules. 1,843,200 trainable parameters (1.35%) and 134,515,008 frozen. Validation loss 2.91 → 0.19 in 272 s on CPU. Frozen-weight checksum identical before and after.

| System | Valid JSON | Schema-valid | All fields exact (test / OOD) | Component accuracy (OOD) | Prompt tokens |
|---|---|---|---|---|---|
| rules | 100% | 100% | 88% / 40% | 95% | – |
| base_prompted | 31% | 28% | 0% / 0% | 0% | 285 |
| adapter | **100%** | 44% | 2% / 0% | 25% | **57** |
| base_constrained | 100% | 100% | 0% / 0% | 10% | 285 |
| adapter_constrained | 100% | **100%** | 2% / 0% | **55%** | 57 |
| DeepSeek (prompted) | 97% | 97% | 54% / **45%** | 95% | 306 |

General-knowledge check (forgetting): base 6/12, adapter 5/12. That's a one-question difference on a tiny slice, so treat it as "no clear forgetting", not as proof either way.

**What this says:**
- Fine-tuning taught the *format* (valid JSON every time, a 5× shorter prompt, good summaries) but not the full *mapping* to correct enum values: a 135M model and 3 epochs aren't enough.
- Constrained decoding plus the adapter more than doubled component accuracy on realistic requests (25% → 55%).
- On this task, a large prompted API model still wins on real-world requests. That's the PDF's warning: measure the baseline before you fine-tune.

**Run v2** (6 epochs, lr 3e-4) learned the mapping: 30% exact on test and 10% on OOD, component accuracy 98% on test and 85% on OOD, schema-valid 100%. But general-question accuracy fell from 6/12 to **2/12**: catastrophic forgetting, measured. More training improved the task and hurt everything else. The fix the PDF suggests is to mix general examples into the training data and gate on a general-capability set.

## Limits and next steps

- A tiny model and synthetic training data. The rules baseline and the OOD slice share an author, so the rules' OOD score is likely optimistic.
- QLoRA isn't available on Apple Silicon; training runs in fp32 on CPU.
- **V2:** hard-negative mining (train more on the mistakes), a bigger base model, confidence calibration, routing hard requests to the API model, and DPO from SignalLoop feedback pairs.
