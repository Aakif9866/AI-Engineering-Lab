"""The policy engine: the actual security boundary. It never asks the model whether an action is
allowed. Decisions come from the caller's role, the tool's risk tier, validated arguments and
whether the input was flagged as tainted."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lab.core.redaction import detect_pii

from . import sqlguard

INTERNAL_DOMAIN = "meridian.example"
ROLE_TOOLS = {
    "viewer": set(),
    "analyst": {"query_sales_db", "create_ticket"},
    "operator": {"query_sales_db", "create_ticket", "send_reply"},
    "admin": {"query_sales_db", "create_ticket", "send_reply", "export_customer_data"},
}
# Cost-of-error drives friction (PDF 4f): reads run, writes to people need a human, bulk export needs one too.
RISK_TIER = {"query_sales_db": "low", "create_ticket": "medium", "send_reply": "high", "export_customer_data": "critical"}


class QueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field(min_length=6, max_length=2000)


class TicketArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=5, max_length=120)
    priority: Literal["P1", "P2", "P3"]
    team: Literal["support", "logistics", "billing", "quality"]


class ReplyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(pattern=r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")  # exactly one address: no smuggled CC lists
    subject: str = Field(min_length=2, max_length=150)
    body: str = Field(min_length=2, max_length=2000)


class ExportArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["csv", "json"]


ARGS = {"query_sales_db": QueryArgs, "create_ticket": TicketArgs, "send_reply": ReplyArgs, "export_customer_data": ExportArgs}


def decide(action: dict, role: str, ctx: dict) -> dict:
    """Returns {decision: allow|approval|deny, reasons: [...], args: validated args}."""
    tool = action.get("tool")
    reasons: list[str] = []
    if tool not in ARGS:  # exact match only: 'Send_Reply' or 'send_reply ' are unknown tools
        return {"decision": "deny", "reasons": [f"unknown tool {tool!r}"], "args": None}
    if tool not in ROLE_TOOLS.get(role, set()):
        return {"decision": "deny", "reasons": [f"role '{role}' is not permitted to use {tool}"], "args": None}
    try:
        args = ARGS[tool].model_validate(action.get("args") or {}).model_dump()
    except ValidationError as e:
        return {"decision": "deny", "reasons": ["invalid arguments: " + "; ".join(f"{'.'.join(map(str, x['loc']))} {x['msg']}" for x in e.errors()[:3])], "args": None}

    tainted = ctx.get("tainted", False)
    decision = "allow"
    if tool == "query_sales_db":
        try:
            args["sql"], notes = sqlguard.validate(args["sql"], role)
            reasons += notes
        except sqlguard.SQLRejected as e:
            return {"decision": "deny", "reasons": [f"SQL rejected: {e}"], "args": args}
    elif tool == "create_ticket":
        if args["priority"] == "P1":
            decision = "approval"
            reasons.append("P1 tickets page on-call: human approval required")
    elif tool == "send_reply":
        domain = args["to"].split("@")[1].lower()
        sender = (ctx.get("sender") or "").lower()
        if args["to"].lower() != sender and domain != INTERNAL_DOMAIN:
            return {"decision": "deny", "reasons": [f"recipient {args['to']} is neither the original sender nor internal"], "args": args}
        if urls := [u for u in re.findall(r"https?://([^/\s)]+)", args["body"]) if not u.endswith(INTERNAL_DOMAIN)]:
            return {"decision": "deny", "reasons": [f"reply contains external links: {', '.join(urls[:3])}"], "args": args}
        leaked = [f.kind for f in detect_pii(args["body"]) if f.value.lower() != args["to"].lower()]
        if leaked:
            return {"decision": "deny", "reasons": [f"reply would disclose personal data: {', '.join(sorted(set(leaked)))}"], "args": args}
        decision = "approval"
        reasons.append("outbound email always requires human review")
    elif tool == "export_customer_data":
        decision = "approval"
        reasons.append("bulk export of customer data requires approval")

    if tainted:
        if RISK_TIER[tool] in ("high", "critical"):
            return {"decision": "deny", "reasons": reasons + ["input was flagged as a likely injection: high-risk tools are disabled for this document"], "args": args}
        if decision == "allow" and tool != "query_sales_db":
            decision = "approval"
            reasons.append("input flagged: side effects need approval")
    return {"decision": decision, "reasons": reasons, "args": args, "risk_tier": RISK_TIER[tool]}
