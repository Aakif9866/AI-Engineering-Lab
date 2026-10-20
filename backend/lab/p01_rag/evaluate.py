"""Benchmark evaluation and experiment grid for Evidence Atlas.

Retrieval quality (Recall@k, MRR, nDCG@k at document level) is scored separately from answer
quality (correctness, abstention, citation validity, groundedness), per PDF 1: a RAG system can
fail purely at retrieval while generation looks fine, and conflating the two wastes debugging time.

    python -m lab.p01_rag.evaluate                 # offline grid, default embedder
    python -m lab.p01_rag.evaluate --embedder hash
    python -m lab.p01_rag.evaluate --llm --limit 6 # also run LLM generation (costs money)
"""
import argparse
import json
import math
import time
from dataclasses import asdict

from lab.core.config import DATA, var_dir

from .generate import answer
from .index import IndexConfig, get_index
from .retrieve import RetrievalConfig, retrieve

BENCH = json.loads((DATA / "p01" / "benchmark.json").read_text())["items"]


def doc_ranking(hits) -> list[str]:
    seen: list[str] = []
    for h in hits:
        if h.chunk.doc_id not in seen:
            seen.append(h.chunk.doc_id)
    return seen


def retrieval_metrics(ranked_docs: list[str], support: list[str], k: int) -> dict:
    rel = set(support)
    top = ranked_docs[:k]
    first = next((i for i, d in enumerate(ranked_docs) if d in rel), None)
    dcg = sum(1 / math.log2(i + 2) for i, d in enumerate(top) if d in rel)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(rel), k)))
    return {"recall": len(rel & set(top)) / len(rel), "mrr": 1 / (first + 1) if first is not None else 0.0,
            "ndcg": dcg / idcg if idcg else 0.0}


def answer_correct(text: str, must_contain: list[list[str]]) -> bool:
    from .generate import canonical
    t = canonical(text).lower()
    return all(any(alt.lower() in t for alt in group) for group in must_contain)


def run_benchmark(icfg: IndexConfig, rcfg: RetrievalConfig, *, use_llm=False, provider=None,
                  min_coverage=0.35, items=None) -> dict:
    index = get_index(icfg)
    items = items or BENCH
    rows = []
    for it in items:
        hits = retrieve(index, it["question"], rcfg)
        a = answer(index, it["question"], hits, use_llm=use_llm, provider=provider, min_coverage=min_coverage)
        row = {"id": it["id"], "type": it["type"], "question": it["question"], "answer": a.text,
               "abstained": a.abstained, "expected_abstain": it["abstain"], "retrieved_docs": doc_ranking(hits),
               "groundedness": a.verification.get("groundedness"),
               "citation_validity": a.verification.get("citation_validity")}
        if not it["abstain"]:
            if it.get("support"):  # feedback-derived items may have no labelled support documents
                row.update(retrieval_metrics(row["retrieved_docs"], it["support"], rcfg.k))
            row["correct"] = (not a.abstained) and answer_correct(a.text, it["must_contain"])
        else:
            row["correct"] = a.abstained
        rows.append(row)
    ans = [r for r in rows if not r["expected_abstain"]]
    una = [r for r in rows if r["expected_abstain"]]
    answered = [r for r in rows if not r["abstained"]]
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None  # noqa: E731
    by_type: dict = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r["correct"])
    return {
        "config": {"index": asdict(icfg), "retrieval": asdict(rcfg), "embedder": index.embedder_name,
                   "generator": "llm" if use_llm else "extractive", "min_coverage": min_coverage},
        "retrieval": {f"recall@{rcfg.k}": mean([r["recall"] for r in ans if "recall" in r]), "mrr": mean([r["mrr"] for r in ans if "mrr" in r]),
                      f"ndcg@{rcfg.k}": mean([r["ndcg"] for r in ans if "ndcg" in r])},
        "answers": {"accuracy_answerable": mean([r["correct"] for r in ans]),
                    "abstention_on_unanswerable": mean([r["abstained"] for r in una]),
                    "false_abstention": mean([r["abstained"] for r in ans]),
                    "citation_validity": mean([r["citation_validity"] for r in answered if r["citation_validity"] is not None]),
                    "groundedness": mean([r["groundedness"] for r in answered if r["groundedness"] is not None])},
        "by_type": {t: mean(v) for t, v in by_type.items()},
        "n": len(rows), "rows": rows,
    }


GRID = {
    "chunking": [IndexConfig(60, 10, "fixed"), IndexConfig(120, 20, "fixed"), IndexConfig(250, 40, "fixed"),
                 IndexConfig(120, 20, "section")],
    "retrieval": [RetrievalConfig(strategy="bm25", reranker="none"), RetrievalConfig(strategy="dense", reranker="none"),
                  RetrievalConfig(strategy="hybrid", reranker="none"), RetrievalConfig(strategy="hybrid", reranker="overlap")],
    "budget": [RetrievalConfig(k=1, context_budget=150), RetrievalConfig(k=3, context_budget=350),
               RetrievalConfig(k=5, context_budget=600), RetrievalConfig(k=8, context_budget=1200)],
}


def summarise(res: dict) -> dict:
    return {"config": res["config"], "retrieval": res["retrieval"], "answers": res["answers"], "by_type": res["by_type"]}


def run_grid(embedder: str | None = None, use_llm=False, provider=None, limit=None) -> dict:
    items = BENCH[:limit] if limit else BENCH
    t0 = time.time()
    out: dict = {"started": t0, "embedder_requested": embedder, "experiments": {}}
    for i in GRID["chunking"]:  # vary chunking, hold retrieval at the default
        i.embedder = embedder
    out["experiments"]["chunking"] = [summarise(run_benchmark(i, RetrievalConfig(), items=items)) for i in GRID["chunking"]]
    base = IndexConfig(embedder=embedder)
    out["experiments"]["retrieval"] = [summarise(run_benchmark(base, r, items=items)) for r in GRID["retrieval"]]
    out["experiments"]["budget"] = [summarise(run_benchmark(base, r, items=items)) for r in GRID["budget"]]
    out["default_rows"] = run_benchmark(base, RetrievalConfig(), items=items)["rows"]
    if use_llm:
        llm_res = run_benchmark(base, RetrievalConfig(), use_llm=True, provider=provider, items=items)
        gen = {"generator": [summarise(run_benchmark(base, RetrievalConfig(), items=items)), summarise(llm_res)],
               "llm_rows": llm_res["rows"], "started": t0}
        (var_dir("results") / "p01_generator.json").write_text(json.dumps(gen, indent=1))
    gen_path = var_dir("results") / "p01_generator.json"
    if gen_path.exists():  # paid LLM comparison is kept across offline re-runs
        gen = json.loads(gen_path.read_text())
        out["experiments"]["generator"] = gen["generator"]
        out["llm_rows"], out["generator_run_started"] = gen["llm_rows"], gen["started"]
    out["duration_s"] = round(time.time() - t0, 2)
    path = var_dir("results") / "p01_latest.json"
    path.write_text(json.dumps(out, indent=1))
    out["saved_to"] = str(path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", default=None)
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--provider", default=None)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    res = run_grid(a.embedder, a.llm, a.provider, a.limit)
    for name, exps in res["experiments"].items():
        print(f"\n== {name} ==")
        for e in exps:
            c = e["config"]
            label = f"{c['index']['strategy']}/{c['index']['chunk_size']} {c['retrieval']['strategy']}+{c['retrieval']['reranker']} k={c['retrieval']['k']} gen={c['generator']}"
            print(f"{label:55s} retrieval={e['retrieval']} answers={e['answers']}")
    print(f"\nsaved {res['saved_to']} in {res['duration_s']}s")


if __name__ == "__main__":
    main()
