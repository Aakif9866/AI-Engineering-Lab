import json

import pytest

from lab.core.db import db
from lab.p06_agent_evals import evaluate as ev
from lab.p06_agent_evals.agents import run as run_agent
from lab.p06_agent_evals.sim import Simulator
from tests.conftest import completion


def test_simulator_is_deterministic():
    a, b = run_agent("S1", "careful"), run_agent("S1", "careful")
    strip = lambda r: [(s["tool"], json.dumps(s["args"]), json.dumps(s["observation"])) for s in r["steps"]]  # noqa: E731
    assert strip(a) == strip(b) and a["final"] == b["final"]


def test_timeline_and_faults_fire_on_steps():
    sim = Simulator("S1")
    for _ in range(4):
        sim.call("list_units", {})
    assert sim.call("get_incident_report", {"incident_id": "INC-1"})["observation"]["casualties"] == 5  # step 5 event
    f = Simulator("S4")
    r = f.call("check_route", {"unit_id": "HAZ-1", "incident_id": "INC-4"})
    assert not r["ok"] and r["fault"] and "timeout" in r["error"]
    assert f.call("check_route", {"unit_id": "HAZ-1", "incident_id": "INC-4"})["ok"]
    assert Simulator("S4", faults=False).call("check_route", {"unit_id": "HAZ-1", "incident_id": "INC-4"})["ok"]


def test_argument_validation_and_unknown_tools():
    sim = Simulator("S1")
    assert sim.call("notify_hospital", {"hospital_id": "H-A", "patients": "five"})["args_valid"] is False
    assert sim.call("dispatch_unit", {"unit_id": "HAZ-1"})["args_valid"] is False
    assert sim.call("teleport", {})["error"].startswith("unknown tool")


def test_careful_agent_passes_every_scenario():
    for sid in ("S1", "S2", "S3", "S4", "S5", "S6"):
        e = ev.evaluate(run_agent(sid, "careful"))
        assert e["passed"], (sid, e["failure_reasons"])
        assert e["tool_recall"] == 1.0 and not e["safety_violations"]


def test_reckless_agent_is_penalised_for_the_right_reasons():
    s1 = ev.evaluate(run_agent("S1", "reckless"))
    assert not s1["passed"] and any(v["violation"] == "evacuated_without_verification" for v in s1["safety_violations"])
    assert any("beds booked 2" in f for f in s1["failure_reasons"])  # used a stale casualty count
    s3 = ev.evaluate(run_agent("S3", "reckless"))
    assert any(p["predicate"] == "evacuated" and not p["passed"] for p in s3["predicates"])
    s6 = ev.evaluate(run_agent("S6", "reckless"))
    assert s6["action_precision"] == 0.0 and not s6["success"]  # dispatched for a duplicate report
    assert s1["redundant_info_calls"] >= 1


def test_final_answer_alone_cannot_pass():
    """An agent that only calls finish with a confident summary fails: success is judged on state."""
    sim = Simulator("S1")
    from lab.p06_agent_evals.agents import Recorder
    rec = Recorder(sim)
    rec.call("finish", {"summary": "All units dispatched, zone evacuated, hospitals notified. Mission complete."})
    e = ev.evaluate({"scenario": "S1", "steps": rec.steps, "final": sim.final_state(), "sim_events": sim.events, "wall_ms": 1})
    assert not e["success"] and e["tool_recall"] == 0


def test_grounding_flags_unobserved_dispatch():
    sim = Simulator("S2")
    from lab.p06_agent_evals.agents import Recorder
    rec = Recorder(sim)
    rec.call("dispatch_unit", {"unit_id": "AMB-3", "incident_id": "INC-2"})
    e = ev.evaluate({"scenario": "S2", "steps": rec.steps, "final": sim.final_state(), "sim_events": sim.events, "wall_ms": 1})
    assert e["ungrounded"] and "without having observed" in e["ungrounded"][0]["issue"]


def test_runs_are_traced_with_one_span_per_tool_call():
    r = ev.run_and_store("S6", "careful")
    with db() as c:
        spans = [dict(x) for x in c.execute("SELECT name, kind, parent_id FROM spans WHERE trace_id=?", (r["run"]["trace_id"],))]
    root = [s for s in spans if s["name"] == "agent.run"]
    tools = [s for s in spans if s["kind"] == "tool"]
    assert len(root) == 1 and len(tools) == len(r["run"]["steps"]) == 2


def test_llm_agent_uses_native_tool_calls(fake_provider):
    script = iter([("get_incident_report", {"incident_id": "INC-6"}), ("finish", {"summary": "Duplicate report; nothing to dispatch."})])

    def handler(req):
        body = json.loads(req.content)
        assert body["tools"] and any(t["function"]["name"] == "dispatch_unit" for t in body["tools"])
        name, args = next(script)
        return completion("", tool_calls=[{"id": f"c-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}])
    fake_provider(handler)
    r = ev.run_and_store("S6", "llm", provider="deepseek")
    assert r["eval"]["passed"] and r["eval"]["tokens"] > 0 and [s["tool"] for s in r["run"]["steps"]] == ["get_incident_report", "finish"]


def test_batch_summary_and_listing():
    res = ev.batch(["careful", "reckless"], ["S1", "S6"])
    assert res["agents"]["careful"]["pass_rate"] == 1.0 and res["agents"]["reckless"]["pass_rate"] == 0.0
    assert len(ev.list_runs()) == 4
    got = ev.get_run(res["runs"][0]["id"])
    assert got["run"]["steps"] and got["eval"]["predicates"]
