from ingest import load_chunks
from retrieve import BM25Index, DenseIndex, hybrid_search, rerank, rrf, search

chunks = load_chunks()
index = DenseIndex(chunks)
bm25 = BM25Index(chunks)


def test_bm25_needs_shared_words_and_finds_exact_ones():
    assert bm25.search("how long until I get my money back?") == []  # no word in common with any chunk
    assert bm25.search("inactive 24 months", k=1)[0][0].id == "account-help#0"


def test_rrf_rewards_agreement():
    a, b, c = chunks[:3]
    assert rrf([a, b], [c, b])[0][0] == b  # b is 2nd in both lists, beats a and c (1st in only one)


def test_hybrid_fixes_dense_near_tie():
    # dense alone ranks account-help#1 first for this one (see retrieve.py demo)
    assert hybrid_search(index, bm25, "can I change my email?", k=1)[0][0].id == "account-help#0"


def top_id(q):
    return index.search(q, k=1)[0][0].doc


def test_meaning_match_without_shared_words():
    # "money back" never appears in the doc, which says "returned to the original payment method"
    assert top_id("how long until I get my money back?") == "refund-policy-current"


def test_other_topics():
    assert top_id("can I change my email?") == "account-help"
    assert top_id("which countries do you deliver to?") == "shipping"


def test_rerank_fixes_24_months():
    # hybrid alone puts order-tracking#0 first for this query
    assert search(index, bm25, "24 months", k=1)[0][0].id == "account-help#0"


def test_retired_policy_sorted_last():
    old = next(c for c in chunks if c.doc == "refund-policy-old")
    new = next(c for c in chunks if c.doc == "refund-policy-current")
    assert [c.doc for c, _ in rerank("refund within 14 days", [old, new], k=2)][0] == "refund-policy-current"
