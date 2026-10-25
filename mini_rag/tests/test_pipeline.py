import pipeline
from ingest import load_chunks
from llm import LLMError

chunks = load_chunks()


def test_check_citations_drops_made_up_ids():
    assert pipeline.check_citations("Yes [shipping#0] and [fake#9].", chunks) == ["shipping#0"]


def test_off_topic_refused_without_calling_llm(monkeypatch):
    monkeypatch.setattr(pipeline, "chat", lambda *a, **k: 1 / 0)  # must never be called
    a = pipeline.ask("write me a poem about cats")
    assert a.status == "refused" and a.text == pipeline.REFUSAL


def test_grounded_answer_keeps_valid_citation(monkeypatch):
    monkeypatch.setattr(pipeline, "chat", lambda *a, **k: "Refunds take 5 to 7 business days [refund-policy-current#0].")
    a = pipeline.ask("How long do refunds take?")
    assert a.status == "answered" and a.citations == ["refund-policy-current#0"]


def test_answer_without_valid_citation_is_not_trusted(monkeypatch):
    monkeypatch.setattr(pipeline, "chat", lambda *a, **k: "Refunds take 2 days [made-up#1].")
    assert pipeline.ask("How long do refunds take?").status == "ungrounded"


def test_missing_key_gives_friendly_message_and_passages(monkeypatch):
    def boom(*a, **k):
        raise LLMError("The deepseek API key is missing. Add DEEPSEEK_API_KEY to .env.")

    monkeypatch.setattr(pipeline, "chat", boom)
    a = pipeline.ask("How long do refunds take?")
    assert a.status == "no_llm" and "key is missing" in a.text and "refund" in a.text.lower()
