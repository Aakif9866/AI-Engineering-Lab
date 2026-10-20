import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lab.core import jobs, providers
from lab.core.config import var_dir

from . import data
from .evaluate import OOD
from .evaluate import run as run_eval
from .schema import Decision

router = APIRouter(prefix="/api/finetune", tags=["02 IntentForge"])


@router.get("/environment")
def environment():
    out = {"torch": False, "device": None, "base_model": None, "base_cached": False}
    try:
        import torch

        from . import model as M
        out.update(torch=torch.__version__, device=M.device(), base_model=M.BASE_MODEL, base_revision=M.base_revision())
        out["base_cached"] = out["base_revision"] is not None
    except ImportError:
        out["note"] = "torch/transformers/peft not installed: dataset and rules evaluation still work"
    out["schema"] = Decision.model_json_schema()
    return out


@router.get("/dataset")
def dataset():
    d = var_dir("p02", "dataset")
    if not (d / "report.json").exists():
        data.build()
    report = json.loads((d / "report.json").read_text())
    samples = {s: data.load(s)[:4] for s in ("train", "test")}
    rejected = [json.loads(x) for x in (d / "rejected.jsonl").read_text().splitlines() if x]
    by_reason: dict = {}
    for r in rejected:
        by_reason.setdefault(r["reject_reason"].split(":")[0], []).append(r)
    return {"report": report, "samples": samples, "ood_samples": OOD[:3],
            "rejected_examples": {k: v[:2] for k, v in by_reason.items()}}


class BuildIn(BaseModel):
    n: int = Field(700, ge=100, le=5000)
    seed: int = 7


@router.post("/dataset/build")
def build(body: BuildIn):
    if jobs.running("p02-train"):
        raise HTTPException(409, "a training run is reading the dataset; wait for it to finish")
    return data.build(body.n, body.seed)


class TrainIn(BaseModel):
    epochs: int = Field(3, ge=1, le=10)
    lr: float = Field(2e-4, gt=0, le=1e-2)
    r: int = Field(16, ge=1, le=128)
    alpha: int = Field(32, ge=1, le=256)
    max_train: int | None = Field(None, ge=16)


@router.post("/train")
def train(body: TrainIn):
    import time
    run_id = time.strftime("run-%Y%m%d-%H%M%S")
    args = ["--run-id", run_id, "--epochs", str(body.epochs), "--lr", str(body.lr), "--r", str(body.r), "--alpha", str(body.alpha)]
    if body.max_train:
        args += ["--max-train", str(body.max_train)]
    try:
        jobs.spawn("p02-train", "lab.p02_finetune.train", args)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"run_id": run_id}


@router.get("/runs")
def runs():
    out = []
    for p in sorted(var_dir("p02", "runs").glob("*/status.json"), reverse=True):
        s = json.loads(p.read_text())
        if s["state"] in ("loading", "training") and not jobs.running("p02-train"):
            s["state"] = "interrupted"  # process died without writing a final state
        out.append(s)
    return {"runs": out, "job_running": bool(jobs.running("p02-train")), "log_tail": jobs.tail("p02-train")}


class EvalIn(BaseModel):
    system: str = Field(pattern=r"^(rules|base_prompted|base_constrained|adapter:[A-Za-z0-9\-]+|adapter_constrained:[A-Za-z0-9\-]+|api:(deepseek|groq))$")


@router.post("/evaluate")
def evaluate(body: EvalIn):
    if body.system == "rules":
        return {"done": True, "system": "rules", "result_slug": "rules", "summary": _summary(run_eval("rules"))}
    if body.system.startswith("api:") and not providers.available(body.system[4:]):
        raise providers.ProviderUnavailable(f"{body.system[4:]} is not configured")
    if body.system.startswith("adapter") and not (var_dir("p02", "runs", body.system.split(":", 1)[1]) / "adapter").exists():
        raise HTTPException(404, "no trained adapter with that run id")
    try:
        jobs.spawn("p02-eval", "lab.p02_finetune.evaluate", ["--system", body.system])
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"done": False, "system": body.system}


def _summary(r: dict) -> dict:
    return {"system": r["system"], "finished": r.get("finished"), "prompt_tokens_avg": r.get("prompt_tokens_avg"),
            "latency_ms_per_example": r.get("latency_ms_per_example"), "cost_usd": r.get("cost_usd"),
            "general_accuracy": (r.get("general") or {}).get("accuracy"),
            "slices": {k: {x: v[x] for x in v if x != "examples"} for k, v in r["slices"].items()}}


@router.get("/evals")
def evals():
    out = [_summary(json.loads(p.read_text())) for p in sorted(var_dir("p02", "evals").glob("*.json"))]
    return {"evals": out, "job_running": bool(jobs.running("p02-eval")), "log_tail": jobs.tail("p02-eval", 6)}


@router.get("/evals/{slug}")
def eval_detail(slug: str):
    p = var_dir("p02", "evals") / f"{slug}.json"
    if not p.exists() or "/" in slug:
        raise HTTPException(404, "no such evaluation")
    return json.loads(p.read_text())
