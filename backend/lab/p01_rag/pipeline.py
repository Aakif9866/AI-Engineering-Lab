"""End-to-end ask(): index -> retrieve -> gate -> generate -> verify, all inside one trace."""
from dataclasses import asdict

from lab.core import providers, tracing

from .generate import answer
from .index import IndexConfig, get_index
from .retrieve import RetrievalConfig, retrieve


def ask(question: str, icfg: IndexConfig | None = None, rcfg: RetrievalConfig | None = None, *,
        use_llm: bool = False, provider: str | None = None, min_coverage: float = 0.35) -> dict:
    icfg, rcfg = icfg or IndexConfig(), rcfg or RetrievalConfig()
    if use_llm and not providers.available(provider or providers.default_provider()):
        raise providers.ProviderUnavailable("LLM generation requested but no provider is configured")
    with tracing.span("rag.ask", kind="request", module="rag", question=question,
                      strategy=rcfg.strategy, chunk_size=icfg.chunk_size) as sp:
        index = get_index(icfg)
        hits = retrieve(index, question, rcfg)
        a = answer(index, question, hits, use_llm=use_llm, provider=provider, min_coverage=min_coverage)
        return {"trace_id": sp.trace_id, "question": question,
                "index_config": asdict(icfg), "retrieval_config": asdict(rcfg), "embedder": index.embedder_name,
                "hits": [h.as_dict(n) for n, h in enumerate(hits, 1)],
                "answer": a.text, "abstained": a.abstained, "generator": a.generator, "reason": a.reason,
                "citations": a.citations, "verification": a.verification, "usage": a.usage,
                "prompt": a.prompt}
