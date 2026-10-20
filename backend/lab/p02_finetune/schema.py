"""The output contract IntentForge must produce, plus parsing and per-field scoring."""
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

COMPONENT_OWNER = {"billing": "payments", "checkout": "payments", "onboarding": "growth", "notifications": "growth",
                   "search": "platform", "auth": "platform", "mobile_app": "mobile", "reporting": "data"}


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_type: Literal["feature_request", "bug_fix", "removal", "pricing_change", "ux_change", "performance"]
    component: Literal["billing", "checkout", "search", "onboarding", "notifications", "reporting", "auth", "mobile_app"]
    priority: Literal["P0", "P1", "P2", "P3"]
    customer_impact: Literal["low", "medium", "high"]
    requires_migration: bool
    owner_team: Literal["payments", "growth", "platform", "mobile", "data"]
    summary: str = Field(min_length=10, max_length=120)


FIELDS = ["change_type", "component", "priority", "customer_impact", "requires_migration", "owner_team"]


def business_errors(d: Decision) -> list[str]:
    """Rules the JSON schema cannot express. Schema-valid but wrong labels are still bad data."""
    errs = []
    if COMPONENT_OWNER[d.component] != d.owner_team:
        errs.append(f"owner_team {d.owner_team} does not own component {d.component}")
    if d.priority == "P0" and d.customer_impact == "low":
        errs.append("P0 with low customer impact is contradictory")
    return errs


_OBJ = re.compile(r"\{.*\}", re.S)


def parse_output(text: str) -> dict:
    """Score a raw model output. Returns json_valid / schema_valid / fields / errors.
    Lenient on surrounding prose (find the first {...}); strict on the object itself."""
    out = {"json_valid": False, "schema_valid": False, "fields": {}, "error": None}
    m = _OBJ.search(text or "")
    if not m:
        out["error"] = "no JSON object in output"
        return out
    try:
        obj = json.loads(m.group())
    except json.JSONDecodeError as e:
        out["error"] = f"invalid JSON: {e.msg}"
        return out
    out["json_valid"] = isinstance(obj, dict)
    if not out["json_valid"]:
        return out
    out["fields"] = obj
    try:
        Decision.model_validate(obj)
        out["schema_valid"] = True
    except ValidationError as e:
        out["error"] = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4])
    return out


def token_f1(a: str, b: str) -> float:
    ta, tb = re.findall(r"[a-z0-9]+", (a or "").lower()), re.findall(r"[a-z0-9]+", (b or "").lower())
    if not ta or not tb:
        return 0.0
    common = sum(min(ta.count(t), tb.count(t)) for t in set(ta))
    if not common:
        return 0.0
    p, r = common / len(ta), common / len(tb)
    return 2 * p * r / (p + r)


def score(pred_text: str, gold: dict) -> dict:
    p = parse_output(pred_text)
    f = p["fields"]
    per = {k: f.get(k) == gold[k] for k in FIELDS}
    return {**{k: p[k] for k in ("json_valid", "schema_valid", "error")}, "per_field": per,
            "exact_all_fields": p["schema_valid"] and all(per.values()),
            "summary_f1": token_f1(str(f.get("summary", "")), gold["summary"])}


def aggregate(scores: list[dict]) -> dict:
    n = len(scores) or 1
    return {"n": len(scores),
            "json_valid": sum(s["json_valid"] for s in scores) / n,
            "schema_valid": sum(s["schema_valid"] for s in scores) / n,
            "exact_all_fields": sum(s["exact_all_fields"] for s in scores) / n,
            "per_field": {k: sum(s["per_field"][k] for s in scores) / n for k in FIELDS},
            "summary_f1": sum(s["summary_f1"] for s in scores) / n}
