import json

import pytest

from lab.p02_finetune import data
from lab.p02_finetune.evaluate import OOD, rules_predict
from lab.p02_finetune.schema import Decision, aggregate, business_errors, parse_output, score, token_f1

GOLD = {"change_type": "bug_fix", "component": "auth", "priority": "P0", "customer_impact": "high",
        "requires_migration": False, "owner_team": "platform", "summary": "Fix SSO login error"}


def test_generation_is_deterministic_and_seed_sensitive():
    assert data.generate(50, seed=1) == data.generate(50, seed=1)
    assert data.generate(50, seed=1) != data.generate(50, seed=2)


def test_cleaning_catches_every_injected_problem():
    raw = data.generate(400, seed=3)
    kept, rejected = data.clean(raw)
    injected_bad = {r["id"] for r in raw if r["injected"] and "duplicate" not in r["injected"]}
    assert injected_bad and injected_bad <= {r["id"] for r in rejected}
    reasons = {r["reject_reason"].split(":")[0] for r in rejected}
    assert {"schema", "business_rule", "exact_duplicate", "near_duplicate"} <= reasons
    for r in kept:  # everything kept is schema- and rule-valid
        assert not business_errors(Decision.model_validate(r["label"]))
    norms = [data.normalise(r["request"]) for r in kept]
    assert len(norms) == len(set(norms))


def test_splits_are_reproducible_disjoint_and_leakage_free():
    rep1 = data.build(300, seed=5)
    splits1 = {s: [r["request"] for r in data.load(s)] for s in ("train", "val", "test")}
    rep2 = data.build(300, seed=5)
    assert rep1["dataset_hash"] == rep2["dataset_hash"]
    assert splits1 == {s: [r["request"] for r in data.load(s)] for s in ("train", "val", "test")}
    sets = {s: {data.normalise(x) for x in v} for s, v in splits1.items()}
    assert not (sets["train"] & sets["test"]) and not (sets["train"] & sets["val"])
    # the split depends on content only, so an example cannot move between splits when others change
    assert data.split_of(splits1["test"][0]) == "test"


def test_parse_output_is_lenient_on_prose_strict_on_object():
    ok = parse_output('Sure! Here it is: ' + json.dumps(GOLD) + " hope that helps")
    assert ok["json_valid"] and ok["schema_valid"]
    bad_enum = parse_output(json.dumps({**GOLD, "priority": "P9"}))
    assert bad_enum["json_valid"] and not bad_enum["schema_valid"] and "priority" in bad_enum["error"]
    extra = parse_output(json.dumps({**GOLD, "confidence": 0.9}))
    assert not extra["schema_valid"]  # extra keys are forbidden: downstream parsers depend on the exact shape
    assert parse_output("no json here")["error"] == "no JSON object in output"
    assert not parse_output('{"change_type": "bug_fix",')["json_valid"]


def test_per_field_scoring_and_aggregate():
    wrong_prio = json.dumps({**GOLD, "priority": "P1"})
    s = score(wrong_prio, GOLD)
    assert s["per_field"]["priority"] is False and s["per_field"]["component"] is True and not s["exact_all_fields"]
    agg = aggregate([score(json.dumps(GOLD), GOLD), s, score("garbage", GOLD)])
    assert agg["json_valid"] == pytest.approx(2 / 3) and agg["exact_all_fields"] == pytest.approx(1 / 3)
    assert agg["per_field"]["priority"] == pytest.approx(1 / 3)
    assert token_f1("Fix SSO login error", "fix sso login error") == 1.0


def test_ood_slice_labels_are_valid():
    for x in OOD:
        assert not business_errors(Decision.model_validate(x["label"])), x["id"]


def test_rules_baseline_always_emits_schema_valid_json():
    for x in OOD + data.generate(30, seed=9):
        if x["request"].strip():
            assert parse_output(rules_predict(x["request"]))["schema_valid"]


torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
pytest.importorskip("peft")


def test_lora_training_changes_only_adapter_weights():
    """Real training on a tiny randomly initialised Llama: proves the mechanism without downloads."""
    from lab.p02_finetune import model as M
    torch.manual_seed(0)
    cfg = transformers.LlamaConfig(vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                                   num_attention_heads=4, num_key_value_heads=4, max_position_embeddings=64)
    base = transformers.LlamaForCausalLM(cfg)
    before = {n: p.detach().clone() for n, p in base.named_parameters()}
    model, info = M.attach_lora(base, r=4, alpha=8, dropout=0.0)
    # 4 target projections x 2 layers, each LoRA adds A (r x 32) + B (32 x r)
    assert info["trainable_params"] == 2 * 4 * (4 * 32 + 32 * 4)
    assert info["adapted_modules"] == 8 and info["trainable_pct"] < 10
    ids = torch.randint(0, 64, (4, 12))
    labels = ids.clone()
    labels[:, :6] = -100  # prompt masked
    batch = {"input_ids": ids, "labels": labels, "attention_mask": torch.ones_like(ids)}
    hist = M.train_loop(model, [batch], epochs=30, lr=5e-3)
    assert hist[-1]["loss"] < hist[0]["loss"]
    for n, p in model.named_parameters():
        if "lora_" in n:
            if "lora_B" in n:
                assert p.abs().sum() > 0  # B starts at zero, so non-zero proves it trained
        else:
            orig = n.replace("base_model.model.", "").replace(".base_layer", "")
            assert torch.equal(p, before[orig]), f"frozen weight changed: {n}"


def test_encode_masks_prompt_tokens():
    from lab.p02_finetune import model as M

    class Tok:
        eos_token_id = 0
        def apply_chat_template(self, msgs, tokenize, add_generation_prompt):
            return "P" * 5
        def __call__(self, text, add_special_tokens=False):
            return {"input_ids": [ord(c) % 50 + 1 for c in text]}
    enc = M.encode_example(Tok(), "req", {"a": 1})
    n_prompt = 5
    assert enc["labels"][:n_prompt] == [-100] * n_prompt
    assert enc["labels"][n_prompt:] == enc["input_ids"][n_prompt:] and enc["labels"][-1] == 0


def test_train_run_end_to_end_writes_adapter_and_honest_metadata(monkeypatch):
    """Full train.run() path (metadata, frozen-weight probe, save) on a tiny model: no download."""
    from lab.core.config import var_dir
    from lab.p02_finetune import model as M
    from lab.p02_finetune import train as T

    class Tok:
        eos_token_id, pad_token_id, padding_side = 1, 0, "left"
        def apply_chat_template(self, msgs, tokenize, add_generation_prompt):
            return "".join(m["content"] for m in msgs)[-40:]
        def __call__(self, text, add_special_tokens=False):
            return {"input_ids": [2 + ord(c) % 60 for c in text[:200]]}

    cfg = transformers.LlamaConfig(vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                                   num_attention_heads=4, num_key_value_heads=4, max_position_embeddings=512)
    monkeypatch.setattr(M, "load_base", lambda dev=None: (Tok(), transformers.LlamaForCausalLM(cfg)))
    data.build(150, seed=1)
    meta = T.run("t1", epochs=1, max_train=16, batch_size=8)
    assert meta["weight_change_evidence"]["base_weight_unchanged"] is True
    assert meta["weight_change_evidence"]["lora_B_mean_abs_after"] > 0
    assert meta["frozen_params"] + meta["trainable_params"] == meta["total_params"]
    assert (var_dir("p02", "runs", "t1") / "adapter" / "adapter_config.json").exists()
    assert json.loads((var_dir("p02", "runs", "t1") / "status.json").read_text())["state"] == "done"


def test_constrained_decoding_is_schema_valid_even_for_a_random_model():
    from lab.p02_finetune import model as M
    try:
        tok = transformers.AutoTokenizer.from_pretrained(M.BASE_MODEL, local_files_only=True)
    except Exception:
        pytest.skip("SmolLM2 tokenizer not cached")
    tok.pad_token = tok.pad_token or tok.eos_token
    torch.manual_seed(0)
    cfg = transformers.LlamaConfig(vocab_size=len(tok), hidden_size=16, intermediate_size=32, num_hidden_layers=1,
                                   num_attention_heads=2, num_key_value_heads=2, max_position_embeddings=1024)
    rand = transformers.LlamaForCausalLM(cfg)
    out = M.constrained_generate(rand, tok, M.prompt_text(tok, "the CSV export is slow", M.FT_SYSTEM), max_summary_tokens=8)
    r = parse_output(out)
    # A random model's summary may be too short to satisfy min_length; every enum/bool field must be valid.
    obj = json.loads(out)
    assert r["json_valid"] and list(obj) == [n for n, _ in M.field_spec()]
    for name, choices in M.field_spec():
        if choices is not None:
            assert obj[name] in choices
