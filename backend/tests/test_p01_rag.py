import json

import httpx
import pytest

from lab.p01_rag import index as ix
from lab.p01_rag.evaluate import answer_correct, retrieval_metrics, run_benchmark
from lab.p01_rag.generate import ABSTAIN, Answer, verify
from lab.p01_rag.index import Document, IndexConfig, chunk_document, get_index, parse_document, tokens
from lab.p01_rag.pipeline import ask
from lab.p01_rag.retrieve import RetrievalConfig, retrieve
from tests.conftest import completion


@pytest.fixture(autouse=True)
def fresh_indexes():
    ix._indexes.clear()


def test_tokens_keep_identifiers_and_parts():
    t = tokens("Lot VX-88213 peaked at 11.4 at 02:20.")
    assert {"vx-88213", "88213", "11.4", "02:20"} <= set(t)


def test_front_matter_and_email_header_extraction():
    d = parse_document("---\nid: X1\ntitle: T\naccess: restricted\n---\nbody text")
    assert (d.id, d.title, d.meta["access"], d.body) == ("X1", "T", "restricted", "body text")
    e = parse_document("From: a@b.co\nSubject: Late truck\n\nThe truck was late.", "E1")
    assert e.meta["type"] == "email" and e.title == "Late truck" and e.meta["access"] == "public"


def test_fixed_chunking_respects_size_and_overlap():
    doc = Document("D", "t", " ".join(f"w{i}" for i in range(100)), {})
    chunks = chunk_document(doc, size=30, overlap=10, strategy="fixed")
    assert all(len(c.text.split()) <= 30 for c in chunks)
    assert chunks[0].text.split()[-10:] == chunks[1].text.split()[:10]
    assert chunks[-1].text.split()[-1] == "w99"


def test_section_chunking_never_splits_a_paragraph():
    paras = [" ".join(f"p{j}w{i}" for i in range(20)) for j in range(5)]
    chunks = chunk_document(Document("D", "t", "\n\n".join(paras), {}), size=45, overlap=0, strategy="section")
    for c in chunks:
        assert len(c.text.split()) % 20 == 0  # whole paragraphs only


def test_incremental_sync_reembeds_only_changed_docs():
    cfg = IndexConfig(embedder="hash")
    idx = ix.Index(cfg)
    s1 = idx.sync(ix.load_corpus())
    assert s1["docs_reembedded"] == s1["docs_total"] == 15
    assert idx.sync(ix.load_corpus())["docs_reembedded"] == 0
    ix.save_document(Document("NEW-1", "New memo", "Depot 9 freezer F-2 failed on Tuesday.", {"access": "public", "status": "current"}))
    s3 = idx.sync(ix.load_corpus())
    assert (s3["docs_reembedded"], s3["docs_unchanged"]) == (1, 15)
    ix.delete_document("NEW-1")
    s4 = idx.sync(ix.load_corpus())
    assert s4["docs_removed"] == 1 and all(c.doc_id != "NEW-1" for c in idx.chunks)
    assert len(idx.chunks) == len(idx.vectors) == len(idx.bm25.docs)


def test_index_refuses_to_mix_embedders(monkeypatch):
    idx = ix.Index(IndexConfig(embedder="hash"))
    idx.sync(ix.load_corpus())
    idx.config.embedder = "other"
    monkeypatch.setattr(ix, "get_embedder", lambda name: type("E", (), {"name": "other-model", "dim": 384})())
    with pytest.raises(ValueError, match="refusing to mix"):
        idx.sync(ix.load_corpus())


def test_bm25_wins_exact_identifier():
    idx = get_index(IndexConfig(embedder="hash"))
    hits = retrieve(idx, "CTR-2291 service credit", RetrievalConfig(strategy="bm25", reranker="none"))
    assert hits[0].chunk.doc_id == "CTR-2291"


def test_acl_prefilter_hides_restricted_documents():
    idx = get_index(IndexConfig(embedder="hash"))
    q = "FrostLine emergency response penalty contract CTR-2291 telephone log"
    staff = retrieve(idx, q, RetrievalConfig(role="staff", k=10, context_budget=5000))
    inv = retrieve(idx, q, RetrievalConfig(role="investigator", k=10, context_budget=5000))
    assert all(h.chunk.meta["access"] == "public" for h in staff)
    assert any(h.chunk.doc_id == "CTR-2291" for h in inv)
    with pytest.raises(ValueError):
        retrieve(idx, q, RetrievalConfig(role="admin"))


def test_superseded_policy_is_demoted():
    idx = get_index(IndexConfig(embedder="hash"))
    hits = retrieve(idx, "excursion quarantine minutes policy", RetrievalConfig(k=10, context_budget=5000))
    docs = [h.chunk.doc_id for h in hits]
    assert docs.index("POL-001-v3") < docs.index("POL-001-v2")


def test_context_budget_limits_passages():
    idx = get_index(IndexConfig(embedder="hash"))
    hits = retrieve(idx, "R-17 alarm", RetrievalConfig(k=8, context_budget=100))
    assert sum(len(h.chunk.text.split()) for h in hits) <= 100 or len(hits) == 1


def test_verify_flags_invalid_citations_and_unsupported_numbers():
    idx = get_index(IndexConfig(embedder="hash"))
    hits = retrieve(idx, "peak temperature R-17", RetrievalConfig(k=2))
    good = verify(Answer("The peak reading was 11.4 degrees. [S1]", False, "t"), hits)
    assert good["citation_validity"] == 1.0
    bad = verify(Answer("The peak reading was 19.9 degrees. [S1] Something else entirely happened. [S7]", False, "t"), hits)
    assert bad["invalid_refs"] == [7] and bad["citation_validity"] == 0.5
    assert bad["sentences"][0]["numbers_supported"] is False and bad["groundedness"] == 0.0
    fake_quote = verify(Answer('The report says "the vendor was never called at all". [S1]', False, "t"), hits)
    assert fake_quote["sentences"][0]["quotes_verbatim"] is False


def test_offline_ask_abstains_on_off_topic_question():
    res = ask("What caused the power outage at the Denver depot last year?", IndexConfig(embedder="hash"))
    assert res["abstained"] and res["answer"].startswith(ABSTAIN) and res["generator"] == "gate"


def test_offline_ask_answers_with_valid_citations():
    res = ask("What service credit does CTR-2291 impose per late hour?", IndexConfig(embedder="hash"))
    assert not res["abstained"] and "2,500" in res["answer"]
    assert res["verification"]["citation_validity"] == 1.0 and res["citations"]


def test_llm_path_uses_sources_and_flags_truncation(fake_provider):
    seen = {}

    def handler(req):
        body = json.loads(req.content)
        seen["prompt"] = body["messages"][1]["content"]
        return completion("The service credit is 2,500 US dollars per late hour. [S1]")
    fake_provider(handler)
    res = ask("What service credit does CTR-2291 impose per late hour?", IndexConfig(embedder="hash"), use_llm=True)
    assert "[S1]" in seen["prompt"] and "CTR-2291" in seen["prompt"]
    assert res["generator"].startswith("llm:deepseek") and res["verification"]["citation_validity"] == 1.0

    fake_provider(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "The cred"}, "finish_reason": "length"}], "usage": {}}))
    res = ask("What service credit does CTR-2291 impose per late hour?", IndexConfig(embedder="hash"), use_llm=True)
    assert res["usage"]["truncated"] is True and res["usage"]["cost_usd"] is None


def test_llm_abstention_is_recognised(fake_provider):
    fake_provider(lambda r: completion(f"{ABSTAIN}: the sources do not give an expiry date."))
    res = ask("What is the expiry date of lot VX-88213?", IndexConfig(embedder="hash"), use_llm=True)
    assert res["abstained"] is True


def test_llm_requested_without_provider_fails_loudly():
    from lab.core.providers import ProviderUnavailable
    with pytest.raises(ProviderUnavailable):
        ask("anything", use_llm=True)


def test_retrieval_metrics_math():
    m = retrieval_metrics(["A", "B", "C"], ["B", "D"], k=3)
    assert m["recall"] == 0.5 and m["mrr"] == 0.5
    assert retrieval_metrics(["X"], ["A"], k=1) == {"recall": 0.0, "mrr": 0.0, "ndcg": 0.0}
    assert answer_correct("Call at 02:20, SLA four hours", [["02:20"], ["4 hours", "four hours"]])
    assert not answer_correct("Call at 02:20", [["02:20"], ["4 hours"]])


def test_benchmark_runs_offline_and_reports_split_metrics():
    res = run_benchmark(IndexConfig(embedder="hash"), RetrievalConfig())
    assert res["n"] == 24
    assert 0 < res["retrieval"]["recall@5"] <= 1 and 0 < res["retrieval"]["mrr"] <= 1
    assert res["answers"]["abstention_on_unanswerable"] >= 0.5
    assert res["answers"]["citation_validity"] == 1.0  # extractive generator only cites provided sources
