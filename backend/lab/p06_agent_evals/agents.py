"""Agents under test. Each runs a mission against the simulator and records a full trajectory
inside one trace (root span agent.run, one child span per tool call): the same schema TraceLens
shows, so a recorded production trajectory could be replayed through this evaluator.

- careful:  deterministic baseline that verifies, checks routes, refreshes stale facts, respects capacity
- reckless: deterministic anti-baseline that skips checks; exists to prove the evaluator penalises it
- llm:      DeepSeek or Groq with native tool calling
"""
import json
import time

from lab.core import providers, tracing

from .sim import SCENARIOS, Simulator, openai_tools

NEEDS = {"chemical_spill": ["hazmat", "ambulance"], "collision": ["ambulance", "ambulance", "police"],
         "fire": ["fire_engine", "ambulance"], "medical": ["ambulance"]}


class Recorder:
    def __init__(self, sim: Simulator):
        self.sim, self.steps = sim, []

    def call(self, tool: str, args: dict, *, thought: str = "", usage: dict | None = None) -> dict:
        t0 = time.perf_counter()
        with tracing.span(f"tool.{tool}", kind="tool", module="missionreplay", arguments=args) as sp:
            r = self.sim.call(tool, args)
            if not r["ok"]:
                sp.fail("fault" if r.get("fault") else "invalid_arguments" if not r["args_valid"] else "tool_error", r["error"])
            sp.set(step=self.sim.step, observation=r["observation"])
        self.steps.append({"step": self.sim.step, "tool": tool, "args": args, "thought": thought, **r,
                           "latency_ms": round((time.perf_counter() - t0) * 1000, 2), "usage": usage or {}})
        return r

    def malformed(self, raw: str, usage: dict | None = None) -> None:
        """Record a tool call the provider could not even parse: it uses a step and counts as invalid arguments."""
        self.sim._advance()
        with tracing.span("tool.(unparseable)", kind="tool", module="missionreplay", arguments=raw) as sp:
            sp.fail("invalid_arguments", "model produced unparseable tool-call JSON")
        self.steps.append({"step": self.sim.step, "tool": "(unparseable)", "args": {"_raw": raw[:300]}, "thought": "", "ok": False,
                           "args_valid": False, "error": "model produced tool-call arguments that are not valid JSON",
                           "observation": None, "latency_ms": 0.0, "usage": usage or {}})


def careful(rec: Recorder, sc: dict) -> None:
    inc = sc["incident"]["id"]
    rep = rec.call("get_incident_report", {"incident_id": inc}, thought="Start by reading the report.")["observation"]
    if "duplicate" in rep["status"]:
        rec.call("finish", {"summary": "Duplicate report of an incident already being handled; no dispatch."}, thought="Report says duplicate.")
        return
    units = rec.call("list_units", {}, thought="See which units are available.")["observation"]
    hazard = None
    if rep["hazard_suspected"]:
        hazard = rec.call("verify_hazard", {"incident_id": inc}, thought="Hazard suspected: verify before acting on it.")["observation"]
    budget = sc["budget"]
    for need in NEEDS[rep["type"]]:
        for u in sorted((u for u in units if u["type"] == need and u["available"]), key=lambda u: u["cost"]):
            if u["cost"] > budget:
                continue
            route = rec.call("check_route", {"unit_id": u["id"], "incident_id": inc}, thought=f"Check {u['id']} can reach the scene.")
            if not route["ok"]:  # transient fault: retry once
                route = rec.call("check_route", {"unit_id": u["id"], "incident_id": inc}, thought="Routing failed; retry once.")
            if not route["ok"] or route["observation"]["closed"]:
                continue
            d = rec.call("dispatch_unit", {"unit_id": u["id"], "incident_id": inc}, thought=f"Dispatch {u['id']} ({need}).")
            if d["ok"]:
                budget = d["observation"]["budget_remaining"]
                u["available"] = False
                break
            units = rec.call("list_units", {}, thought="Dispatch failed: refresh availability.")["observation"]
    if hazard and hazard["confirmed"]:
        rec.call("evacuate_zone", {"zone_id": rep["zone"]}, thought="Hazard confirmed: evacuate the zone.")
    rep = rec.call("get_incident_report", {"incident_id": inc}, thought="Refresh casualties before booking beds.")["observation"]
    remaining = rep["casualties"]
    if remaining:
        for h in sorted(rec.call("get_hospital_capacity", {}, thought="Check free beds.")["observation"], key=lambda h: -h["free_beds"]):
            n = min(remaining, h["free_beds"])
            if n > 0:
                rec.call("notify_hospital", {"hospital_id": h["id"], "patients": n}, thought=f"Reserve {n} beds at {h['id']}.")
                remaining -= n
            if remaining == 0:
                break
    rec.call("finish", {"summary": f"Handled {inc}: dispatched {', '.join(rec.sim.dispatched) or 'nothing'}."})


def reckless(rec: Recorder, sc: dict) -> None:
    inc = sc["incident"]["id"]
    rep = rec.call("get_incident_report", {"incident_id": inc})["observation"]
    units = rec.call("list_units", {})["observation"]
    rec.call("list_units", {})  # redundant call: an efficiency penalty
    if rep["hazard_suspected"]:
        rec.call("evacuate_zone", {"zone_id": rep["zone"]}, thought="Evacuate first, ask questions later.")
    for need in NEEDS[rep["type"]]:
        u = next((u for u in units if u["type"] == need and u["id"] not in rec.sim.dispatched), None)
        if u:  # first unit of the type, no availability/route/budget checks
            rec.call("dispatch_unit", {"unit_id": u["id"], "incident_id": inc})
    if rep["casualties"]:
        rec.call("notify_hospital", {"hospital_id": sc["hospitals"][0]["id"], "patients": rep["casualties"]}, thought="Use the casualty count from the first report.")
    rec.call("finish", {"summary": "done"})


SYSTEM = """You are an emergency-response coordinator agent operating through tools only.
Rules: verify suspected hazards before evacuating; only evacuate for a confirmed hazard; check routes before dispatching;
stay within the credit budget; never reserve more beds than a hospital has free; re-read the incident report before booking beds
because casualty counts change; if a report is a duplicate of a handled incident, dispatch nothing. Call finish when done.
Be efficient: avoid repeated calls with identical arguments."""


def llm(rec: Recorder, sc: dict, provider: str | None, temperature: float, model: str | None = None) -> None:
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"{sc['briefing']} Incident id: {sc['incident']['id']}."}]
    nudged, malformed_in_a_row = False, 0
    while rec.sim.step < sc["max_steps"] and not rec.sim.finished:
        try:
            r = providers.chat(msgs, provider=provider, model=model, temperature=temperature, max_tokens=1500, tools=openai_tools(),
                               module="missionreplay", prompt_version="agent-v1")
        except providers.MalformedToolCall as e:
            # Count it (argument validity) and let the model correct itself; give up after 3 in a row.
            rec.malformed(e.failed_generation)
            malformed_in_a_row += 1
            if malformed_in_a_row >= 3:
                raise
            msgs.append({"role": "user", "content": "Your last tool call had arguments that were not valid JSON "
                                                    f"({e.failed_generation[:200]}). Call the tool again with valid JSON arguments."})
            continue
        malformed_in_a_row = 0
        usage = {"input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "cost_usd": r.cost_usd, "latency_ms": round(r.latency_ms, 1)}
        if not r.tool_calls:
            if nudged:
                break
            nudged = True
            msgs += [{"role": "assistant", "content": r.text or ""}, {"role": "user", "content": "Use a tool, or call finish if the mission is complete."}]
            continue
        msgs.append({"role": "assistant", "content": r.text or "", "tool_calls": r.tool_calls})
        for i, tc in enumerate(r.tool_calls):
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable": fn.get("arguments", "")[:200]}
            res = rec.call(fn.get("name", "?"), args, thought=(r.text or "")[:500], usage=usage if i == 0 else {})
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": json.dumps(res["observation"] if res["ok"] else {"error": res["error"]})})
            if rec.sim.finished or rec.sim.step >= sc["max_steps"]:
                break


def run(scenario_id: str, agent: str, *, provider: str | None = None, temperature: float = 0.2, faults: bool = True,
        model: str | None = None) -> dict:
    sc = SCENARIOS[scenario_id]
    sim = Simulator(scenario_id, faults)
    rec = Recorder(sim)
    t0 = time.perf_counter()
    error = None
    with tracing.span("agent.run", kind="request", module="missionreplay", scenario=scenario_id, agent=agent) as sp:
        try:
            if agent == "careful":
                careful(rec, sc)
            elif agent == "reckless":
                reckless(rec, sc)
            elif agent == "llm":
                llm(rec, sc, provider, temperature, model)
            else:
                raise ValueError(f"unknown agent {agent!r}")
        except providers.ProviderError as e:
            error = f"{e.error_type}: {e}"
            sp.fail(e.error_type, str(e))
        trace_id = sp.trace_id
    return {"scenario": scenario_id, "agent": agent, "trace_id": trace_id, "steps": rec.steps, "final": sim.final_state(),
            "sim_events": sim.events, "wall_ms": round((time.perf_counter() - t0) * 1000, 1), "error": error,
            "config": {"provider": provider, "temperature": temperature, "faults": faults, "model": model}}
