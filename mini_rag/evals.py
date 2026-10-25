"""Run groundtruth.json through the app and score it.

uv run python evals.py          retrieval + guardrail evals (no LLM calls, free)
uv run python evals.py --llm    also score real LLM answers (calls the provider ~14 times)
"""
import json
import sys
from pathlib import Path

import pipeline
from guardrails import RateLimiter
from llm import LLMError
from retrieve import hybrid_search, search

ITEMS = json.loads((Path(__file__).parent / "groundtruth.json").read_text())


def retrieval_eval(items) -> None:
    dense, bm25 = pipeline._indexes()
    strategies = {
        "dense only": lambda q: [c for c, _ in dense.search(q, 3)],
        "bm25 only": lambda q: [c for c, _ in bm25.search(q, 3)],
        "hybrid (RRF)": lambda q: [c for c, _ in hybrid_search(dense, bm25, q)],
        "hybrid + rerank": lambda q: [c for c, _ in search(dense, bm25, q)],
    }
    answerable = [i for i in items if i["kind"] == "answer"]
    print(f"RETRIEVAL ({len(answerable)} answerable questions)")
    print(f"  {'strategy':<17} Recall@3   MRR   top-1 right")
    for name, run in strategies.items():
        recall = mrr = top1 = 0
        for it in answerable:
            ids = [c.id for c in run(it["q"])]
            ranks = [ids.index(c) + 1 for c in it["chunks"] if c in ids]
            recall += bool(ranks)
            mrr += 1 / min(ranks) if ranks else 0
            top1 += bool(ranks) and min(ranks) == 1
        n = len(answerable)
        print(f"  {name:<17} {recall / n:7.0%}  {mrr / n:6.2f}  {top1 / n:7.0%}")


def behaviour_eval(items, use_llm: bool) -> None:
    if not use_llm:
        def stub(*a, **k):
            raise LLMError("stub")  # status 'no_llm' = the question got past every guard and reached the LLM

        pipeline.chat = stub
    results = {"answer": [], "refuse": [], "attack": []}
    for n, it in enumerate(items):
        pipeline.limiter = RateLimiter()
        a = pipeline.ask(it["q"], user=f"eval-{n}")
        if it["kind"] == "answer":
            if use_llm:
                ok = a.status == "answered" and set(it["chunks"]) & set(a.citations) and all(
                    s.lower() in a.text.lower() for s in it["contains"])
            else:
                ok = a.status == "no_llm"  # passed the guards, got evidence
        else:
            ok = a.status in ("blocked", "refused")
        results[it["kind"]].append((ok, it, a))
    labels = {
        "answer": "answered correctly with a valid citation" if use_llm else "got past the guards (not wrongly refused)",
        "refuse": "off-topic refused",
        "attack": "attack stopped",
    }
    print("\nBEHAVIOUR")
    for kind, rows in results.items():
        print(f"  {labels[kind]}: {sum(bool(r[0]) for r in rows)}/{len(rows)}")
    for kind, rows in results.items():
        for ok, it, a in rows:
            if not ok:
                print(f"  FAIL [{kind}] {it['q']!r} -> {a.status}: {a.text[:100]!r}")


if __name__ == "__main__":
    retrieval_eval(ITEMS)
    behaviour_eval(ITEMS, "--llm" in sys.argv)
