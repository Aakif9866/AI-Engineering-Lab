import { useState } from "react";
import { Link } from "react-router-dom";
import { api, useAction, useApi } from "../api";
import { useStatus, Workspace } from "../components/Layout";
import { Badge, Bars, Card, Empty, ErrorBox, Field, pct, Select, Spinner, Stat, Toggle, usd } from "../components/ui";
import { bySlug } from "../projects";

const p = bySlug("missionreplay");

function ScenarioCard({ sc }: { sc: any }) {
  return (
    <div className="space-y-2 text-xs">
      <p className="text-sm">{sc.briefing}</p>
      <div className="flex flex-wrap gap-1"><Badge>{sc.difficulty}</Badge><Badge>max {sc.max_steps} steps</Badge><Badge>budget {sc.budget}</Badge><Badge>reference {sc.optimal_steps} steps</Badge></div>
      <div><span className="label">Units</span>{sc.units.map((u: any) => <Badge key={u.id} tone={u.available ? "gray" : "rose"}>{u.id} {u.type} · {u.cost}cr · {u.route_minutes}m{u.route_closes_at_step ? ` · route closes @${u.route_closes_at_step}` : ""}</Badge>)}</div>
      <div><span className="label">Hospitals</span>{sc.hospitals.map((h: any) => <Badge key={h.id}>{h.id} {h.capacity} beds</Badge>)}</div>
      {(sc.timeline.length > 0 || sc.faults?.length) && <div><span className="label">World changes</span>{sc.timeline.map((t: any, i: number) => <Badge key={i} tone="amber">step {t.at_step}: {t.event} {t.value ?? t.unit}</Badge>)}{sc.faults?.map((f: any, i: number) => <Badge key={i} tone="rose">fault: {f.tool} call #{f.on_call}</Badge>)}</div>}
      <div><span className="label">Success predicates (checked on final state)</span>{sc.success.map((s: any, i: number) => <Badge key={i} tone="teal">{s.type}{s.unit_type ? ` ${s.unit_type}≥${s.min}` : ""}{s.zone ? ` ${s.zone}=${s.expected}` : ""}{s.max != null ? ` ≤${s.max}` : ""}</Badge>)}</div>
    </div>
  );
}

function Timeline({ data }: { data: any }) {
  const { run, eval: ev } = data;
  const changes = new Set<number>((run.sim_events ?? []).map((e: any) => e.step));
  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="verdict" value={ev.passed ? "PASS" : "FAIL"} tone={ev.passed ? "good" : "bad"} />
        <Stat label="task success" value={ev.success ? "yes" : "no"} tone={ev.success ? "good" : "bad"} />
        <Stat label="tool recall" value={pct(ev.tool_recall)} />
        <Stat label="action precision" value={pct(ev.action_precision)} hint={`${ev.actions_attempted} actions`} />
        <Stat label="argument validity" value={pct(ev.argument_validity)} />
        <Stat label="steps" value={`${ev.steps} / ${ev.optimal_steps}`} hint={`${ev.redundant_info_calls} redundant info calls${ev.cost_usd != null ? ` · ${usd(ev.cost_usd)}` : ""}`} tone={ev.step_budget_exhausted ? "bad" : undefined} />
      </div>
      {ev.failure_reasons.length > 0 && <div className="rounded-tl-xl rounded-br-xl border border-rose-400/50 bg-rose-50 p-3 text-xs dark:bg-rose-400/10"><b>Why it failed:</b><ul className="mt-1 list-disc pl-4">{ev.failure_reasons.map((f: string) => <li key={f}>{f}</li>)}</ul></div>}
      {ev.warnings?.length > 0 && <div className="text-xs text-amber-700 dark:text-amber-300">Recoverable warnings: {ev.warnings.map((w: any) => `${w.violation} (${w.detail}) at step ${w.step}`).join("; ")}</div>}
      <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
        <ol className="relative space-y-2 border-l-2 border-gray-200 pl-4 dark:border-white/10">
          {run.steps.map((s: any) => (
            <li key={s.step} className="relative">
              <span className={`absolute -left-[23px] top-2 h-3 w-3 rounded-full border-2 border-white dark:border-ink-card ${!s.ok ? "bg-rose-500" : s.needed === false ? "bg-amber-500" : "bg-teal-500"}`} />
              <div className={`rounded-tl-xl rounded-br-xl border p-2 text-xs ${changes.has(s.step) ? "border-rose-400/60" : "border-gray-200 dark:border-white/10"}`}>
                <div className="flex flex-wrap items-center gap-1"><span className="font-mono muted">#{s.step}</span><span className="font-mono font-semibold">{s.tool}</span><span className="font-mono muted">{JSON.stringify(s.args)}</span>
                  {s.fault && <Badge tone="rose">injected fault</Badge>}{!s.args_valid && <Badge tone="rose">invalid args</Badge>}{s.needed === true && <Badge tone="teal">needed action</Badge>}{s.needed === false && <Badge tone="amber">unneeded action</Badge>}
                  <span className="ml-auto muted">{s.latency_ms} ms{s.usage?.input_tokens ? ` · ${s.usage.input_tokens}+${s.usage.output_tokens} tok` : ""}</span></div>
                {s.thought && <div className="mt-1 italic muted">“{s.thought}”</div>}
                <div className={`mt-1 font-mono ${s.ok ? "text-gray-700 dark:text-gray-300" : "text-rose-600"}`}>{s.ok ? `→ ${JSON.stringify(s.observation)}` : `✗ ${s.error}`}</div>
              </div>
            </li>
          ))}
        </ol>
        <div className="space-y-3">
          <Card title="Predicates (final state)">{ev.predicates.map((x: any, i: number) => <div key={i} className="text-xs">{x.passed ? "✓" : "✗"} {x.detail}</div>)}</Card>
          <Card title="Required calls">{ev.required_calls.map((x: any, i: number) => <div key={i} className="text-xs">{x.made ? "✓" : "✗"} {x.call.tool}{x.call.unit_type ? ` (${x.call.unit_type})` : ""}{x.call.args ? ` ${JSON.stringify(x.call.args)}` : ""}</div>)}</Card>
          <Card title="Safety & grounding">
            {ev.safety_violations.length === 0 && ev.ungrounded.length === 0 ? <div className="text-xs text-teal-700 dark:text-teal-300">No violations, every action grounded.</div> : null}
            {ev.safety_violations.map((v: any, i: number) => <div key={i} className="text-xs text-rose-600">step {v.step}: {v.violation} ({v.detail})</div>)}
            {ev.ungrounded.map((u: any, i: number) => <div key={i} className="text-xs text-amber-700">step {u.step}: {u.issue}</div>)}
          </Card>
          <Link className="link text-xs" to={`/tracelens?trace=${run.trace_id}`}>open this trajectory in TraceLens ↗</Link>
        </div>
      </div>
    </div>
  );
}

function RunTab() {
  const { status } = useStatus();
  const sc = useApi<any>("/api/agents/scenarios");
  const [sid, setSid] = useState("S1");
  const [agent, setAgent] = useState("careful");
  const [faults, setFaults] = useState(true);
  const [temp, setTemp] = useState(0.2);
  const run = useAction(() => api("/api/agents/run", { body: { scenario: sid, agent, faults, temperature: temp } }));
  const judge = useAction((id: string) => api(`/api/agents/runs/${id}/judge`, { method: "POST" }));
  const scenario = sc.data?.scenarios.find((s: any) => s.id === sid);
  const r: any = run.result;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <Card title="Mission setup">
          <Field label="Scenario"><Select value={sid} onChange={setSid} options={sc.data?.scenarios.map((s: any) => [s.id, `${s.id} · ${s.title}`]) ?? []} /></Field>
          <div className="mt-2"><Field label="Agent"><Select value={agent} onChange={setAgent} options={[["careful", "careful (deterministic baseline)"], ["reckless", "reckless (anti-baseline)"], ...(status?.default_provider ? [["llm", `LLM agent (${status.default_provider})`] as [string, string]] : [])]} /></Field></div>
          {agent === "llm" && <div className="mt-2"><Field label={`Temperature ${temp}`}><input type="range" min={0} max={1.2} step={0.1} value={temp} onChange={(e) => setTemp(+e.target.value)} className="w-full accent-teal-600" /></Field></div>}
          <Toggle checked={faults} onChange={setFaults} label="Inject configured faults" />
          <button className="btn-primary mt-2 w-full" disabled={run.loading} onClick={() => run.run()}>Run mission</button>
          {run.loading && <Spinner label={agent === "llm" ? "Agent thinking" : "Simulating"} />}
          <ErrorBox error={run.error} />
        </Card>
        <Card title={scenario ? `${scenario.id} · ${scenario.title}` : "Scenario"}>{scenario ? <ScenarioCard sc={scenario} /> : <Spinner />}</Card>
      </div>
      {r && (
        <Card title={`Trajectory · ${r.run.agent} on ${r.run.scenario}`} aside={status?.default_provider && <button className="btn !min-h-[32px] !py-1 text-xs" disabled={judge.loading} onClick={() => judge.run(r.id)}>LLM judge (model-graded, paid)</button>}>
          {judge.result && (
            <div className="mb-3 rounded-tl-xl rounded-br-xl border border-violet-400/50 bg-violet-50 p-3 text-xs dark:bg-violet-400/10">
              <b>Model-graded judgement</b> (an opinion, separate from the deterministic scores): overall {(judge.result as any).overall}/5 · plan {(judge.result as any).plan_quality}/5 · execution {(judge.result as any).execution_quality}/5
              <ul className="mt-1">{(judge.result as any).steps?.map((s: any) => <li key={s.step}>#{s.step}: {s.score}/5 {s.comment}</li>)}</ul>
            </div>
          )}
          <ErrorBox error={judge.error} />
          <Timeline data={r} />
        </Card>
      )}
    </div>
  );
}

function CompareTab() {
  const { status } = useStatus();
  const [agents, setAgents] = useState<string[]>(["careful", "reckless"]);
  const [repeats, setRepeats] = useState(3);
  const b = useAction(() => api("/api/agents/batch", { body: { agents, repeats } }));
  const d: any = b.result;
  const all = ["careful", "reckless", ...(status?.default_provider ? ["llm"] : [])];
  return (
    <div className="space-y-4">
      <Card title="Batch evaluation across all scenarios">
        <div className="flex flex-wrap items-end gap-4">
          {all.map((a) => <Toggle key={a} checked={agents.includes(a)} onChange={(v) => setAgents(v ? [...agents, a] : agents.filter((x) => x !== a))} label={a} />)}
          <Field label="LLM repeats per scenario" hint="stochastic behaviour needs repeats; deterministic agents run once"><input type="number" min={1} max={5} className="input w-24" value={repeats} onChange={(e) => setRepeats(+e.target.value)} /></Field>
          <button className="btn-primary" disabled={b.loading || !agents.length} onClick={() => b.run()}>Run batch</button>
        </div>
        {b.loading && <Spinner label="Running missions" />}
        <ErrorBox error={b.error} />
      </Card>
      {d && (
        <>
          <Card title="Agents compared">
            <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-xs">
              <thead className="muted"><tr><th className="py-1">agent</th><th>runs</th><th>pass</th><th>success</th><th>recall</th><th>precision</th><th>arg validity</th><th>safety</th><th>ungrounded</th><th>steps×ref</th><th>tokens</th><th>cost</th></tr></thead>
              <tbody>{Object.entries(d.agents).map(([a, s]: any) => (
                <tr key={a} className="border-t border-gray-100 dark:border-white/5"><td className="py-1.5 font-semibold">{a}</td><td>{s.runs}</td><td>{pct(s.pass_rate)}</td><td>{pct(s.success_rate)}</td><td>{pct(s.tool_recall)}</td><td>{pct(s.action_precision)}</td><td>{pct(s.argument_validity)}</td><td className={s.safety_violations ? "text-rose-600" : ""}>{s.safety_violations}</td><td>{s.ungrounded}</td><td>{s.mean_step_ratio}</td><td>{s.tokens ?? "–"}</td><td>{s.cost_usd == null ? "–" : usd(s.cost_usd)}</td></tr>
              ))}</tbody>
            </table></div>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Pass rate by scenario">
              <Bars rows={Object.entries(d.agents).flatMap(([a, s]: any) => Object.entries(s.per_scenario).map(([sid, v]: any) => ({ label: `${a} · ${sid}`, value: v.passed / v.runs, tone: a === "reckless" ? "bg-rose-500" : a === "llm" ? "bg-purple-500" : undefined, note: `${v.passed}/${v.runs}` })))} format={(v) => pct(v)} />
            </Card>
            <Card title="Failure analysis (most frequent reasons)">
              {Object.entries(d.agents).map(([a, s]: any) => (
                <div key={a} className="mb-2"><div className="label">{a}</div>{s.failure_reasons.length ? s.failure_reasons.slice(0, 6).map((f: any) => <div key={f.reason} className="text-xs">{f.count}× {f.reason}</div>) : <div className="text-xs muted">no failures</div>}</div>
              ))}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function HistoryTab() {
  const runs = useApi<any[]>("/api/agents/runs");
  const [sel, setSel] = useState<string | null>(null);
  const detail = useApi<any>(sel ? `/api/agents/runs/${sel}` : null);
  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <Card title={`Recorded runs (${runs.data?.length ?? 0})`}>
        {!runs.data?.length ? <Empty>No runs yet.</Empty> : <div className="max-h-[32rem] overflow-auto">{runs.data.map((r) => (
          <button key={r.id} onClick={() => setSel(r.id)} className={`flex w-full items-center gap-2 border-t border-gray-100 py-1.5 text-left text-xs dark:border-white/5 ${sel === r.id ? "bg-teal-50 dark:bg-teal-400/10" : ""}`}>
            {r.passed ? <Badge tone="teal">pass</Badge> : <Badge tone="rose">fail</Badge>}<span className="font-mono">{r.scenario}</span><span>{r.agent}</span><span className="ml-auto muted">{new Date(r.ts * 1000).toLocaleTimeString()}</span>
          </button>
        ))}</div>}
      </Card>
      <div className="min-w-0">{detail.data ? <Card title={`${detail.data.run.agent} on ${detail.data.run.scenario}`}><Timeline data={detail.data} /></Card> : <Empty>Select a run to replay its trajectory.</Empty>}</div>
    </div>
  );
}

export default function MissionReplay() {
  return <Workspace p={p} tabs={[
    { id: "run", label: "Run & inspect", content: <RunTab /> },
    { id: "compare", label: "Compare agents", content: <CompareTab /> },
    { id: "history", label: "Run history", content: <HistoryTab /> },
  ]} />;
}
