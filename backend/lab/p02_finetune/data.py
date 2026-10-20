"""Synthetic data generation, cleaning, deduplication and leakage-free splitting.

    python -m lab.p02_finetune.data --n 700 --seed 7

Gold labels are derived from the same sampled attributes that drive the text, so they are
correct by construction; ~8% of records are deliberately corrupted and ~10% duplicated so
the cleaning stage has real work to do (and tests can prove it catches them).
"""
import argparse
import hashlib
import json
import random
import re

from pydantic import ValidationError

from lab.core.config import var_dir

from .schema import COMPONENT_OWNER, Decision, business_errors

OBJECTS = {
    "billing": ["invoice PDF", "annual plan proration", "tax calculation", "payment retry emails"],
    "checkout": ["coupon code field", "Apple Pay button", "address autocomplete", "order confirmation page"],
    "search": ["search filters", "autocomplete suggestions", "search result ranking", "saved searches"],
    "onboarding": ["welcome tour", "signup form", "workspace setup wizard", "invite teammates step"],
    "notifications": ["email digest", "push notification settings", "Slack alerts", "notification center"],
    "reporting": ["revenue dashboard", "CSV export", "weekly usage report", "custom report builder"],
    "auth": ["password reset flow", "SSO login", "two-factor authentication", "session timeout"],
    "mobile_app": ["iOS app home screen", "Android offline mode", "mobile app login screen", "mobile app settings tab"],
}
FEATURES = ["dark mode", "bulk editing", "keyboard shortcuts", "multi-currency support", "an undo option", "date range filters", "share links"]
BUGS = [("it shows a blank screen", "blank screen"), ("it rejects valid input", "rejects valid input"), ("it throws a 500 error", "500 error"),
        ("it submits twice", "double submit"), ("it shows the wrong totals", "wrong totals")]
PRICES = [("raise the price by 10%", "raise price 10%"), ("add a 20% discount for annual plans", "20% annual discount"),
          ("introduce a free tier", "add free tier"), ("charge per seat instead of a flat fee", "per-seat pricing")]
UX = [("the main button is easier to find", "clearer primary button"), ("it takes fewer clicks", "fewer clicks"),
      ("the labels are clearer", "clearer labels"), ("it works on small screens", "small-screen layout")]
PERF = [("it takes 10 seconds to load", "10s load time"), ("it times out at peak hours", "peak-hour timeouts"),
        ("it freezes for large accounts", "freezes on large accounts")]

TEMPLATES = {
    "feature_request": (["can we add {f} to the {o}", "it would be great if the {o} supported {f}", "customers keep asking for {f} in the {o}"], "Add {f} to {o}"),
    "bug_fix": (["the {o} is broken, {b}", "{o} keeps failing - {b}", "seeing errors in the {o}: {b}"], "Fix {o}: {bs}"),
    "removal": (["we should get rid of the {o}", "please remove the {o}, nobody uses it", "kill the {o}, it's legacy"], "Remove {o}"),
    "pricing_change": (["we need to change pricing for the {o}: {p}", "finance wants to {p} for the {o}"], "Pricing change for {o}: {ps}"),
    "ux_change": (["the {o} is confusing, can we change it so {u}", "redesign the {o} so {u}"], "Improve {o} UX: {us}"),
    "performance": (["the {o} is super slow, {pf}", "{o} takes forever, {pf}"], "Speed up {o}: {pfs}"),
}
PRIORITY_CUES = {"P0": ["this is an outage!!", "production is down because of this", "customers literally cannot use it right now"],
                 "P1": ["this is blocking a big deal", "needs to happen this sprint", "urgent, lots of complaints"],
                 "P2": ["would be nice this quarter", "not urgent but annoying", "when you get a chance"],
                 "P3": ["someday maybe", "low priority idea", "no rush at all, just a thought"]}
IMPACT_CUES = {"high": ["affects every customer", "all users hit this", "every account sees it"],
               "medium": ["a bunch of enterprise customers mentioned it", "some teams are affected", "about a third of users"],
               "low": ["one customer asked", "only internal staff see this", "a single account reported it"]}
MIGRATION_CUES = ["we'd need to store a new field per account", "this means migrating the existing records",
                  "the database column has to change", "old data needs backfilling"]
OPENERS = ["hey team,", "Hi all -", "so um", "quick one:", "", "fwd from support:", "hello,"]
CLOSERS = ["thanks!", "cheers", "- sent from my phone", "lmk", "", "ty"]
FILLERS = ["honestly", "tbh", "I think", "basically", "like"]


def _typo(rng: random.Random, text: str) -> str:
    words = text.split()
    for _ in range(rng.choice([0, 0, 1, 2])):
        i = rng.randrange(len(words))
        w = words[i]
        if len(w) > 4 and w.isalpha():
            j = rng.randrange(1, len(w) - 2)
            words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2:]
    return " ".join(words)


def make_example(rng: random.Random) -> dict:
    ct = rng.choice(list(TEMPLATES))
    comp = rng.choice(list(OBJECTS))
    obj = rng.choice(OBJECTS[comp])
    prio = rng.choice(["P0", "P1"] if ct in ("bug_fix", "performance") and rng.random() < 0.4 else ["P1", "P2", "P3"])
    impact = rng.choice(["medium", "high"] if prio == "P0" else ["low", "medium", "high"])
    migration = ct in ("feature_request", "pricing_change", "removal") and rng.random() < 0.4
    f, (b, bs), (p, ps), (u, us), (pf, pfs) = rng.choice(FEATURES), rng.choice(BUGS), rng.choice(PRICES), rng.choice(UX), rng.choice(PERF)
    texts, summary_t = TEMPLATES[ct]
    vals = dict(o=obj, f=f, b=b, bs=bs, p=p, ps=ps, u=u, us=us, pf=pf, pfs=pfs)
    clauses = [rng.choice(texts).format(**vals), rng.choice(PRIORITY_CUES[prio]), rng.choice(IMPACT_CUES[impact])]
    if migration:
        clauses.append(rng.choice(MIGRATION_CUES))
    head = clauses[0]
    rest = clauses[1:]
    rng.shuffle(rest)
    if rng.random() < 0.3:
        rest.insert(0, rng.choice(FILLERS))
    text = " ".join(x for x in [rng.choice(OPENERS), head + ".", ". ".join(rest) + ".", rng.choice(CLOSERS)] if x)
    text = _typo(rng, text)
    if rng.random() < 0.3:
        text = text.lower()
    summary = summary_t.format(**vals)
    summary = summary[0].upper() + summary[1:]
    return {"request": text, "label": {"change_type": ct, "component": comp, "priority": prio, "customer_impact": impact,
                                       "requires_migration": migration, "owner_team": COMPONENT_OWNER[comp], "summary": summary[:120]},
            "source": "template", "injected": None}


def corrupt(rng: random.Random, ex: dict) -> dict:
    ex = json.loads(json.dumps(ex))
    kind = rng.choice(["bad_enum", "missing_field", "long_summary", "empty_request", "owner_mismatch"])
    lab = ex["label"]
    if kind == "bad_enum":
        lab["priority"] = "P5"
    elif kind == "missing_field":
        lab.pop("customer_impact")
    elif kind == "long_summary":
        lab["summary"] = (lab["summary"] + " ") * 6
    elif kind == "empty_request":
        ex["request"] = "  "
    else:
        lab["owner_team"] = next(t for t in ("payments", "growth", "platform", "mobile", "data") if t != lab["owner_team"])
    ex["injected"] = kind
    return ex


def generate(n: int, seed: int, invalid_rate=0.08, dup_rate=0.06, near_dup_rate=0.04) -> list[dict]:
    rng = random.Random(seed)
    out: list[dict] = []
    while len(out) < n:
        r = rng.random()
        if out and r < dup_rate:
            ex = dict(rng.choice(out), injected="exact_duplicate")
        elif out and r < dup_rate + near_dup_rate:
            src = rng.choice(out)
            ex = dict(src, request=src["request"] + " " + rng.choice(["pls", "thx!!", "asap", "(resending)"]), injected="near_duplicate")
        else:
            ex = make_example(rng)
            if rng.random() < invalid_rate:
                ex = corrupt(rng, ex)
        out.append(ex)
    for i, ex in enumerate(out):
        ex["id"] = f"ex{i:04d}"
    return out


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def shingles(text: str, k: int = 5) -> set[str]:
    t = normalise(text)
    return {t[i:i + k] for i in range(max(1, len(t) - k + 1))}


def clean(records: list[dict], near_dup_threshold: float = 0.85) -> tuple[list[dict], list[dict]]:
    """Returns (kept, rejected-with-reason). Order: validity -> business rules -> exact dup -> near dup."""
    kept, rejected, seen, kept_sh = [], [], set(), []
    for r in records:
        reason = None
        if len(r["request"].strip()) < 15:
            reason = "empty_or_too_short"
        else:
            try:
                d = Decision.model_validate(r["label"])
                errs = business_errors(d)
                reason = f"business_rule: {errs[0]}" if errs else None
            except ValidationError as e:
                x = e.errors()[0]
                reason = f"schema: {'.'.join(map(str, x['loc']))} {x['msg']}"
        if not reason:
            norm = normalise(r["request"])
            if norm in seen:
                reason = "exact_duplicate"
            else:
                sh = shingles(r["request"])
                # ponytail: O(n^2) Jaccard scan; MinHash/LSH once the dataset passes ~20k rows
                if any(len(sh & o) / len(sh | o) >= near_dup_threshold for o in kept_sh):
                    reason = "near_duplicate"
                else:
                    seen.add(norm)
                    kept_sh.append(sh)
        (rejected if reason else kept).append({**r, "reject_reason": reason} if reason else r)
    return kept, rejected


def split_of(request: str, test_pct=15, val_pct=10) -> str:
    """Deterministic: the bucket depends only on the normalised text, never on order or seed."""
    h = int(hashlib.sha256(normalise(request).encode()).hexdigest(), 16) % 100
    return "test" if h < test_pct else "val" if h < test_pct + val_pct else "train"


def build(n: int = 700, seed: int = 7) -> dict:
    raw = generate(n, seed)
    kept, rejected = clean(raw)
    splits: dict[str, list] = {"train": [], "val": [], "test": []}
    for r in kept:
        splits[split_of(r["request"])].append(r)
    d = var_dir("p02", "dataset")
    for name, rows in splits.items():
        (d / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (d / "rejected.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rejected))
    reasons: dict[str, int] = {}
    for r in rejected:
        key = r["reject_reason"].split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1
    injected_invalid = [r for r in raw if r["injected"] and "duplicate" not in r["injected"]]
    caught = sum(1 for r in rejected if r["injected"] and "duplicate" not in r["injected"])
    dist = {name: {f: _counts(rows, f) for f in ("change_type", "priority", "component")} for name, rows in splits.items()}
    report = {"n_generated": len(raw), "seed": seed, "kept": len(kept), "rejected": len(rejected), "reject_reasons": reasons,
              "injected_invalid": len(injected_invalid), "injected_invalid_caught": caught,
              "splits": {k: len(v) for k, v in splits.items()}, "label_distribution": dist,
              "dataset_hash": hashlib.sha256("".join(json.dumps(r, sort_keys=True) for r in kept).encode()).hexdigest()[:16]}
    (d / "report.json").write_text(json.dumps(report, indent=1))
    return report


def _counts(rows, field):
    c: dict = {}
    for r in rows:
        c[r["label"][field]] = c.get(r["label"][field], 0) + 1
    return dict(sorted(c.items()))


def load(split: str) -> list[dict]:
    p = var_dir("p02", "dataset") / f"{split}.jsonl"
    if not p.exists():
        build()
    return [json.loads(x) for x in p.read_text().splitlines() if x]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=700)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    print(json.dumps(build(a.n, a.seed), indent=1))
