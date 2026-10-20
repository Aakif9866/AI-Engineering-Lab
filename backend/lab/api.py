"""FastAPI app: one router per pattern module plus shared status. Run: uvicorn lab.api:app --port 8000"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lab.core import embeddings, providers
from lab.core.config import env, flag
from lab.core.redaction import scrub_secrets
from lab.p01_rag.api import router as rag
from lab.p02_finetune.api import router as finetune
from lab.p03_cache.api import router as cache
from lab.p04_guardrails.api import router as guard
from lab.p05_feedback.api import router as feedback
from lab.p06_agent_evals.api import router as agents
from lab.p07_observability.api import router as observability

app = FastAPI(title="AI Engineering Lab", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
for r in (rag, finetune, cache, guard, feedback, agents, observability):
    app.include_router(r)


@app.exception_handler(providers.ProviderUnavailable)
def _unavailable(_: Request, e: Exception):
    return JSONResponse({"error": "provider_unavailable", "detail": scrub_secrets(str(e))}, status_code=409)


@app.exception_handler(providers.ProviderError)
def _provider(_: Request, e: Exception):
    return JSONResponse({"error": getattr(e, "error_type", "provider_error"), "detail": scrub_secrets(str(e))}, status_code=502)


@app.exception_handler(PermissionError)
def _forbidden(_: Request, e: Exception):
    return JSONResponse({"error": "forbidden", "detail": scrub_secrets(str(e))}, status_code=403)


@app.exception_handler(ValueError)
def _value(_: Request, e: Exception):
    return JSONResponse({"error": "bad_request", "detail": scrub_secrets(str(e))}, status_code=400)


@app.get("/api/status")
def status():
    return {**providers.status(), "embedder": env("LAB_EMBEDDER", "minilm"),
            "embedder_fallback": embeddings.fallback_reason, "capture_content": flag("LAB_CAPTURE_CONTENT")}
