"""Held-out evaluation of every system on the same slices.

    python -m lab.p02_finetune.evaluate --system rules
    python -m lab.p02_finetune.evaluate --system base_prompted
    python -m lab.p02_finetune.evaluate --system adapter:run-v1
    python -m lab.p02_finetune.evaluate --system api:deepseek     # paid, ~115 short calls

Slices: test (held-out, in-distribution synthetic), ood (20 hand-written natural requests the
templates never produce), general (12 simple questions, for forgetting; model systems only).
"""
import argparse
import json
import re
import time

from lab.core import providers, tracing
from lab.core.config import DATA, var_dir

from .data import load
from .schema import COMPONENT_OWNER, aggregate, score

OOD = [json.loads(x) for x in (DATA / "p02" / "ood.jsonl").read_text().splitlines() if x]
GENERAL = json.loads((DATA / "p02" / "general.json").read_text())["items"]


def _first(t: str, table: list, default: str) -> str:
    return next((k for k, words in table if any(w in t for w in words)), default)


def rules_predict(text: str) -> str:
    """A keyword system an engineer could write in an afternoon: the cheapest baseline."""
    t = text.lower()
    ct = _first(t, [("pricing_change", ["price", "pricing", "discount", "free tier", "per seat", "per-seat", "charge "]),
                     ("removal", ["remove", "get rid", "kill the", "sunset", "retire", "drop the", "deprecate"]),
                     ("performance", ["slow", "forever", "time out", "times out", "lag", "freez", "late"]),
                     ("bug_fix", ["broken", "error", "fail", "crash", "bug", "wrong", "blank", "twice", "down"]),
                     ("ux_change", ["confusing", "redesign", "can't find", "hard to find", "layout", "clicks", "prominent"])],
                "feature_request")
    comp = _first(t, [("mobile_app", ["ios", "android", "mobile", "iphone"]), ("checkout", ["checkout", "coupon", "apple pay", "address", "order", "pay button"]),
                      ("billing", ["invoice", "tax", "billing", "proration", "payment retry", "plan"]), ("search", ["search", "autocomplete"]),
                      ("onboarding", ["onboarding", "welcome", "signup", "setup wizard", "invite"]),
                      ("notifications", ["notification", "digest", "slack", "push", "email"]),
                      ("reporting", ["report", "dashboard", "csv", "export"]), ("auth", ["password", "sso", "login", "two-factor", "2fa", "session"])],
                  "search")
    prio = _first(t, [("P0", ["outage", "is down", "completely down", "cannot", "can't sign", "production is down", "revenue is zero"]),
                      ("P1", ["sprint", "urgent", "blocking", "escalation", "high priority"]),
                      ("P3", ["someday", "no rush", "low priority", "no urgency", "low urgency", "not committed"])], "P2")
    impact = _first(t, [("high", ["every", "all users", "all customers", "everyone", "all eu", "all big", "all workspaces"]),
                        ("low", ["one customer", "single", "internal", "a few", "handful", "a couple"])], "medium")
    migration = any(w in t for w in ["store", "migrat", "column", "backfill", "table", "database", "persist", "stored"])
    summary = re.sub(r"\s+", " ", re.split(r"[.!?]", text.strip())[0])[:100] or "Change request"
    return json.dumps({"change_type": ct, "component": comp, "priority": prio, "customer_impact": impact,
                       "requires_migration": migration, "owner_team": COMPONENT_OWNER[comp], "summary": summary.capitalize()})


def _general_correct(ans: str, alts: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(a)}\b", ans.lower()) for a in alts)


def run(system: str, limit: int | None = None) -> dict:
    test = load("test")[:limit] if limit else load("test")
    slices = {"test": test, "ood": OOD}
    preds: dict[str, list[str]] = {}
    result: dict = {"system": system, "started": time.time(), "prompt_tokens_avg": None, "cost_usd": None}
    with tracing.span("finetune.evaluate", kind="evaluation", module="intentforge", system=system) as sp:
        t0 = time.perf_counter()
        n_items = sum(len(v) for v in slices.values())
        if system == "rules":
            preds = {k: [rules_predict(x["request"]) for x in v] for k, v in slices.items()}
        elif system.startswith("api:"):
            from .model import BASELINE_SYSTEM
            prov, cost, toks = system.split(":", 1)[1], 0.0, []
            for k, v in slices.items():
                preds[k] = []
                for x in v:
                    try:
                        r = providers.chat([{"role": "system", "content": BASELINE_SYSTEM}, {"role": "user", "content": x["request"]}],
                                           provider=prov, temperature=0.0, max_tokens=600, json_mode=True, module="intentforge",
                                           prompt_version="intent-baseline-v1")
                        preds[k].append(r.text)
                        cost += r.cost_usd or 0
                        toks.append(r.input_tokens or 0)
                    except providers.ProviderError as e:
                        preds[k].append(f"<provider error: {e.error_type}>")
            result["cost_usd"], result["prompt_tokens_avg"] = round(cost, 6), round(sum(toks) / max(1, len(toks)), 1)
        else:
            import torch
            from . import model as M
            tok, base = M.load_base()
            constrained = system.startswith(("base_constrained", "adapter_constrained:"))
            if system in ("base_prompted", "base_constrained"):
                mdl, sysmsg = base, M.BASELINE_SYSTEM
            elif system.startswith(("adapter:", "adapter_constrained:")):
                from peft import PeftModel
                mdl = PeftModel.from_pretrained(base, str(var_dir("p02", "runs", system.split(":", 1)[1]) / "adapter"))
                sysmsg = M.FT_SYSTEM
            else:
                raise ValueError(f"unknown system {system!r}")
            for k, v in slices.items():
                prompts = [M.prompt_text(tok, x["request"], sysmsg) for x in v]
                preds[k] = [M.constrained_generate(mdl, tok, pr) for pr in prompts] if constrained else M.generate(mdl, tok, prompts)
            result["prompt_tokens_avg"] = round(sum(len(tok(M.prompt_text(tok, x["request"], sysmsg))["input_ids"]) for x in test) / len(test), 1)
            gprompts = [M.prompt_text(tok, g["q"], "You are a helpful assistant. Answer briefly.") for g in GENERAL]
            gans = M.generate(mdl, tok, gprompts, max_new_tokens=24)
            result["general"] = {"accuracy": sum(_general_correct(a, g["a"]) for a, g in zip(gans, GENERAL)) / len(GENERAL),
                                 "answers": [{"q": g["q"], "answer": a.strip()[:80], "correct": _general_correct(a, g["a"])} for a, g in zip(gans, GENERAL)]}
            del mdl, base
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        result["latency_ms_per_example"] = round((time.perf_counter() - t0) * 1000 / n_items, 1)
        result["slices"] = {}
        for k, v in slices.items():
            scored = [score(p, x["label"]) for p, x in zip(preds[k], v)]
            result["slices"][k] = {**aggregate(scored), "examples": [
                {"id": x["id"], "request": x["request"], "gold": x["label"], "output": p[:400], **s}
                for x, p, s in zip(v, preds[k], scored)]}
        sp.set(test_exact=result["slices"]["test"]["exact_all_fields"], ood_exact=result["slices"]["ood"]["exact_all_fields"])
    result["finished"] = time.time()
    slug = system.replace(":", "_").replace("/", "_")
    (var_dir("p02", "evals") / f"{slug}.json").write_text(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    r = run(a.system, a.limit)
    for k, s in r["slices"].items():
        print(f"{k:5s} json={s['json_valid']:.2f} schema={s['schema_valid']:.2f} exact={s['exact_all_fields']:.2f} "
              f"summaryF1={s['summary_f1']:.2f} fields={ {f: round(v, 2) for f, v in s['per_field'].items()} }")
    if "general" in r:
        print("general accuracy", r["general"]["accuracy"])
    print("prompt tokens avg", r["prompt_tokens_avg"], "latency/example ms", r["latency_ms_per_example"], "cost", r["cost_usd"])
