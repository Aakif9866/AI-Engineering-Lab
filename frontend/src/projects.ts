/** Registry of the seven workspaces plus their learning content. Grounded in the reference PDF
 * ("Seven Design Patterns: A Technical Reference for AI Engineering Interviews"). */

export type Project = {
  slug: string;
  num: string;
  name: string;
  pattern: string;
  axis: "Quality" | "Cost / Risk" | "Both";
  hue: string; // icon/illustration colour only — teal stays the interactive accent
  tagline: string;
  problem: string;
  pdf: string; // the PDF scenario this project implements
  learn: { title: string; body: string }[];
  limitations: string[];
  v2: string[];
};

export const PROJECTS: Project[] = [
  {
    slug: "evidence-atlas", num: "01", name: "Evidence Atlas", pattern: "Retrieval-Augmented Generation", axis: "Quality", hue: "text-sky-500",
    tagline: "Hybrid retrieval, verified citations and abstention over an internal investigation corpus.",
    problem: "Models don't know your private, changing documents. RAG retrieves evidence at query time and grounds the answer in it, which costs far less than retraining whenever the documents change.",
    pdf: "Interview case: Q&A over company policies, procedures and contracts with weekly updates, citations and access control.",
    learn: [
      { title: "Score retrieval separately from generation", body: "Recall@k, MRR and nDCG score whether the right documents came back. Answer accuracy, citation validity and groundedness score what the model did with them. When an answer is wrong, the split tells you which stage to fix." },
      { title: "Why hybrid beats either alone", body: "Dense embeddings generalise away exact identifiers (CTR-2291, VX-88213). BM25 matches those trivially but misses paraphrases. Reciprocal rank fusion merges the two ranked lists without having to compare their incomparable scores." },
      { title: "Abstention is a design feature", body: "A cheap evidence gate (lexical coverage OR dense similarity) refuses before spending a model call when nothing relevant was retrieved. It can't catch an on-topic question about a missing fact; only the generator can, which is exactly why the extractive baseline fails q21 and q24." },
      { title: "Embedding versioning", body: "Vectors from different embedding models live in different spaces. Each index records its embedder and refuses to mix vectors from another one." },
      { title: "Incremental indexing", body: "Every document carries a content hash, and a sync re-embeds only documents whose hash changed. Ingest a document and watch the sync stats." },
      { title: "Lexical groundedness has a ceiling", body: "The verifier checks that each sentence's words and numbers appear in the passages it cites. It correctly flags fabricated numbers, but it also flags correct derived claims (\"5 hours 20 minutes later\") because those are computed, not quoted. An NLI model is the upgrade." },
    ],
    limitations: [
      "15-document corpus: retrieval metrics sit near ceiling, so the benchmark mostly separates generators. A larger, noisier corpus is needed to separate retrievers.",
      "The dense gate threshold (0.50) was calibrated on the same 24 questions it is evaluated on.",
      "Groundedness is lexical (word and number overlap), not entailment.",
      "Exact numpy cosine search; no ANN index. Fine at this scale, not at millions of vectors.",
      "Ingestion accepts text, markdown and email; no PDF or HTML extraction.",
    ],
    v2: ["Temporal retrieval (as-of-date queries over versioned documents)", "Contradictory-source analysis that pairs conflicting claims across documents", "Robustness tests with injected misleading documents", "NLI-based groundedness", "Held-out calibration set for abstention thresholds", "Agentic/iterative retrieval for multi-hop questions"],
  },
  {
    slug: "intentforge", num: "02", name: "IntentForge", pattern: "Fine-tuning", axis: "Quality", hue: "text-violet-500",
    tagline: "Messy change requests → strict JSON decisions, comparing a baseline prompt with a real LoRA adapter.",
    problem: "Prompting got the content right but the format stays inconsistent, so downstream parsers break. Fine-tuning bakes the output contract into the weights.",
    pdf: "Interview case: correct answers in a verbose, inconsistent format that downstream systems can't parse.",
    learn: [
      { title: "Baseline first", body: "Fine-tuning has the highest fixed cost of any pattern. This workspace always measures prompted baselines (same base model zero-shot, a keyword rule system, and optionally an API model) before trusting the adapter." },
      { title: "What LoRA actually changes", body: "LoRA freezes every base weight and trains small low-rank matrices A·B injected into attention projections. Training metadata records the exact trainable versus frozen parameter counts and which modules received adapters." },
      { title: "Data quality over quantity", body: "The pipeline validates against the schema, rejects invalid examples, removes exact and near duplicates before splitting (preventing train/test leakage), and splits deterministically by content hash." },
      { title: "Forgetting is measurable", body: "A small general-capability slice is evaluated on both the base model and the adapter, so format gains can't hide capability losses." },
      { title: "Low loss can hide field errors", body: "Run v1 reached a validation loss of 0.19, yet it still invented enum values like component \"pay_per_base\". Loss averages over every token, and most tokens (keys, punctuation, copied summaries) are easy. Only per-field evaluation exposes the gap." },
      { title: "Constrained decoding is a separate lever", body: "Picking each enum value by likelihood among the allowed values makes output schema-valid by construction (PDF 4b). Applying it to both base and adapter separates what decoding fixes (format) from what training taught (the mapping)." },
      { title: "Score with the training tokenisation", body: "The first constrained-decoding version always chose \"performance\". It scored a bare closing quote, but training always saw the quote merged with the following comma (\"\",\" is one token). Scoring must reproduce training tokenisation exactly, including boundaries." },
    ],
    limitations: [
      "SmolLM2-135M-Instruct is tiny, so absolute quality is modest. The point is a real, inspectable training run on an 8 GB laptop.",
      "Synthetic, template-generated data: the distribution is narrower than real requests.",
      "QLoRA is not used because bitsandbytes 4-bit isn't supported on Apple Silicon. LoRA trains in fp32 on CPU by default: on the 8 GB M1 it was built on, MPS gave no speedup and its memory growth pushed the system into swap.",
      "The rules baseline and the OOD slice were written by the same author, so the rules' OOD score is, if anything, optimistic.",
    ],
    v2: ["Hard-negative mining from evaluation failures", "Quantization of the merged model", "Confidence calibration on field predictions", "Confidence-aware routing between adapter and API model", "DPO on preference pairs from SignalLoop"],
  },
  {
    slug: "cachecraft", num: "03", name: "CacheCraft", pattern: "LLM Caching", axis: "Cost / Risk", hue: "text-emerald-500",
    tagline: "Layered exact and semantic caches with dependency-aware invalidation, measured on a labelled workload.",
    problem: "Most traffic repeats. Serving a stored answer cuts latency and cost, but a wrong or stale hit silently serves an incorrect answer.",
    pdf: "Interview case: an FAQ system with 100k queries a day where 60% are variations of 500 questions.",
    learn: [
      { title: "Layer the caches", body: "Exact match runs first: near-free and zero false-positive risk. Semantic match runs second to cover paraphrases. Provider prefix/KV caching sits underneath both and appears as cached_tokens in real usage." },
      { title: "The threshold is the design problem", body: "Too low serves wrong answers to different questions; too high collapses the hit rate. The threshold sweep runs on labelled duplicate and non-duplicate pairs." },
      { title: "Hits are not correctness", body: "Every served hit is checked against the workload's ground-truth intent and the data version. False hits are counted separately." },
      { title: "Invalidation by version hash", body: "Each entry records the content hashes of the knowledge-base articles it depends on. Editing an article invalidates exactly the entries that used it." },
      { title: "Personalised queries", body: "Account-specific questions are keyed by user. Time-sensitive ones bypass the cache entirely." },
    ],
    limitations: [
      "Measured with MiniLM: no threshold reaches zero false hits on this knowledge base. Confusable pairs reach 0.986 similarity, higher than any true paraphrase pair (max 0.854), so even at 0.95 three wrong answers were served in the 240-query workload.",
      "In offline mode the upstream model is a deterministic local answerer with a clearly labelled modelled latency (800 ms); cost avoided is an estimate from configured pricing.",
      "Personalisation and time-sensitivity are detected with patterns, not a classifier.",
      "The threshold sweep uses the same paraphrase set the workload draws from; production needs a held-out labelled set.",
    ],
    v2: ["Adaptive per-intent thresholds", "Workload-aware TTL policies", "Model routing on cache-miss difficulty"],
  },
  {
    slug: "trustboundary", num: "04", name: "TrustBoundary", pattern: "Guardrails & Defensive UX", axis: "Cost / Risk", hue: "text-rose-500",
    tagline: "Untrusted email and documents in, policy-checked actions out, with backend enforcement that holds even when the model is fooled.",
    problem: "Models obey instructions hidden in the data they read. Guardrails constrain inputs and outputs, and Defensive UX handles what still gets through.",
    pdf: "Interview case: an NL-to-SQL analytics tool with injection, destructive statements, least privilege and show-before-execute.",
    learn: [
      { title: "Detection is a signal; enforcement is the boundary", body: "Injection detectors produce a risk score. The backend policy engine, not the model, decides which tools can run, with which arguments, for which role." },
      { title: "Least privilege at the database", body: "Generated SQL runs on a read-only SQLite connection (mode=ro) after a statement-level validator. Even a validator bug can't write." },
      { title: "Generate → validate → retry", body: "Model output is parsed against a strict schema. Validation errors go back into one bounded retry, then the system fails closed." },
      { title: "Friction by design", body: "Sensitive actions such as sending email or creating priority tickets wait in an approval queue. Cost of error decides the friction, not a uniform rule." },
      { title: "Count which layer stopped each attack", body: "Input block, redaction, policy, database authorizer, output stripping, approval: the adversarial report attributes each stop. Defence in depth means no single layer is load-bearing." },
    ],
    limitations: [
      "Heuristic detection caught 45% of attacks in the corpus; enforcement held on 100%. The report lists every detector miss.",
      "Running the corpus with DeepSeek as the planner found a real gap: the model reported a beacon as a plain-text URL, which the output guardrail didn't catch. It's now fixed by defanging external hosts. LLM-planner results vary run to run (29 or 30 of 30 after the fix).",
      "The offline 'compromised model' is a simulation that deliberately obeys embedded instructions to exercise enforcement.",
      "The model-based detector (Groq Prompt Guard) is wired in but unverified until a GROQ_API_KEY is configured.",
    ],
    v2: ["Versioned policies with diff and rollback", "Learned risk scoring", "Adversarial regression generation", "Red-team results dashboard over time"],
  },
  {
    slug: "signalloop", num: "05", name: "SignalLoop", pattern: "User Feedback", axis: "Both", hue: "text-amber-500",
    tagline: "A research assistant whose feedback flows through review, curation and a release gate. Nothing auto-trains.",
    problem: "Without a feedback loop, quality ships fixed and decays. With one, the system compounds, but only if feedback is curated, de-biased and privacy-safe.",
    pdf: "Interview case: a writing assistant that plateaued after six months; design the full flywheel.",
    learn: [
      { title: "Explicit, implicit and corrections", body: "Ratings are clean but sparse. Implicit signals (regenerate, copy, edit distance) are plentiful but noisy. Corrections are the most valuable: free in-distribution training pairs." },
      { title: "Curation sits between collection and training", body: "Feedback lands in a review queue with deduplication, clustering and PII scanning. Only approved items enter a dataset, and each keeps its provenance." },
      { title: "Frozen evals and release gates", body: "Candidates are compared against the baseline on an immutable, content-hashed eval set. The gate blocks promotion on any defined regression." },
      { title: "Flywheel latency", body: "Time from a user correction to an approved dataset example is tracked as an explicit metric." },
    ],
    limitations: ["Single-user local demo: bias metrics (concentration of approved feedback by user) use simulated user ids.", "Clustering is greedy cosine over question embeddings."],
    v2: ["Prioritised improvement recommendations", "Active-learning selection of what to ask users", "Controlled fine-tuning dataset export to IntentForge"],
  },
  {
    slug: "missionreplay", num: "06", name: "MissionReplay", pattern: "Agentic Evaluations", axis: "Quality", hue: "text-orange-500",
    tagline: "A deterministic emergency-response simulator that scores every agent trajectory, not just its final words.",
    problem: "An agent can reach the right outcome with the wrong tools, in the wrong order, five extra times. Trajectory evaluation shows where it went wrong.",
    pdf: "Interview case: a travel-booking agent with 85% success and clustered failures; diagnose with trajectory evals.",
    learn: [
      { title: "Deterministic first, judged second", body: "Success predicates, tool precision/recall, argument validity, safety violations and step budgets are code. An optional LLM judge is stored separately and labelled as such." },
      { title: "Grounding per step", body: "Dispatching a unit the agent never observed as available is flagged, which is the simulator's version of booking a flight the search never returned." },
      { title: "Same schema as observability", body: "Every run is stored as a trace, so a production trajectory could be replayed into this harness." },
      { title: "Repeat stochastic agents", body: "At temperature 0.7 the LLM agent passed 17 of 18 missions. The one failure dispatched units for a duplicate report. A single run per scenario would probably have missed it." },
    ],
    limitations: [
      "Six hand-written scenarios; the PDF recommends 30 to 50. DeepSeek passed 6 of 6 at temperature 0.2 (one run each) and 17 of 18 at 0.7 (three runs each), so the scenarios are not yet hard enough to rank strong models.",
      "Plan-versus-execution scoring is only available through the optional LLM judge.",
    ],
    v2: ["Stochastic scenarios", "Fault injection campaigns", "Adversarial tool results", "Regression scenarios generated from reviewed failures"],
  },
  {
    slug: "tracelens", num: "07", name: "TraceLens", pattern: "LLM Observability", axis: "Cost / Risk", hue: "text-cyan-500",
    tagline: "Traces, spans, percentiles, cost, alerts and drift for every other workspace in this lab.",
    problem: "Evals predict behaviour before you ship. Observability records what actually happened, for one user, on one request, right now.",
    pdf: "Interview case: a customer reports a wrong agent answer you can't reproduce because only the final output was logged.",
    learn: [
      { title: "Root span plus children", body: "Every module request becomes a root span with children for retrieval, generation, cache decisions, guardrails and tool calls. Failures are attributed to the exact step." },
      { title: "Redact before persisting", body: "Content capture is off by default (length and hash only). When on, PII and secrets are redacted at the tracing layer before writing." },
      { title: "Percentiles, not averages", body: "p50, p95 and p99 latency per module and model. Averages hide the tail that drives complaints." },
      { title: "Leading indicators", body: "Rising retry rate or falling cache hit rate predicts incidents. Alerts evaluate configurable thresholds over a window." },
    ],
    limitations: ["Local SQLite span store; no OTLP export.", "No sampling: every span is stored."],
    v2: ["Quality-versus-cost drift monitoring", "Trace-to-eval replay into MissionReplay", "Regression alerts tied to release gates", "OTLP exporter"],
  },
];

export const bySlug = (slug: string) => PROJECTS.find((p) => p.slug === slug)!;
