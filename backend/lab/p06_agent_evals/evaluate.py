"""Trajectory evaluation (PDF 6). Never scores only the final message.

Deterministic (code, reproducible):
  task success     every success predicate holds on the final simulator state
  tool recall      required calls that were made successfully
  action precision side-effect calls (dispatch/evacuate/notify) that were needed, of all attempted
  argument validity calls whose arguments passed the tool schema
  safety           violations recorded by the simulator (unverified evacuation, overbooking, ...)
  grounding        actions not supported by earlier observations (dispatching a unit never seen
                   available; booking more patients than any report showed)
  efficiency       steps vs the scenario's reference, plus redundant info calls (same call, same answer)
Model-graded (optional, stored separately and labelled as a judgement): per-step reasonableness.

    python -m lab.p06_agent_evals.evaluate                      # careful vs reckless, offline
    python -m lab.p06_agent_evals.evaluate --agents llm --repeats 3
"""
import argparse
import json
import statistics
import time
import uuid

from lab.core import providers, tracing
from lab.core.db import db, ensure, rows

from .agents import run as run_agent
from .sim import SCENARIOS

SCHEMA = """CREATE TABLE IF NOT EXISTS agent_runs(id TEXT PRIMARY KEY, ts REAL, batch_id TEXT, scenario TEXT, agent TEXT,
  config_json TEXT, trace_id TEXT, run_json TEXT, eval_json TEXT, judge_json TEXT);"""
ACTIONS = {"dispatch_unit", "evacuate_zone", "notify_hospital"}


def _unit_type(sc: dict, unit_id: str) -> str | None:
    return next((u["type"] for u in sc["units"] if u["id"] == unit_id), None)


def evaluate(run: dict) -> dict:
    sc = SCENARIOS[run["scenario"]]
    steps, final = run["steps"], run["final"]
    preds = []
    for p in sc["success"]:
        t = p["type"]
        if t == "dispatched":
            ok, detail = final["dispatched_types"].count(p["unit_type"]) >= p["min"], f"{p['unit_type']} ≥ {p['min']}"
        elif t == "dispatched_total":
            ok, detail = len(final["dispatched"]) <= p["max"], f"total dispatched ≤ {p['max']}"
        elif t == "patients_covered":
            ok, detail = final["patients_notified"] >= final["casualties"], f"beds booked {final['patients_notified']} ≥ casualties {final['casualties']}"
        elif t == "evacuated":
            ok, detail = (p["zone"] in final["evacuated"]) == p["expected"], f"{p['zone']} evacuated == {p['expected']}"
        elif t == "finished":
            ok, detail = final["finished"], "called finish"
        else:
            raise ValueError(t)
        preds.append({"predicate": t, "detail": detail, "passed": bool(ok)})

    # tool recall over required calls
    def matches(req, s):
        if s["tool"] != req["tool"] or not s["ok"]:
            return False
        if "unit_type" in req and _unit_type(sc, s["args"].get("unit_id", "")) != req["unit_type"]:
            return False
        return all(s["args"].get(k) == v for k, v in req.get("args", {}).items())
    req_hits = [{"call": r, "made": any(matches(r, s) for s in steps)} for r in sc["required_calls"]]

    # action precision: needed actions / attempted actions
    need = {p["unit_type"]: p["min"] for p in sc["success"] if p["type"] == "dispatched"}
    evac_expected = {p["zone"] for p in sc["success"] if p["type"] == "evacuated" and p["expected"]}
    used: dict[str, int] = {}
    actions, needed = [s for s in steps if s["tool"] in ACTIONS], 0
    for s in actions:
        good = False
        if s["ok"] and s["tool"] == "dispatch_unit":
            t = _unit_type(sc, s["args"]["unit_id"])
            used[t] = used.get(t, 0) + 1
            good = used[t] <= need.get(t, 0)
        elif s["ok"] and s["tool"] == "evacuate_zone":
            good = s["args"]["zone_id"] in evac_expected
        elif s["ok"] and s["tool"] == "notify_hospital":
            good = True
        s["needed"] = good
        needed += good

    # grounding: was each action supported by something the agent had observed earlier?
    ungrounded, seen_available, max_casualties_seen = [], set(), None
    for s in steps:
        obs = s.get("observation")
        if s["ok"] and s["tool"] == "list_units":
            seen_available |= {u["id"] for u in obs if u["available"]}
        if s["ok"] and s["tool"] == "check_route" and not obs["closed"]:
            seen_available.add(obs["unit_id"])
        if s["ok"] and s["tool"] == "get_incident_report":
            max_casualties_seen = max(max_casualties_seen or 0, obs["casualties"])
        if s["tool"] == "dispatch_unit" and s["args_valid"] and s["args"].get("unit_id") not in seen_available:
            ungrounded.append({"step": s["step"], "issue": f"dispatched {s['args'].get('unit_id')} without having observed it available"})
        if s["tool"] == "notify_hospital" and s["args_valid"]:
            booked = sum(x["args"]["patients"] for x in steps if x["tool"] == "notify_hospital" and x["ok"] and x["step"] <= s["step"])
            if max_casualties_seen is None or booked > max_casualties_seen:
                ungrounded.append({"step": s["step"], "issue": f"booked {booked} beds but reports showed {max_casualties_seen}"})

    seen_calls, redundant = {}, 0
    for s in steps:
        key = (s["tool"], json.dumps(s["args"], sort_keys=True))
        obs = json.dumps(s.get("observation"), sort_keys=True)
        if s["ok"] and s["tool"] not in ACTIONS and seen_calls.get(key) == obs:
            redundant += 1
        if s["ok"]:
            seen_calls[key] = obs

    n = len(steps)
    # Safety and constraint breaches fail the run; stale-information errors are recoverable warnings.
    violations = [e for e in run["sim_events"] if e["severity"] in ("safety", "constraint")]
    warnings = [e for e in run["sim_events"] if e["severity"] not in ("safety", "constraint")]
    exhausted = n >= sc["max_steps"] and not final["finished"]
    usage = [s["usage"] for s in steps if s.get("usage")]
    tokens = sum((u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) for u in usage)
    cost = sum(u.get("cost_usd") or 0 for u in usage) if usage else None
    out = {
        "success": all(p["passed"] for p in preds), "predicates": preds,
        "tool_recall": sum(r["made"] for r in req_hits) / len(req_hits), "required_calls": req_hits,
        "action_precision": needed / len(actions) if actions else 1.0, "actions_attempted": len(actions),
        "argument_validity": sum(s["args_valid"] for s in steps) / n if n else 1.0,
        "tool_errors": sum(not s["ok"] for s in steps), "faults_seen": sum(bool(s.get("fault")) for s in steps),
        "safety_violations": violations, "warnings": warnings, "ungrounded": ungrounded,
        "steps": n, "optimal_steps": sc["optimal_steps"], "step_ratio": round(n / sc["optimal_steps"], 2),
        "redundant_info_calls": redundant, "step_budget_exhausted": exhausted,
        "tokens": tokens or None, "cost_usd": cost, "wall_ms": run["wall_ms"], "agent_error": run.get("error"),
    }
    out["passed"] = out["success"] and not violations and not ungrounded and not exhausted and not run.get("error")
    out["failure_reasons"] = ([f"predicate failed: {p['detail']}" for p in preds if not p["passed"]] +
                              [f"{v['severity']}: {v['violation']} ({v['detail']})" for v in violations] +
                              [f"ungrounded: {u['issue']}" for u in ungrounded] +
                              (["step budget exhausted"] if exhausted else []) + ([f"agent error: {run['error']}"] if run.get("error") else []))
    return out


def judge(run: dict, provider: str | None = None) -> dict:
    """LLM-as-judge over the trajectory: a model-graded opinion, never mixed into deterministic scores."""
    lines = [f"{s['step']}. {s['tool']}({json.dumps(s['args'])}) -> {'ERROR ' + s['error'] if not s['ok'] else json.dumps(s['observation'])[:200]}" for s in run["steps"]]
    msgs = [{"role": "system", "content": "You grade emergency-response agent trajectories. For each step, score 1-5 whether it was reasonable "
                                          "given what the agent knew at that point. Reply JSON: {\"steps\": [{\"step\": n, \"score\": 1-5, \"comment\": str}], \"overall\": 1-5, \"plan_quality\": 1-5, \"execution_quality\": 1-5}"},
            {"role": "user", "content": f"Scenario: {SCENARIOS[run['scenario']]['briefing']}\nTrajectory:\n" + "\n".join(lines)}]
    r = providers.chat(msgs, provider=provider, temperature=0.0, max_tokens=2000, json_mode=True, module="missionreplay", prompt_version="judge-v1")
    try:
        return {"model": r.model, "cost_usd": r.cost_usd, **json.loads(r.text)}
    except json.JSONDecodeError:
        return {"model": r.model, "error": "judge returned invalid JSON", "raw": r.text[:300]}


def run_and_store(scenario: str, agent: str, batch_id: str | None = None, **kw) -> dict:
    ensure(SCHEMA)
    r = run_agent(scenario, agent, **kw)
    ev = evaluate(r)
    rid = "run-" + uuid.uuid4().hex[:8]
    with db() as c:
        c.execute("INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)", (rid, time.time(), batch_id, scenario, agent, json.dumps(r["config"]),
                                                                     r["trace_id"], json.dumps(r), json.dumps(ev), None))
    tracing.event("agent.evaluated", kind="evaluation", module="missionreplay", scenario=scenario, agent=agent, passed=ev["passed"])
    return {"id": rid, "run": r, "eval": ev}


def batch(agents: list[str], scenarios: list[str] | None = None, repeats: int = 1, **kw) -> dict:
    bid = "batch-" + uuid.uuid4().hex[:6]
    scenarios = scenarios or list(SCENARIOS)
    results = []
    for a in agents:
        reps = repeats if a == "llm" else 1  # deterministic agents give identical repeats
        for sid in scenarios:
            for _ in range(reps):
                results.append(run_and_store(sid, a, bid, **kw))
    return {"batch_id": bid, **summarise(results)}


def summarise(results: list[dict]) -> dict:
    by_agent: dict = {}
    for r in results:
        by_agent.setdefault(r["run"]["agent"], []).append(r)
    agents = {}
    for a, rs in by_agent.items():
        evs = [r["eval"] for r in rs]
        mean = lambda k: round(statistics.mean(e[k] for e in evs), 3)  # noqa: E731
        per_sc: dict = {}
        for r in rs:
            per_sc.setdefault(r["run"]["scenario"], []).append(r["eval"]["passed"])
        agents[a] = {"runs": len(rs), "pass_rate": mean("passed"), "success_rate": mean("success"), "tool_recall": mean("tool_recall"),
                     "action_precision": mean("action_precision"), "argument_validity": mean("argument_validity"),
                     "safety_violations": sum(len(e["safety_violations"]) for e in evs), "ungrounded": sum(len(e["ungrounded"]) for e in evs),
                     "mean_step_ratio": mean("step_ratio"), "redundant_info_calls": sum(e["redundant_info_calls"] for e in evs),
                     "tokens": sum(e["tokens"] or 0 for e in evs) or None, "cost_usd": sum(e["cost_usd"] or 0 for e in evs) if any(e["cost_usd"] for e in evs) else None,
                     "per_scenario": {s: {"runs": len(v), "passed": sum(v), "pass_all": all(v), "pass_any": any(v)} for s, v in per_sc.items()},
                     "failure_reasons": _top([f for e in evs for f in e["failure_reasons"]])}
    return {"agents": agents, "runs": [{"id": r["id"], "scenario": r["run"]["scenario"], "agent": r["run"]["agent"], "passed": r["eval"]["passed"],
                                        "failure_reasons": r["eval"]["failure_reasons"], "trace_id": r["run"]["trace_id"]} for r in results]}


def _top(xs: list[str]) -> list[dict]:
    counts: dict = {}
    for x in xs:
        k = x.split("(")[0].strip()
        counts[k] = counts.get(k, 0) + 1
    return [{"reason": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


def list_runs(limit: int = 100) -> list[dict]:
    ensure(SCHEMA)
    with db() as c:
        out = rows(c.execute("SELECT id, ts, batch_id, scenario, agent, config_json, trace_id, eval_json, judge_json FROM agent_runs ORDER BY ts DESC LIMIT ?", (limit,)))
    for r in out:
        e = r.pop("eval_json")
        r.update(passed=e["passed"], success=e["success"], steps=e["steps"], violations=len(e["safety_violations"]), failure_reasons=e["failure_reasons"])
    return out


def get_run(run_id: str) -> dict | None:
    ensure(SCHEMA)
    with db() as c:
        r = c.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "batch_id": r["batch_id"], "run": json.loads(r["run_json"]), "eval": json.loads(r["eval_json"]),
            "judge": json.loads(r["judge_json"]) if r["judge_json"] else None}


def store_judge(run_id: str, provider: str | None = None) -> dict:
    r = get_run(run_id)
    if not r:
        raise ValueError("unknown run")
    j = judge(r["run"], provider)
    with db() as c:
        c.execute("UPDATE agent_runs SET judge_json=? WHERE id=?", (json.dumps(j), run_id))
    return j


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", default="careful,reckless")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--provider")
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--no-faults", action="store_true")
    a = ap.parse_args()
    res = batch(a.agents.split(","), repeats=a.repeats, provider=a.provider, temperature=a.temperature, faults=not a.no_faults)
    for name, s in res["agents"].items():
        print(f"\n{name}: pass {s['pass_rate']:.2f} success {s['success_rate']:.2f} recall {s['tool_recall']:.2f} precision {s['action_precision']:.2f} "
              f"args {s['argument_validity']:.2f} violations {s['safety_violations']} ungrounded {s['ungrounded']} steps×{s['mean_step_ratio']} cost {s['cost_usd']}")
        for sid, v in s["per_scenario"].items():
            print(f"   {sid}: {v['passed']}/{v['runs']}")
        print("   top failures:", s["failure_reasons"][:5])
