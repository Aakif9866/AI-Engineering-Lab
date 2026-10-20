"""Base model, prompts, generation, LoRA and the training loop.

Base model: HuggingFaceTB/SmolLM2-135M-Instruct (Apache-2.0, ~270 MB). Chosen for an 8 GB M1:
fp32 LoRA training fits in memory and a run finishes in minutes. QLoRA is not used because
bitsandbytes 4-bit kernels are not available on Apple Silicon.

The training loop is written out (no Trainer/TRL) so every step is visible: prompt tokens are
masked with -100, so loss is computed only on the JSON the model must learn to emit.
"""
import json
import time

import torch

BASE_MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj"]

# Baseline prompt: everything the model needs to know must be spelled out every time.
BASELINE_SYSTEM = """Convert the product change request into a JSON object with exactly these keys:
change_type: one of feature_request, bug_fix, removal, pricing_change, ux_change, performance
component: one of billing, checkout, search, onboarding, notifications, reporting, auth, mobile_app
priority: one of P0 (outage), P1 (this sprint), P2 (this quarter), P3 (someday)
customer_impact: one of low, medium, high
requires_migration: true if stored data or database schema must change, else false
owner_team: payments for billing/checkout, growth for onboarding/notifications, platform for search/auth, mobile for mobile_app, data for reporting
summary: one line under 120 characters
Example output: {"change_type": "bug_fix", "component": "search", "priority": "P1", "customer_impact": "medium", "requires_migration": false, "owner_team": "platform", "summary": "Fix search filters: wrong totals"}
Output only the JSON object."""
# Fine-tuned prompt: the contract lives in the weights, so the instruction is one line.
FT_SYSTEM = "Convert the product change request into a decision JSON."


def device() -> str:
    """CPU by default: on the 8 GB M1 this lab was built on, MPS gave no speedup for a 135M model
    (1.48 vs 1.59 s/step at batch 8) but its allocator growth pushed the system into swap and
    stalled training. Set LAB_TORCH_DEVICE=mps (or cuda) on machines with headroom."""
    from lab.core.config import env
    return env("LAB_TORCH_DEVICE", "cpu")


def load_base(dev: str | None = None):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    kw = {}
    try:
        tok = AutoTokenizer.from_pretrained(BASE_MODEL, local_files_only=True)
        kw["local_files_only"] = True
    except Exception:
        tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float32, **kw).to(dev or device())
    return tok, model


def base_revision() -> str | None:
    try:
        from huggingface_hub import scan_cache_dir
        for repo in scan_cache_dir().repos:
            if repo.repo_id == BASE_MODEL:
                return sorted(r.commit_hash for r in repo.revisions)[0]
    except Exception:
        return None
    return None


def prompt_text(tok, request: str, system: str) -> str:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": request}]
    return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)


@torch.no_grad()
def generate(model, tok, prompts: list[str], max_new_tokens: int = 110, batch_size: int = 16) -> list[str]:
    model.eval()
    out = []
    for i in range(0, len(prompts), batch_size):
        enc = tok(prompts[i:i + batch_size], return_tensors="pt", padding=True).to(model.device)
        gen = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=tok.pad_token_id)
        out.extend(tok.batch_decode(gen[:, enc["input_ids"].shape[1]:], skip_special_tokens=True))
    return out


def attach_lora(model, r: int = 16, alpha: int = 32, dropout: float = 0.05, targets=LORA_TARGETS):
    from peft import LoraConfig, get_peft_model
    cfg = LoraConfig(r=r, lora_alpha=alpha, lora_dropout=dropout, target_modules=list(targets), task_type="CAUSAL_LM")
    pm = get_peft_model(model, cfg)
    trainable = sum(p.numel() for p in pm.parameters() if p.requires_grad)
    total = sum(p.numel() for p in pm.parameters())
    adapted = sorted({n.split(".lora_")[0] for n, _ in pm.named_parameters() if ".lora_" in n})
    return pm, {"trainable_params": trainable, "total_params": total, "trainable_pct": round(100 * trainable / total, 4),
                "adapted_modules": len(adapted), "adapted_module_names_sample": adapted[:4], "lora_config": {
                    "r": r, "alpha": alpha, "dropout": dropout, "target_modules": list(targets)}}


def encode_example(tok, request: str, label: dict, max_len: int = 320) -> dict:
    """input_ids = prompt + target + eos; labels = -100 over the prompt so only the target is learned."""
    p_ids = tok(prompt_text(tok, request, FT_SYSTEM), add_special_tokens=False)["input_ids"]
    t_ids = tok(json.dumps(label), add_special_tokens=False)["input_ids"] + [tok.eos_token_id]
    ids = (p_ids + t_ids)[:max_len]
    labels = ([-100] * len(p_ids) + t_ids)[:max_len]
    return {"input_ids": ids, "labels": labels}


def collate(batch: list[dict], pad_id: int) -> dict:
    n = max(len(b["input_ids"]) for b in batch)  # right-pad for training
    ids = torch.full((len(batch), n), pad_id)
    labels = torch.full((len(batch), n), -100)
    mask = torch.zeros((len(batch), n), dtype=torch.long)
    for i, b in enumerate(batch):
        L = len(b["input_ids"])
        ids[i, :L] = torch.tensor(b["input_ids"])
        labels[i, :L] = torch.tensor(b["labels"])
        mask[i, :L] = 1
    return {"input_ids": ids, "labels": labels, "attention_mask": mask}


def train_loop(model, batches: list[dict], *, epochs: int, lr: float, val_batches=None, on_step=None, grad_clip=1.0):
    """Plain AdamW with linear decay over only the parameters that require grad (LoRA A/B)."""
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    total = epochs * len(batches)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: max(0.0, 1 - s / max(1, total)))
    history, step, t0 = [], 0, time.time()
    for ep in range(epochs):
        model.train()
        for b in batches:
            b = {k: v.to(model.device) for k, v in b.items()}
            loss = model(**b).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, grad_clip)
            opt.step()
            sched.step()
            opt.zero_grad()
            step += 1
            history.append({"step": step, "epoch": ep + 1, "loss": round(loss.item(), 4)})
            if on_step:
                on_step(step, total, history, time.time() - t0)
        if val_batches:
            history[-1]["val_loss"] = round(evaluate_loss(model, val_batches), 4)
            if on_step:
                on_step(step, total, history, time.time() - t0)
    return history


@torch.no_grad()
def evaluate_loss(model, batches) -> float:
    model.eval()
    losses = [model(**{k: v.to(model.device) for k, v in b.items()}).loss.item() for b in batches]
    return sum(losses) / len(losses)


def field_spec() -> list[tuple[str, list | None]]:
    """(field, allowed values) in the training label order; None = free text."""
    from typing import get_args
    from .schema import Decision
    spec = []
    for name, f in Decision.model_fields.items():
        if f.annotation is bool:
            spec.append((name, [True, False]))
        elif get_args(f.annotation):
            spec.append((name, list(get_args(f.annotation))))
        else:
            spec.append((name, None))
    return spec


@torch.no_grad()
def constrained_generate(model, tok, prompt: str, max_summary_tokens: int = 40) -> str:
    """Schema-constrained decoding (PDF 4b): the JSON skeleton is fixed, each enum/bool field is the
    allowed value with the highest sequence log-likelihood under the model, and only the summary
    is generated freely. Output is schema-valid by construction; what remains measurable is
    whether the model *prefers* the right values, which is what fine-tuning should improve."""
    model.eval()
    dev = model.device
    # Mirror encode_example(): prompt and JSON target are tokenised separately and concatenated, so
    # no token straddles the prompt/answer boundary in a way training never showed the model.
    prompt_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    enc_json = lambda t: prompt_ids + tok(t, add_special_tokens=False)["input_ids"]  # noqa: E731
    text = "{"
    for i, (name, choices) in enumerate(field_spec()):
        text += ("" if i == 0 else ", ") + f'"{name}":'
        p_ids = enc_json(text)
        if choices is not None:
            # Tokenise prefix+value jointly, exactly as training saw `"field": "value"`, and score from
            # the first token where the sequences diverge from the prefix. Tokenising the value on its
            # own creates boundary tokens the model never saw and badly distorts the likelihoods.
            # Every enum/bool field is followed by another field, so training always saw `"value",`
            # (the quote and comma merge into one token). Scoring a bare closing quote is
            # out-of-distribution and biased the choice toward single-token values; include the comma.
            fulls = [enc_json(text + " " + json.dumps(c) + ",") for c in choices]
            starts = []
            for f in fulls:
                k = 0
                while k < min(len(f), len(p_ids)) and f[k] == p_ids[k]:
                    k += 1
                starts.append(k)
            L = max(len(f) for f in fulls)
            ids = torch.full((len(fulls), L), tok.pad_token_id, dtype=torch.long)
            mask = torch.zeros_like(ids)
            for j, f in enumerate(fulls):
                ids[j, :len(f)] = torch.tensor(f)
                mask[j, :len(f)] = 1
            # Only the logits that score candidate tokens are needed: keep the tail positions
            # instead of projecting every prompt position onto the 49k-token vocabulary.
            first = max(1, min(starts))
            keep = L - first + 1
            logits = model(input_ids=ids.to(dev), attention_mask=mask.to(dev), logits_to_keep=keep).logits
            logp = torch.log_softmax(logits.float(), -1).cpu()
            off = L - keep  # absolute position of logits[:, 0]
            scores = [sum(logp[j, pos - 1 - off, f[pos]].item() for pos in range(starts[j], len(f))) for j, f in enumerate(fulls)]
            text += " " + json.dumps(choices[max(range(len(choices)), key=scores.__getitem__)])
        else:
            text += ' "'
            ids = torch.tensor([enc_json(text)], device=dev)
            out = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids), max_new_tokens=max_summary_tokens,
                                 do_sample=False, pad_token_id=tok.pad_token_id)
            s = tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True).split('"')[0]
            text += s.replace("\\", "")[:120] + '"'
    return text + "}"
