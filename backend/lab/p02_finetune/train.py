"""Run a real LoRA SFT job and record exactly what changed.

    python -m lab.p02_finetune.train --epochs 3 --lr 2e-4 --r 16

Writes var/p02/runs/<run_id>/{status.json, metadata.json, adapter/}. status.json is polled by the UI.
"""
import argparse
import hashlib
import json
import platform
import random
import time

import torch

from lab.core.config import var_dir

from . import model as M
from .data import load


def _write(path, obj):
    path.write_text(json.dumps(obj, indent=1))


def checksum(t: torch.Tensor) -> str:
    return hashlib.sha256(t.detach().float().cpu().numpy().tobytes()).hexdigest()[:16]


def run(run_id: str | None = None, epochs: int = 3, lr: float = 2e-4, r: int = 16, alpha: int = 32,
        batch_size: int = 8, seed: int = 0, max_train: int | None = None) -> dict:
    run_id = run_id or time.strftime("run-%Y%m%d-%H%M%S")
    d = var_dir("p02", "runs", run_id)
    status = {"run_id": run_id, "state": "loading", "step": 0, "total": 0, "history": [], "started": time.time()}
    _write(d / "status.json", status)
    try:
        random.seed(seed)
        torch.manual_seed(seed)
        train, val = load("train"), load("val")
        if max_train:
            train = train[:max_train]
        dev = M.device()
        tok, base = M.load_base(dev)

        # Evidence that the base stays frozen: checksum one base projection before and after.
        probe_name = "model.layers.0.self_attn.q_proj.weight"
        probe_before = checksum(dict(base.named_parameters())[probe_name])
        model, lora_info = M.attach_lora(base, r=r, alpha=alpha)

        tok.padding_side = "right"
        enc = [M.encode_example(tok, x["request"], x["label"]) for x in train]
        rng = random.Random(seed)
        rng.shuffle(enc)
        batches = [M.collate(enc[i:i + batch_size], tok.pad_token_id) for i in range(0, len(enc), batch_size)]
        venc = [M.encode_example(tok, x["request"], x["label"]) for x in val]
        vbatches = [M.collate(venc[i:i + batch_size], tok.pad_token_id) for i in range(0, len(venc), batch_size)]
        initial_val = M.evaluate_loss(model, vbatches)

        def on_step(step, total, history, elapsed):
            status.update(state="training", step=step, total=total, history=history, elapsed_s=round(elapsed, 1),
                          eta_s=round(elapsed / step * (total - step), 1) if step else None)
            if step % 5 == 0 or step == total or "val_loss" in history[-1]:
                _write(d / "status.json", status)

        t0 = time.time()
        history = M.train_loop(model, batches, epochs=epochs, lr=lr, val_batches=vbatches, on_step=on_step)
        train_s = time.time() - t0

        model.save_pretrained(str(d / "adapter"))  # save first: metadata problems must not lose a trained adapter
        # PEFT wraps adapted Linear layers, so the frozen weight becomes "...q_proj.base_layer.weight".
        wanted = probe_name.replace(".weight", ".base_layer.weight")
        base_param = next(p for n, p in model.named_parameters() if n.endswith(wanted))
        lora_b = [p for n, p in model.named_parameters() if "lora_B" in n]
        meta = {
            "run_id": run_id, "what_was_trained": "LoRA adapter (supervised fine-tuning, completion-only loss)",
            "base_model": M.BASE_MODEL, "base_revision": M.base_revision(), **lora_info,
            "frozen_params": lora_info["total_params"] - lora_info["trainable_params"],
            "weight_change_evidence": {
                "probe_base_weight": probe_name, "checksum_before": probe_before, "checksum_after": checksum(base_param),
                "base_weight_unchanged": probe_before == checksum(base_param),
                "lora_B_mean_abs_after": float(torch.stack([p.abs().mean() for p in lora_b]).mean()),
                "note": "LoRA B matrices start at zero, so a non-zero mean proves the adapter learned something."},
            "hyperparameters": {"epochs": epochs, "lr": lr, "batch_size": batch_size, "seed": seed, "optimizer": "AdamW, linear decay",
                                "max_len": 320, "loss": "cross-entropy on target tokens only (prompt masked)"},
            "data": {"train_examples": len(train), "val_examples": len(val),
                     "dataset_hash": json.loads((var_dir("p02", "dataset") / "report.json").read_text())["dataset_hash"]},
            "val_loss_before": round(initial_val, 4), "val_loss_after": history[-1].get("val_loss"),
            "train_seconds": round(train_s, 1), "device": dev,
            "versions": {"torch": torch.__version__, "transformers": __import__("transformers").__version__,
                         "peft": __import__("peft").__version__, "python": platform.python_version()},
        }
        _write(d / "metadata.json", meta)
        status.update(state="done", finished=time.time(), metadata=meta)
        _write(d / "status.json", status)
        return meta
    except Exception as e:
        status.update(state="failed", error=f"{type(e).__name__}: {e}")
        _write(d / "status.json", status)
        raise


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-train", type=int)
    a = ap.parse_args()
    print(json.dumps(run(a.run_id, a.epochs, a.lr, a.r, a.alpha, a.batch_size, max_train=a.max_train), indent=1))
