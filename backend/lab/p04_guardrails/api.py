import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lab.core import providers
from lab.core.config import var_dir

from . import adversarial, pipeline, policy, sqlguard

router = APIRouter(prefix="/api/guard", tags=["04 TrustBoundary"])
ROLE = "^(viewer|analyst|operator|admin)$"


class ProcessIn(BaseModel):
    document: str = Field(min_length=1, max_length=40_000)
    role: str = Field("analyst", pattern=ROLE)
    mode: str = Field("safe", pattern="^(safe|compromised|llm)$")
    provider: str | None = Field(None, pattern="^(deepseek|groq)$")
    block_threshold: float = Field(0.8, ge=0.05, le=1.0)
    flag_threshold: float = Field(0.4, ge=0.0, le=1.0)
    redact_kinds: list[str] = Field(default_factory=lambda: ["email", "phone", "ssn", "card", "iban"])
    use_model_detector: bool = True


@router.post("/process")
def process(body: ProcessIn):
    if body.flag_threshold > body.block_threshold:
        raise HTTPException(422, "flag threshold must not exceed block threshold")
    return pipeline.process(body.document, body.role, body.mode, body.provider, body.block_threshold, body.flag_threshold,
                            set(body.redact_kinds), body.use_model_detector)


@router.get("/policy")
def get_policy():
    return {"roles": {r: sorted(t) for r, t in policy.ROLE_TOOLS.items()}, "risk_tiers": policy.RISK_TIER,
            "sql": {"allowed_tables": sorted(sqlguard.ALLOWED_TABLES), "sensitive_columns": [f"{t}.{c}" for t, c in sqlguard.SENSITIVE_COLUMNS],
                    "max_limit": sqlguard.MAX_LIMIT}, "internal_domain": policy.INTERNAL_DOMAIN,
            "groq_detector_available": providers.available("groq")}


class ApproveIn(BaseModel):
    approve: bool
    reviewer_role: str = Field("operator", pattern=ROLE)


@router.post("/approvals/{approval_id}")
def approve(approval_id: str, body: ApproveIn):
    return pipeline.decide_approval(approval_id, body.approve, body.reviewer_role)


@router.get("/approvals")
def approvals():
    return pipeline.listing("guard_approvals")


@router.get("/log")
def log():
    return pipeline.listing("guard_log", 100)


@router.get("/sandbox")
def sandbox():
    return {"tickets": pipeline.listing("guard_tickets"), "outbox": pipeline.listing("guard_outbox")}


class SqlIn(BaseModel):
    question: str | None = Field(None, max_length=500)
    sql: str | None = Field(None, max_length=2000)
    role: str = Field("analyst", pattern=ROLE)
    execute: bool = False
    provider: str | None = Field(None, pattern="^(deepseek|groq)$")


@router.post("/sql")
def sql(body: SqlIn):
    """NL->SQL with show-before-execute (PDF 4, interview case). execute=false only previews."""
    generated = None
    q = body.sql
    if body.question and not q:
        if not providers.available(body.provider or providers.default_provider()):
            raise providers.ProviderUnavailable("natural-language SQL needs a provider; offline, type SQL directly")
        r = providers.chat([{"role": "system", "content": "Write one SQLite SELECT for the question. Tables: orders(id, customer_id, sku, qty, total_usd, status, created), "
                                                          "shipments(id, order_id, carrier, status, eta), customers(id, name, region). Reply with SQL only, no code fences."},
                            {"role": "user", "content": body.question}], provider=body.provider, temperature=0.0, max_tokens=800,
                           module="trustboundary", prompt_version="nl2sql-v1")
        q = generated = re.sub(r"^```\w*|```$", "", r.text.strip(), flags=re.M).strip()
    if not q:
        raise HTTPException(422, "provide sql or question")
    try:
        safe, notes = sqlguard.validate(q, body.role)
    except sqlguard.SQLRejected as e:
        return {"generated_sql": generated, "valid": False, "error": str(e)}
    out = {"generated_sql": generated, "valid": True, "safe_sql": safe, "notes": notes, "executed": False}
    if body.execute:
        try:
            out.update(sqlguard.execute(q, body.role), executed=True)
        except sqlguard.SQLRejected as e:
            out.update(valid=False, error=str(e))
    return out


@router.get("/adversarial")
def corpus():
    return adversarial.CORPUS


@router.get("/adversarial/results")
def results(mode: str = "compromised"):
    p = var_dir("results") / f"p04_{mode}.json"
    return json.loads(p.read_text()) if p.exists() else None


class AdvIn(BaseModel):
    mode: str = Field("compromised", pattern="^(compromised|safe|llm)$")
    provider: str | None = Field(None, pattern="^(deepseek|groq)$")


@router.post("/adversarial/run")
def run_adv(body: AdvIn):
    if body.mode == "llm" and not providers.available(body.provider or providers.default_provider()):
        raise providers.ProviderUnavailable("LLM planner needs a configured provider")
    return adversarial.run(body.mode, body.provider)
