"""Grounded generation, abstention and citation verification.

Two generators share one contract (answer text with [S#] citations, or an abstention):
- llm:        DeepSeek/Groq with a context-only prompt (when a provider is configured)
- extractive: offline; picks the source sentences that best cover the question. It cannot
              paraphrase or reason across documents, which the benchmark makes visible.
"""
import re
from dataclasses import dataclass, field

from lab.core import providers, tracing

from .index import Index, tokens
from .retrieve import Hit, idf_coverage

PROMPT_VERSION = "rag-v2"
ABSTAIN = "INSUFFICIENT_EVIDENCE"
SYSTEM = f"""You answer questions for an internal investigation using ONLY the numbered sources provided.
Rules:
- Cite every factual sentence with the source tags it relies on, like [S1] or [S2][S3].
- If the sources do not contain the answer, reply exactly: {ABSTAIN}: <one sentence on what is missing>.
- If sources conflict, say so, cite both, and prefer documents marked status=current over superseded or unverified ones.
- Be concise: at most 4 sentences. Do not use outside knowledge."""


@dataclass
class Answer:
    text: str
    abstained: bool
    generator: str
    reason: str = ""
    citations: list = field(default_factory=list)
    verification: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    prompt: list = field(default_factory=list)


_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")


def canonical(text: str) -> str:
    """Normalise typographic Unicode some models emit (gpt-oss writes `R\u201117`, `30\u202fminutes`,
    `\u3010S1\u3011`). Without this, correct answers fail string checks and citations go unparsed."""
    import unicodedata
    text = unicodedata.normalize("NFKC", text).translate(_DASHES)
    return re.sub(r"[\u3010\uff3b]\s*(S\d+)\s*[\u3011\uff3d]", r"[\1]", text)


def build_messages(question: str, hits: list[Hit]) -> list[dict]:
    blocks = []
    for n, h in enumerate(hits, 1):
        m = h.chunk.meta
        blocks.append(f"[S{n}] doc={h.chunk.doc_id} title=\"{h.chunk.title}\" date={m.get('date')} "
                      f"status={m.get('status')} type={m.get('type')}\n{h.chunk.text}")
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Sources:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"}]


# Dense threshold is only meaningful for the embedder it was calibrated on (cosines from
# different embedders are not comparable). Calibrated on benchmark.json: every answerable
# question has max cosine >= 0.52; off-topic ones (q22, q23) sit at 0.41 and 0.18.
# Caveat: tuned on the same 24 items it is evaluated on; a held-out set is the V2 fix.
DENSE_GATE = {"sentence-transformers/all-MiniLM-L6-v2": 0.50}


def evidence_gate(index: Index, question: str, hits: list[Hit], min_coverage: float) -> tuple[bool, float, float]:
    """Cheap pre-generation abstention: refuse without spending a model call when no retrieved
    passage covers enough of the question, lexically (idf-weighted term coverage) OR semantically
    (dense cosine, catches paraphrases). Detects missing *topics* only; an on-topic question
    about an absent fact (q21, q24) passes and must be caught by the generator itself."""
    cov = max((idf_coverage(index, question, f"{h.chunk.title} {h.chunk.text}") for h in hits), default=0.0)
    dense = max((h.scores.get("dense", 0.0) for h in hits), default=0.0)
    dense_min = DENSE_GATE.get(index.embedder_name)
    ok = cov >= min_coverage or (dense_min is not None and dense >= dense_min)
    return ok, cov, dense


_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def extractive(index: Index, question: str, hits: list[Hit], max_sentences: int = 2, min_score: float = 0.15) -> Answer:
    """Abstention is the evidence gate's job; here `min_score` is only a floor against picking
    an unrelated sentence. A second sentence is added only if it scores >= 70% of the best."""
    cands = []
    for n, h in enumerate(hits, 1):
        # Terms already satisfied by the document title (e.g. "CTR-2291") located the document;
        # they should not also decide which sentence inside it answers the question.
        title_terms = set(tokens(h.chunk.title))
        focus = " ".join(t for t in tokens(question) if t not in title_terms) or question
        for s in _SENT.split(h.chunk.text):
            s = s.strip()
            if len(s.split()) >= 3 and not s.startswith("#"):
                cands.append((idf_coverage(index, focus, s), n, s))
    cands.sort(key=lambda x: -x[0])
    chosen = [c for c in cands[:max_sentences] if c[0] >= max(min_score, 0.7 * cands[0][0])] if cands else []
    if not chosen:
        return Answer(f"{ABSTAIN}: no source sentence covers the question.", True, "extractive",
                      reason=f"best sentence coverage {cands[0][0]:.2f} < {min_score}" if cands else "no passages")
    text = " ".join(f"{s.rstrip('.')}. [S{n}]" for _, n, s in chosen)
    return Answer(text, False, "extractive")


def llm(question: str, hits: list[Hit], provider: str | None) -> Answer:
    msgs = build_messages(question, hits)
    # Reasoning models spend part of max_tokens on hidden reasoning, so the budget is generous;
    # finish_reason == "length" is surfaced as a truncation failure rather than a normal answer.
    r = providers.chat(msgs, provider=provider, temperature=0.0, max_tokens=1500, module="rag",
                       prompt_version=PROMPT_VERSION)
    text = canonical(r.text.strip())
    truncated = r.finish_reason == "length"
    return Answer(text, text.startswith(ABSTAIN), f"llm:{r.provider}/{r.model}", prompt=msgs,
                  reason="answer truncated by max_tokens" if truncated else "",
                  usage={"finish_reason": r.finish_reason, "truncated": truncated,
                         "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                         "cached_tokens": r.cached_tokens, "cost_usd": r.cost_usd, "cost_source": r.cost_source,
                         "latency_ms": round(r.latency_ms, 1)})


_CITE = re.compile(r"\[S(\d+)\]")
# Answer sentences: split after ".", "!" or "?" unless a citation follows, or after a citation
# that is followed by a new capitalised sentence. Keeps "fact. [S1]" together.
_ANSWER_SENT = re.compile(r"(?<=[.!?])\s+(?!\[S\d)|(?<=\])\s+(?=[A-Z])|\n+")
_NUM = re.compile(r"\d+(?:[.,:]\d+)*")


def verify(answer: Answer, hits: list[Hit], support_threshold: float = 0.6) -> dict:
    """Deterministic checks, no model involved:
    - citation validity: every [S#] must point at a passage that was actually provided.
    - quote check: any "quoted text" must appear verbatim in a cited passage.
    - groundedness: each sentence's content words must mostly appear in its cited passages,
      and every number in it must appear there too (numbers are where fabrication hurts most).
    This is lexical entailment, a floor; an NLI model is the V2 upgrade."""
    if answer.abstained:
        return {"abstained": True}
    cited = [int(n) for n in _CITE.findall(answer.text)]
    valid = [n for n in cited if 1 <= n <= len(hits)]
    sentences = [s for s in _ANSWER_SENT.split(answer.text) if _CITE.sub("", s).strip(" .")]
    per = []
    for s in sentences:
        refs = [int(n) for n in _CITE.findall(s) if 1 <= int(n) <= len(hits)]
        clean = _CITE.sub("", s).strip()
        pool = " ".join(hits[n - 1].chunk.text for n in refs)
        words = set(tokens(clean))
        recall = len(words & set(tokens(pool))) / len(words) if words else 1.0
        nums = _NUM.findall(clean)
        nums_ok = all(x in pool or x.replace(",", "") in pool.replace(",", "") for x in nums)
        quotes_ok = all(q in pool for q in re.findall(r'"([^"]{6,})"', clean))
        per.append({"sentence": clean, "cites": refs, "word_support": round(recall, 2), "numbers_supported": nums_ok,
                    "quotes_verbatim": quotes_ok,
                    "supported": bool(refs) and recall >= support_threshold and nums_ok and quotes_ok})
    supported = sum(p["supported"] for p in per)
    return {"abstained": False, "citations": len(cited), "valid_citations": len(valid),
            "citation_validity": round(len(valid) / len(cited), 3) if cited else 0.0,
            "invalid_refs": sorted(set(cited) - set(valid)),
            "groundedness": round(supported / len(per), 3) if per else 0.0, "sentences": per}


def answer(index: Index, question: str, hits: list[Hit], *, use_llm: bool, provider: str | None = None,
           min_coverage: float = 0.35) -> Answer:
    with tracing.span("rag.generate", kind="generation", module="rag", question=question, use_llm=use_llm) as sp:
        ok, cov, dense = evidence_gate(index, question, hits, min_coverage)
        if not hits or not ok:
            a = Answer(f"{ABSTAIN}: retrieved passages do not cover the question.", True, "gate",
                       reason=f"lexical coverage {cov:.2f} < {min_coverage} and dense similarity {dense:.2f} "
                              f"< {DENSE_GATE.get(index.embedder_name, 'n/a')}")
        elif use_llm:
            a = llm(question, hits, provider)
        else:
            a = extractive(index, question, hits)
        a.verification = verify(a, hits)
        a.citations = sorted(set(int(n) for n in _CITE.findall(a.text)))
        sp.set(answer=a.text, abstained=a.abstained, generator=a.generator, coverage=round(cov, 3),
               groundedness=a.verification.get("groundedness"))
        if a.verification.get("invalid_refs"):
            sp.fail("invalid_citation", f"cited non-existent sources {a.verification['invalid_refs']}")
        return a
