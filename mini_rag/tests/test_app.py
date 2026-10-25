from streamlit.testing.v1 import AppTest

import pipeline
from guardrails import RateLimiter


def test_app_renders_and_answers(monkeypatch):
    monkeypatch.setattr(pipeline, "chat", lambda *a, **k: "Standard shipping costs 4.99 USD [shipping#0].")
    monkeypatch.setattr(pipeline, "limiter", RateLimiter())
    at = AppTest.from_file("../app.py", default_timeout=60).run()
    assert not at.exception
    at.chat_input[0].set_value("How much is standard shipping?").run()
    assert not at.exception
    assert "4.99" in at.chat_message[1].markdown[0].value
