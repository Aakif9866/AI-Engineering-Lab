import json

import httpx
import pytest

from lab.core.db import db
from lab.p03_cache import gateway as g
from lab.p03_cache.gateway import CacheConfig, ask, classify_scope, edit_article
from lab.p03_cache.workload import labelled_pairs, make_workload, run_mode, threshold_sweep
from tests.conftest import completion

EXACT = CacheConfig(mode="exact")


@pytest.fixture(autouse=True)
def fresh_kb_index():
    g._kb_index.clear()


def test_scope_classification():
    assert classify_scope("When does my plan renew?") == "user"
    assert classify_scope("How do I reset my password?") == "global"  # 'my', but the answer is the same for everyone
    assert classify_scope("Is Nimbus down right now?") == "volatile"
    assert classify_scope("How much does the Pro plan cost?") == "global"


def test_exact_hit_after_normalisation():
    a = ask("How much does the Pro plan cost?", cfg=EXACT)
    b = ask("  how much does the PRO plan cost ", cfg=EXACT)
    assert a["event"] == "miss" and b["event"] == "hit_exact" and b["answer"] == a["answer"]
    assert b["cost_usd"] == 0 and b["cost_avoided_usd"] == a["cost_usd"]


@pytest.mark.parametrize("change", [{"prompt_version": "faq-v2"}, {"temperature": 0.7}])
def test_config_changes_cannot_reuse_entries(change):
    ask("How do I export my notes?", cfg=EXACT)
    assert ask("How do I export my notes?", cfg=CacheConfig(mode="exact", **change))["event"] == "miss"


def test_namespaces_are_isolated():
    ask("How do I export my notes?", namespace="tenant-a", cfg=EXACT)
    assert ask("How do I export my notes?", namespace="tenant-b", cfg=EXACT)["event"] == "miss"


def test_personal_answers_never_cross_users():
    a = ask("When does my plan renew?", user_id="u1", cfg=EXACT, label="my_renewal@u1")
    b = ask("When does my plan renew?", user_id="u2", cfg=EXACT, label="my_renewal@u2")
    assert b["event"] == "miss" and "15 January 2027" in b["answer"] and "3 November 2026" in a["answer"]
    assert ask("When does my plan renew?", user_id="u1", cfg=EXACT, label="my_renewal@u1")["event"] == "hit_exact"


def test_without_scoping_the_leak_is_detected_as_a_false_hit():
    unsafe = CacheConfig(mode="exact", scope_aware=False)
    ask("When does my plan renew?", user_id="u1", namespace="x", cfg=unsafe, label="my_renewal@u1")
    leak = ask("When does my plan renew?", user_id="u2", namespace="x", cfg=unsafe, label="my_renewal@u2")
    assert leak["event"] == "hit_exact" and leak["correct"] == 0 and "3 November 2026" in leak["answer"]


def test_volatile_questions_bypass_and_are_never_stored():
    for _ in range(2):
        assert ask("Is Nimbus down right now?", cfg=EXACT)["event"] == "bypass"
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0] == 0


def test_ttl_expiry_evicts():
    cfg = CacheConfig(mode="exact", ttl_s=60)
    ask("Does Nimbus work offline?", cfg=cfg, now=1000.0)
    assert ask("Does Nimbus work offline?", cfg=cfg, now=1059.0)["event"] == "hit_exact"
    r = ask("Does Nimbus work offline?", cfg=cfg, now=1061.0)
    assert r["event"] == "miss" and r["evicted"][0]["reason"] == "ttl_expired"


def test_dependency_change_prevents_stale_answer():
    first = ask("How much does the Pro plan cost?", cfg=EXACT, label="pricing_pro")
    assert "$8" in first["answer"]
    edit_article("pricing_pro", "The Pro plan costs $10 per month.", purge=False)  # lazy path: lookup-time check
    r = ask("How much does the Pro plan cost?", cfg=EXACT, label="pricing_pro")
    assert r["event"] == "miss" and "$10" in r["answer"] and r["evicted"][0]["reason"] == "dependency_changed"


def test_eager_invalidation_purges_only_dependent_entries():
    ask("How much does the Pro plan cost?", cfg=EXACT)
    ask("Does Nimbus work offline?", cfg=EXACT)
    assert edit_article("pricing_pro", "The Pro plan costs $12 per month.")["purged_entries"] == 1
    assert ask("Does Nimbus work offline?", cfg=EXACT)["event"] == "hit_exact"


def test_stale_answer_is_served_and_flagged_when_dependency_check_is_off():
    unsafe = CacheConfig(mode="exact", dependency_check=False)
    ask("How much does the Pro plan cost?", namespace="y", cfg=unsafe, label="pricing_pro")
    edit_article("pricing_pro", "The Pro plan costs $10 per month.", purge=False)
    r = ask("How much does the Pro plan cost?", namespace="y", cfg=unsafe, label="pricing_pro")
    assert r["event"] == "hit_exact" and "$8" in r["answer"] and r["correct"] == 0


def test_semantic_threshold_hit_and_rejected_match():
    ask("How do I export my notes?", cfg=CacheConfig(mode="semantic", threshold=0.5))
    hit = ask("how do I export my notes please", cfg=CacheConfig(mode="semantic", threshold=0.5))
    assert hit["event"] == "hit_semantic" and 0.5 <= hit["similarity"] < 1
    strict = ask("how do I export all my notes", cfg=CacheConfig(mode="semantic", threshold=0.999, reject_band=0.5))
    assert strict["event"] == "rejected_match" and strict["matched_question"]
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM cache_events WHERE event='rejected_match'").fetchone()[0] == 1


def test_upstream_error_is_not_cached(fake_provider):
    fake_provider(lambda r: httpx.Response(500, text="boom"))
    cfg = CacheConfig(mode="exact", provider="deepseek")
    assert ask("Does Nimbus work offline?", cfg=cfg)["event"] == "upstream_error"
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0] == 0


def test_real_provider_usage_is_recorded_and_reused(fake_provider):
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        return completion("Yes, recently opened notes work offline.", prompt_tokens=300, completion_tokens=20, cached=256)
    fake_provider(handler)
    cfg = CacheConfig(mode="exact", provider="deepseek")
    a = ask("Does Nimbus work offline?", cfg=cfg)
    b = ask("Does Nimbus work offline?", cfg=cfg)
    assert len(calls) == 1 and a["cost_kind"] == "actual" and a["cached_tokens"] == 256
    assert b["event"] == "hit_exact" and b["cost_avoided_usd"] == pytest.approx(a["cost_usd"])
    assert "offline_mode" in calls[0]["messages"][1]["content"]  # grounded on the routed FAQ article


def test_workload_is_deterministic_and_modes_measure_correctness():
    wl = make_workload(120, seed=3)
    assert wl == make_workload(120, seed=3)
    off = run_mode(wl, CacheConfig(mode="off"), "off")
    exact = run_mode(wl, CacheConfig(mode="exact"), "exact")
    leaky = run_mode(wl, CacheConfig(mode="exact", scope_aware=False), "leaky")
    assert off["hit_rate"] == 0 and off["upstream_calls"] == 120
    assert exact["hit_rate"] > 0 and exact["false_hits"] == 0
    assert leaky["false_hits"] > 0  # cross-user reuse is caught by the correctness check


def test_threshold_sweep_shape():
    s = threshold_sweep()
    assert s["positives"] == 11 * 6 and s["pairs"] == len(labelled_pairs())
    assert all(0 <= r["precision"] <= 1 for r in s["rows"])
    fps = [r["false_positives"] for r in s["rows"]]
    assert fps == sorted(fps, reverse=True)  # raising the threshold never adds false positives
