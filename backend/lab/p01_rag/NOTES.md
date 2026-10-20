# Notes: RAG, explained simply

## The one idea

A language model only knows what it saw during training. It has never read *your* documents, and it doesn't know what changed last week. RAG gives it an **open-book exam**: before answering, look up the relevant pages and answer from them.

> Training a model = making a student memorise the textbook.
> RAG = letting the student bring the textbook into the exam and cite page numbers.

Updating the "textbook" (your documents) is cheap. Re-training the student is expensive. That's why RAG is the default way to use private or changing knowledge.

## The pieces, in plain words

**Chunking.** Documents are too long to paste whole, so we cut them into pieces of roughly 100 to 300 words.
- *Fixed* chunking cuts every N words, even mid-sentence.
- *Section-aware* chunking cuts between paragraphs and headings, so a fact is never split in half.

**Keyword search (BM25).** Scores a chunk by how many of your query words it contains, giving more weight to rare words. Great for exact IDs like `CTR-2291` or `VX-88213`.

**Vector search (embeddings).** Turns text into a list of numbers (a "vector") so that texts with similar *meaning* get similar numbers. "Which fridge broke?" can find "reefer unit R-17 failed" even with no shared words. Weak with exact codes.

**Hybrid + RRF (reciprocal rank fusion).** Run both searches and merge the two ranked lists. A chunk scores `1/(60 + its rank)` in each list, and the scores are added. We combine *ranks*, not raw scores, because BM25 scores and cosine similarities are on completely different scales.

**Reranking.** A second, more careful pass over the top ~30 candidates to pick the best 5.

**Context budget.** The model can only read so much, and more text means more cost and more distraction. We stop adding passages once a word budget is used.

**Access control (ACL).** Some documents are restricted. They're filtered out *before* ranking, so they can never leak into a prompt or onto the screen. Never rely on telling the model "don't mention X".

**Freshness.** Policy version 2 says 60 minutes and version 3 says 30. Both match the question! We tag every chunk with its status and date and push superseded documents down.

**Abstention.** Saying "I don't have enough evidence" is a *feature*. We use two layers:
1. **Evidence gate (before the model):** if nothing retrieved is on-topic, refuse immediately and save the cost.
2. **The model's own judgement:** if the passages are on-topic but don't contain the fact, a good model says `INSUFFICIENT_EVIDENCE`.

Layer 1 can't catch "on-topic but the fact is missing". q21 asks for the vaccine lot's *expiry date*: the passages talk about that lot, so the gate lets it through, yet no document states the date. The offline extractive generator then grabs a sentence about the lot and answers wrongly. DeepSeek correctly refuses. This is exactly why retrieval scores alone can't decide answerability.

**Citations and verification.** Every sentence must cite `[S#]`. We then check, with no AI involved:
- Does `S#` exist? A model citing `[S9]` when only 5 sources were given is fabricating.
- Do the sentence's numbers appear in the cited passage? Numbers are where fabrication hurts most.
- Does a "quoted" phrase appear word for word?

## Measuring it: two separate report cards

| Retrieval report card | Answer report card |
|---|---|
| **Recall@k:** of the documents that hold the evidence, how many made the top k? | **Accuracy:** did the answer contain the required facts? |
| **MRR:** how high was the first right document? (1st place = 1.0, 2nd = 0.5) | **Abstention:** did it refuse the unanswerable ones? |
| **nDCG:** like MRR, but rewards getting *all* the right documents near the top | **Citation validity / groundedness** |

Keep them separate. If the answer is wrong, the retrieval card tells you whether the right page was never found (fix search) or was found but misused (fix generation).

## Lessons this lab actually produced

1. **Our evidence gate was too strict at first.** It checked only keyword overlap, so paraphrased questions were refused. Adding a meaning-based check fixed it, and DeepSeek accuracy went from 80% to 95%.
2. **Reasoning models can run out of tokens.** One answer stopped mid-word because hidden "thinking" used up the token budget. We now raise the budget and flag `finish_reason == "length"`.
3. **Word-overlap checks are a floor, not a ceiling.** They correctly catch invented numbers, but they also flag correct *calculated* claims ("5 hours 20 minutes later") because that phrase isn't in any document.
4. **On a small corpus, retrieval is easy; generation is the hard part.** Retrieval scored 97.5% MRR while the offline generator reached only 75% accuracy.

## Glossary

| Term | Meaning |
|---|---|
| Embedding | A list of numbers representing a text's meaning |
| Cosine similarity | How closely two embeddings point the same way (1 = identical meaning) |
| Top-k | The k best-ranked passages |
| Hallucination | A confident statement not supported by any source |
| Grounded | Every claim can be traced to a provided source |
| Incremental indexing | Re-processing only documents whose content changed (detected with a hash) |

## Interview question (from the PDF)

> *Design Q&A over 50,000 internal documents, updated weekly.*

1. **Ingestion:** layout-aware chunking; metadata (owner, date, version, access level) on every chunk.
2. **Retrieval:** hybrid BM25 + dense with RRF, then a cross-encoder rerank of the top 50 to 100.
3. **Access control:** filter before ranking, per user.
4. **Weekly refresh:** content-hash every document and re-embed only what changed. Version the embedding model; if it changes, re-embed everything.
5. **Generation:** a context-only prompt, mandatory citations, abstain when evidence is thin, prefer current documents.
6. **Measure:** a labelled query set; retrieval metrics separate from answer metrics; monitor both after launch.
