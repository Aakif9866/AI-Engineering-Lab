# Learning path

Ten sessions of 45 to 90 minutes each. Each one pairs a PDF chapter with something to *do* in the lab and a file to read afterwards. Everything works offline. Steps marked 💳 make small paid calls (well under $0.05 each).

| # | Read in the PDF | Do in the lab | Then read the code |
|---|---|---|---|
| 1 | Introduction, the two axes, ch. 7 overview | Open **TraceLens** and click *Generate demo traffic*. Open one trace and walk its span tree. | `backend/lab/core/tracing.py` (about 150 lines: spans, nesting, redaction) |
| 2 | Ch. 1, 1a–1b | **Evidence Atlas → Ask**: run *Compare strategies* on q04 (an identifier) and q11 (a paraphrase). Where do BM25 and dense disagree? | `p01_rag/retrieve.py` (RRF, rerank, ACL pre-filter) |
| 3 | Ch. 1, productionising | **Benchmark** tab, then **Experiments**: vary chunk size and k. Ask q21 ("expiry date") and see why the extractive generator answers wrongly while the gate lets it through. | `p01_rag/generate.py` (evidence gate, citation verification) |
| 4 | Ch. 3 | **CacheCraft → Threshold tuning**: why is there no "zero false positives" threshold? Then **Workload comparison**: compare *NO user scoping* with the default. | `p03_cache/gateway.py` (key fingerprint, dependency check) |
| 5 | Ch. 3, invalidation | **Knowledge base** tab: change the Pro price with "purge" off, then ask on the Gateway tab with dependency checking on and off. | `p03_cache/workload.py` (how correctness is labelled) |
| 6 | Ch. 4, 4a–4c | **TrustBoundary → Adversarial report** (compromised planner): find the cases where the detector missed and enforcement still held. Try `SELECT * FROM customers` in the SQL guard. | `p04_guardrails/policy.py`, `sqlguard.py` |
| 7 | Ch. 4, 4d–4f | Process the BEC preset as *operator*, then approve the pending action as *analyst* (it gets denied on review). 💳 Run the corpus with the real LLM planner and compare the "stopped by" column. | `p04_guardrails/pipeline.py` |
| 8 | Ch. 6 | **MissionReplay**: run S1 with *careful*, then *reckless*. Read the failure reasons, then the timeline. 💳 Run the batch with the LLM agent at 3 repeats. | `p06_agent_evals/evaluate.py` |
| 9 | Ch. 5 | **SignalLoop**: seed simulated feedback, then work the queue (approve one item, try to approve the poisoning attempt, delete one). Freeze a set, create a candidate with abstention gate 0, run the gate and try to promote it. | `p05_feedback/service.py` (`review`, `gate`, `promote`) |
| 10 | Ch. 2 | **IntentForge**: read the dataset report, then run the evaluations: rules, base_prompted, adapter, and both constrained variants. Compare the OOD column. Optionally train a new run with different r/epochs (about 5 to 10 minutes on CPU). | `p02_finetune/model.py` (training loop, constrained decoding) |

## Questions to answer after each session

1. RAG: Why can a retrieval-score gate never detect "on-topic but the fact is missing"?
2. Fine-tuning: What did the adapter learn that constrained decoding could not give the base model, and what did decoding give that training did not?
3. Caching: Which caching mistake did the workload make more often: semantic false hits, or unsafe reuse (stale data, another user's answer)? What does that say about where to spend engineering effort?
4. Guardrails: Which layer stopped the most attacks, and would you remove any layer given the numbers?
5. Feedback: Which seeded feedback item would have damaged the model if it had gone straight into training?
6. Agentic evals: Name a trajectory that ends with a correct-sounding summary but fails the evaluation. Which metric catches it?
7. Observability: Pick an error in TraceLens → Failures. Can you reach the exact span and its inputs (length plus hash) from the dashboard alone?

## Interview drill

Each workspace header names the PDF interview case it implements. For each one, answer the PDF question in five minutes, then open the workspace and check your answer against what the lab measured.
