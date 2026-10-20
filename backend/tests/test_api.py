"""HTTP-level integration tests: the same routes the frontend uses."""
import os

import pytest
from fastapi.testclient import TestClient

from lab.api import app
from lab.p01_rag import index as ix


@pytest.fixture
def client():
    ix._indexes.clear()
    return TestClient(app)


def test_status_never_exposes_keys(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-live0000000000000000000")
    body = client.get("/api/status").text
    assert "sk-live" not in body and '"offline_forced":true' in body


def test_rag_ask_ingest_delete_roundtrip(client):
    r = client.post("/api/rag/ask", json={"question": "Which lot was affected?"})  # warms the default index
    assert r.status_code == 200 and r.json()["hits"] and r.json()["trace_id"]
    raw = "From: ops@meridian.example\nSubject: Depot 9 freezer\n\nFreezer F-2 at Depot 9 failed on Tuesday."
    r = client.post("/api/rag/ingest", json={"raw": raw, "id": "D9-NOTE"})
    assert r.status_code == 200 and r.json()["index_sync"]["docs_reembedded"] == 1
    assert any(d["id"] == "D9-NOTE" and d["source"] == "ingested" for d in client.get("/api/rag/corpus").json())
    assert client.delete("/api/rag/doc/D9-NOTE").json()["index_sync"]["docs_removed"] == 1


def test_rag_rejects_bad_input(client):
    assert client.post("/api/rag/ingest", json={"raw": "x" * 20, "id": "CTR-2291"}).status_code == 409
    assert client.post("/api/rag/ask", json={"question": "hi there", "retrieval": {"strategy": "magic"}}).status_code == 422
    assert client.post("/api/rag/ask", json={"question": "anything", "use_llm": True}).status_code == 409
    assert client.delete("/api/rag/doc/CTR-2291").status_code == 404
