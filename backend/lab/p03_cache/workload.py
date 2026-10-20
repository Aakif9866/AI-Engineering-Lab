"""Repeatable workloads, cache-mode comparison and threshold tuning.

    python -m lab.p03_cache.workload            # offline comparison + threshold sweep
    python -m lab.p03_cache.workload --n 300

The workload mixes popular repeats and paraphrases, confusable siblings (refund within vs after
30 days), personal questions from three users, volatile questions, unrelated questions, and a
mid-stream knowledge-base change (the Pro price goes from $8 to $10). Every query carries a
ground-truth label, so served hits can be scored for correctness, not just counted.
"""
import argparse
import itertools
import json
import random
import statistics
import time
import uuid
from dataclasses import asdict, replace

import numpy as np

from lab.core.config import var_dir
from lab.core.embeddings import get_embedder

from .gateway import KB, CacheConfig, ask, clear_namespace, edit_article, reset_kb

# Real users wrap the same question in different filler, which defeats exact keys but not meaning.
PREFIXES = ["", "", "", "hi, ", "quick question: ", "hey support - "]
SUFFIXES = ["", "", "", " thanks", " please", " asap"]
PRICE_CHANGE = ("pricing_pro", "The Pro plan costs $10 per month, or $100 per year when billed annually.")


def make_workload(n: int = 240, seed: int = 11) -> dict:
    rng = random.Random(seed)
    arts = [a for a in KB["articles"] if a["scope"] == "global"]
    weights = [1 / (i + 1) for i in range(len(arts))]  # Zipf-like popularity
    rng.shuffle(arts)
    queries = []
    for i in range(n):
        r = rng.random()
        if r < 0.70:
            a = rng.choices(arts, weights)[0]
            q = rng.choice(PREFIXES) + rng.choice(a["questions"]) + rng.choice(SUFFIXES)
            queries.append({"question": q, "user": rng.choice(["u1", "u2", "u3"]), "label": a["id"], "kind": "global"})
        elif r < 0.82:
            a = next(x for x in KB["articles"] if x["scope"] == "user")
            u = rng.choice(["u1", "u2", "u3"])
            queries.append({"question": rng.choice(a["questions"]), "user": u, "label": f"{a['id']}@{u}", "kind": "personal"})
        elif r < 0.88:
            a = next(x for x in KB["articles"] if x["scope"] == "volatile")
            queries.append({"question": rng.choice(a["questions"]), "user": "u1", "label": a["id"], "kind": "volatile"})
        else:
            queries.append({"question": rng.choice(KB["unrelated"]), "user": "u1", "label": "unrelated", "kind": "unrelated"})
    return {"seed": seed, "queries": queries, "events": [{"at": int(n * 0.6), "action": "edit_article", "article": PRICE_CHANGE[0], "answer": PRICE_CHANGE[1]}]}


def _pct(xs, q):
    return float(np.percentile(xs, q)) if xs else None


def run_mode(workload: dict, cfg: CacheConfig, label: str) -> dict:
    ns = f"wl-{uuid.uuid4().hex[:8]}"
    reset_kb()
    results = []
    events = {e["at"]: e for e in workload["events"]}
    for i, q in enumerate(workload["queries"]):
        if i in events:
            e = events[i]
            # With dependency checks off we also skip eager purging, to show what stale serving looks like.
            edit_article(e["article"], e["answer"], purge=cfg.dependency_check)
        results.append(ask(q["question"], q["user"], ns, cfg, label=q["label"], run_id=ns))
    reset_kb()
    clear_namespace(ns)
    hits = [r for r in results if r["event"].startswith("hit")]
    n = len(results)
    spent = [r["cost_usd"] or 0 for r in results]
    avoided = [r.get("cost_avoided_usd") or 0 for r in results]
    false_hits = [r for r in hits if r["correct"] == 0]
    return {
        "label": label, "config": asdict(cfg), "n": n,
        "events": {k: sum(r["event"] == k for r in results) for k in ("hit_exact", "hit_semantic", "miss", "rejected_match", "bypass", "upstream_error")},
        "hit_rate": len(hits) / n, "false_hits": len(false_hits), "false_hit_rate": len(false_hits) / len(hits) if hits else 0.0,
        "false_hit_examples": [{"question": r["question"], "matched": r["matched_question"], "similarity": r["similarity"],
                                "served_label": r["served_label"], "user": r["user_id"]} for r in false_hits[:8]],
        "upstream_calls": sum(r["event"] in ("miss", "rejected_match", "bypass") for r in results),
        "latency_measured_ms": {"p50": _pct([r["measured_ms"] for r in results], 50), "p95": _pct([r["measured_ms"] for r in results], 95)},
        "latency_modelled_ms": {"p50": _pct([r["modelled_ms"] for r in results], 50), "p95": _pct([r["modelled_ms"] for r in results], 95)},
        "cost_spent_usd": sum(spent), "cost_avoided_usd": sum(avoided),
        "cost_kind": results[0]["cost_kind"] if results else None,
        "evictions": sum(len(r["evicted"]) for r in results),
    }


def compare(n: int = 240, seed: int = 11, provider: str | None = None) -> dict:
    wl = make_workload(n, seed)
    base = CacheConfig(provider=provider)
    modes = [("no cache", replace(base, mode="off")), ("exact only", replace(base, mode="exact"))]
    modes += [(f"semantic @{t}", replace(base, mode="semantic", threshold=t)) for t in (0.75, 0.80, 0.85, 0.90, 0.95)]
    modes += [("semantic @0.90, NO dependency check", replace(base, threshold=0.90, dependency_check=False)),
              ("semantic @0.90, NO user scoping", replace(base, threshold=0.90, scope_aware=False))]
    t0 = time.time()
    out = {"workload": {"n": n, "seed": seed, "kinds": {k: sum(q["kind"] == k for q in wl["queries"]) for k in ("global", "personal", "volatile", "unrelated")},
                        "events": wl["events"]},
           "embedder": get_embedder().name, "upstream": provider or "offline (modelled 800 ms, estimated cost)",
           "modes": [run_mode(wl, cfg, label) for label, cfg in modes], "sweep": threshold_sweep()}
    out["duration_s"] = round(time.time() - t0, 2)
    (var_dir("results") / "p03_latest.json").write_text(json.dumps(out, indent=1))
    return out


def labelled_pairs() -> list[tuple[str, str, bool, str]]:
    """Positives: paraphrases of the same article. Negatives: questions from different articles,
    tagged 'confusable' when both articles share a group (e.g. refund within vs after 30 days)."""
    arts = [a for a in KB["articles"] if a["scope"] == "global"]
    pairs = [(x, y, True, a["group"]) for a in arts for x, y in itertools.combinations(a["questions"], 2)]
    for a, b in itertools.combinations(arts, 2):
        kind = "confusable" if a["group"] == b["group"] else "unrelated"
        pairs += [(x, y, False, kind) for x, y in zip(a["questions"], b["questions"])]
    return pairs


def threshold_sweep() -> dict:
    emb = get_embedder()
    pairs = labelled_pairs()
    texts = sorted({t for p in pairs for t in p[:2]})
    vec = dict(zip(texts, emb.embed(texts)))
    sims = [(float(vec[a] @ vec[b]), dup, kind) for a, b, dup, kind in pairs]
    rows = []
    for t in np.round(np.arange(0.30, 0.99, 0.01), 2):
        tp = int(sum(s >= t and d for s, d, _ in sims))
        fp = int(sum(s >= t and not d for s, d, _ in sims))
        fn = int(sum(s < t and d for s, d, _ in sims))
        conf_fp = int(sum(s >= t and not d and k == "confusable" for s, d, k in sims))
        p = tp / (tp + fp) if tp + fp else 1.0
        r = tp / (tp + fn) if tp + fn else 0.0
        rows.append({"threshold": float(t), "precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0, "false_positives": fp, "confusable_false_positives": conf_fp})
    best_f1 = max(rows, key=lambda x: x["f1"])
    safe = next((x for x in rows if x["false_positives"] == 0), None)
    dist = {k: [round(s, 3) for s, d, kk in sims if (kk == k if not d else k == "duplicate")] for k in ("duplicate", "confusable", "unrelated")}
    return {"embedder": emb.name, "pairs": len(pairs), "positives": sum(d for _, d, _ in sims), "rows": rows, "best_f1": best_f1,
            "lowest_zero_false_positive": safe,
            "similarity_summary": {k: {"min": min(v), "median": statistics.median(v), "max": max(v)} for k, v in dist.items() if v},
            "caveat": "Tuned on the same paraphrase set the workload draws from; production thresholds need a held-out labelled set."}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=240)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--provider")
    a = ap.parse_args()
    res = compare(a.n, a.seed, a.provider)
    print(f"embedder {res['embedder']} | upstream {res['upstream']} | {res['duration_s']}s")
    for m in res["modes"]:
        print(f"{m['label']:38s} hit={m['hit_rate']:.2f} false_hits={m['false_hits']:3d} ({m['false_hit_rate']:.2f}) upstream={m['upstream_calls']:3d} "
              f"p50_modelled={m['latency_modelled_ms']['p50']:.1f}ms cost_spent=${m['cost_spent_usd']:.5f} avoided=${m['cost_avoided_usd']:.5f}")
    s = res["sweep"]
    print("sweep best F1", s["best_f1"], "\nzero-FP threshold", s["lowest_zero_false_positive"], "\n", s["similarity_summary"])
