from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lab.core import providers

from . import evaluate as ev
from .sim import SCENARIOS, TOOLS

router = APIRouter(prefix="/api/agents", tags=["06 MissionReplay"])


@router.get("/scenarios")
def scenarios():
    return {"scenarios": list(SCENARIOS.values()), "tools": {n: {"description": d, "schema": m.model_json_schema()} for n, (m, d) in TOOLS.items()}}


class RunIn(BaseModel):
    scenario: str
    agent: str = Field("careful", pattern="^(careful|reckless|llm)$")
    provider: str | None = Field(None, pattern="^(deepseek|groq)$")
    temperature: float = Field(0.2, ge=0, le=1.5)
    faults: bool = True


def _check(agent: str, provider: str | None):
    if agent == "llm" and not providers.available(provider or providers.default_provider()):
        raise providers.ProviderUnavailable("the LLM agent needs a configured provider; use careful/reckless offline")


@router.post("/run")
def run(b: RunIn):
    if b.scenario not in SCENARIOS:
        raise HTTPException(404, "unknown scenario")
    _check(b.agent, b.provider)
    return ev.run_and_store(b.scenario, b.agent, provider=b.provider, temperature=b.temperature, faults=b.faults)


class BatchIn(BaseModel):
    agents: list[str] = Field(default_factory=lambda: ["careful", "reckless"])
    scenarios: list[str] | None = None
    repeats: int = Field(1, ge=1, le=5)
    provider: str | None = Field(None, pattern="^(deepseek|groq)$")
    temperature: float = Field(0.2, ge=0, le=1.5)
    faults: bool = True


@router.post("/batch")
def batch(b: BatchIn):
    for a in b.agents:
        if a not in ("careful", "reckless", "llm"):
            raise HTTPException(422, f"unknown agent {a}")
        _check(a, b.provider)
    return ev.batch(b.agents, b.scenarios, b.repeats, provider=b.provider, temperature=b.temperature, faults=b.faults)


@router.get("/runs")
def runs(limit: int = 100):
    return ev.list_runs(min(limit, 500))


@router.get("/runs/{run_id}")
def get(run_id: str):
    r = ev.get_run(run_id)
    if not r:
        raise HTTPException(404, "unknown run")
    return r


@router.post("/runs/{run_id}/judge")
def judge(run_id: str, provider: str | None = None):
    _check("llm", provider)
    return ev.store_judge(run_id, provider)
