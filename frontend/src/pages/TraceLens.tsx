import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, useAction, useApi } from "../api";
import { useStatus, Workspace } from "../components/Layout";
import { Badge, Card, Empty, ErrorBox, Field, Json, LineChart, ms, pct, Select, Spinner, Stat, usd } from "../components/ui";
import { bySlug } from "../projects";

const p = bySlug("tracelens");
const MODULES = ["", "rag", "intentforge", "cachecraft", "trustboundary", "signalloop", "missionreplay", "standalone"];
const KIND_COLOR: Record<string, string> = { llm: "bg-purple-500", retrieval: "bg-sky-500", tool: "bg-orange-500", cache: "bg-emerald-500", guardrail: "bg-rose-500", request: "bg-teal-600", generation: "bg-indigo-500", evaluation: "bg-amber-500" };

function Waterfall({ trace, onPick, picked }: { trace: any; onPick: (s: any) => void; picked: any }) {
  const total = Math.max(...trace.spans.map((s: any) => s.offset_ms + s.duration_ms), 1);
  return (
    <div className="space-y-0.5">
      {trace.spans.map((s: any) => (
        <button key={s.span_id} onClick={() => onPick(s)} className={`grid w-full grid-cols-[minmax(0,14rem)_1fr_4.5rem] items-center gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-gray-50 dark:hover:bg-white/5 ${picked?.span_id === s.span_id ? "bg-teal-50 dark:bg-teal-400/10" : ""}`}>
          <span className="truncate" style={{ paddingLeft: s.depth * 12 }}>
            {s.status === "error" ? <span className="text-rose-600">● </span> : null}<span className="font-mono">{s.name}</span>
          </span>
          <span className="relative h-3 rounded bg-gray-100 dark:bg-white/5">
            <span className={`absolute inset-y-0 rounded ${s.status === "error" ? "bg-rose-500" : KIND_COLOR[s.kind] ?? "bg-gray-400"}`} style={{ left: `${(s.offset_ms / total) * 100}%`, width: `${Math.max(0.5, (s.duration_ms / total) * 100)}%` }} />
          </span>
          <span className="text-right tabular-nums">{ms(s.duration_ms)}</span>
        </button>
      ))}
      <div className="flex flex-wrap gap-2 pt-2 text-[11px]">{Object.entries(KIND_COLOR).map(([k, c]) => <span key={k} className="inline-flex items-center gap-1"><span className={`inline-block h-2 w-3 rounded ${c}`} />{k}</span>)}</div>
    </div>
  );
}

function TracesTab() {
  const [params, setParams] = useSearchParams();
  const [module, setModule] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const list = useApi<any[]>(`/api/traces?limit=80${module ? `&module=${module}` : ""}${status ? `&status=${status}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
  const sel = params.get("trace");
  const trace = useApi<any>(sel ? `/api/traces/${sel}` : null);
  const [picked, setPicked] = useState<any>(null);
  const [cmp, setCmp] = useState<string | null>(null);
  const comparison = useApi<any>(cmp && sel && cmp !== sel ? `/api/traces/compare?a=${cmp}&b=${sel}` : null);
  useEffect(() => setPicked(null), [sel]);
  return (
    <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
      <Card title="Search traces">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Module"><Select value={module} onChange={setModule} options={MODULES.map((m) => [m, m || "all"] as [string, string])} /></Field>
          <Field label="Status"><Select value={status} onChange={setStatus} options={[["", "any"], ["ok", "ok"], ["degraded", "degraded"], ["error", "error"]]} /></Field>
        </div>
        <div className="mt-2"><Field label="Text (name, id, attributes)"><input className="input" value={q} onChange={(e) => setQ(e.target.value)} /></Field></div>
        <ErrorBox error={list.error} />
        <div className="mt-3 max-h-[34rem] overflow-auto">
          {!list.data?.length ? <Empty>No traces. Use any workspace, or generate demo traffic on the Playground tab.</Empty> : list.data.map((t) => (
            <button key={t.trace_id} onClick={() => setParams({ trace: t.trace_id })} className={`block w-full border-t border-gray-100 py-1.5 text-left text-xs dark:border-white/5 ${sel === t.trace_id ? "bg-teal-50 dark:bg-teal-400/10" : ""}`}>
              <div className="flex items-center gap-1"><Badge tone={t.status === "ok" ? "teal" : t.status === "degraded" ? "amber" : "rose"}>{t.status}</Badge><span className="font-mono">{t.name}</span><span className="ml-auto tabular-nums">{ms(t.duration_ms)}</span></div>
              <div className="mt-0.5 flex gap-2 muted"><span>{t.module}</span><span>{t.spans} spans</span>{t.llm_calls > 0 && <span>{t.llm_calls} llm</span>}{t.cost_usd != null && <span>{usd(t.cost_usd)}</span>}<span className="ml-auto">{new Date(t.start_ts * 1000).toLocaleTimeString()}</span></div>
            </button>
          ))}
        </div>
      </Card>
      <div className="min-w-0 space-y-4">
        {!sel && <Empty>Select a trace to inspect its span tree.</Empty>}
        {sel && trace.loading && <Spinner />}
        <ErrorBox error={trace.error} />
        {trace.data && (
          <>
            <Card title={<span className="font-mono text-xs">{sel}</span>} aside={<div className="flex gap-2 text-xs"><button className="link" onClick={() => setCmp(sel)}>{cmp === sel ? "baseline set ✓" : "use as comparison baseline"}</button><a className="link" href={`/api/traces/${sel}`} target="_blank" rel="noreferrer">export JSON</a></div>}>
              <div className="mb-3 grid gap-2 sm:grid-cols-5">
                <Stat label="duration" value={ms(trace.data.summary.duration_ms)} />
                <Stat label="spans" value={trace.data.summary.spans} />
                <Stat label="errors" value={trace.data.summary.errors} tone={trace.data.summary.errors ? "bad" : "good"} />
                <Stat label="tokens" value={trace.data.summary.tokens ?? "–"} />
                <Stat label="cost" value={trace.data.summary.cost_usd == null ? "–" : usd(trace.data.summary.cost_usd)} />
              </div>
              <Waterfall trace={trace.data} onPick={setPicked} picked={picked} />
            </Card>
            {picked && (
              <Card title={<>Span · <span className="font-mono">{picked.name}</span></>}>
                <div className="flex flex-wrap gap-1 text-xs"><Badge>{picked.kind}</Badge><Badge>{picked.module}</Badge><Badge tone={picked.status === "ok" ? "teal" : "rose"}>{picked.status}</Badge>{picked.error_type && <Badge tone="rose">{picked.error_type}</Badge>}{picked.input_tokens != null && <Badge>{picked.input_tokens} in / {picked.output_tokens} out{picked.cached_tokens ? ` / ${picked.cached_tokens} cached` : ""}</Badge>}{picked.cost_usd != null && <Badge>{usd(picked.cost_usd)} · {picked.cost_source}</Badge>}</div>
                {picked.error && <div className="mt-2 text-xs text-rose-600">{picked.error}</div>}
                <div className="mt-2"><Json value={picked.attrs_json} /></div>
                <p className="mt-1 text-[11px] muted">Content fields show length and hash only unless LAB_CAPTURE_CONTENT=1 (even then PII and secrets are redacted before storage).</p>
              </Card>
            )}
            {comparison.data && (
              <Card title="Comparison with baseline trace">
                <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left text-xs"><thead className="muted"><tr><th className="py-1">span</th><th>baseline</th><th>this trace</th><th>Δ</th></tr></thead>
                  <tbody>{comparison.data.rows.map((r: any) => (
                    <tr key={r.span} className="border-t border-gray-100 dark:border-white/5"><td className="py-0.5 font-mono" style={{ paddingLeft: r.depth * 10 }}>{r.span}</td>
                      <td className={r.a_status === "error" ? "text-rose-600" : r.a_status === "absent" ? "muted" : ""}>{r.a_status === "absent" ? "absent" : ms(r.a_ms)}</td>
                      <td className={r.b_status === "error" ? "text-rose-600" : r.b_status === "absent" ? "muted" : ""}>{r.b_status === "absent" ? "absent" : ms(r.b_ms)}</td>
                      <td className="tabular-nums">{r.a_ms != null && r.b_ms != null ? `${r.b_ms - r.a_ms > 0 ? "+" : ""}${(r.b_ms - r.a_ms).toFixed(1)}` : ""}</td></tr>
                  ))}</tbody></table></div>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function MetricsTab() {
  const [win, setWin] = useState("24");
  const [group, setGroup] = useState("module");
  const m = useApi<any>(`/api/observability/metrics?window_h=${win}&group=${group}`);
  const ts = useApi<any>(`/api/observability/timeseries?window_h=${win}&buckets=24`);
  const t = m.data?.totals;
  return (
    <div className="space-y-4">
      <Card title="Window" aside={<div className="flex gap-2"><div className="w-32"><Select value={win} onChange={setWin} options={[["1", "1 hour"], ["24", "24 hours"], ["168", "7 days"]]} /></div><div className="w-40"><Select value={group} onChange={setGroup} options={[["module", "by module"], ["model", "by model"], ["prompt_version", "by prompt version"], ["kind", "by span kind"]]} /></div></div>}>
        {!t ? <Spinner /> : (
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="requests" value={t.requests} hint={`${t.spans} spans`} />
            <Stat label="error rate" value={pct(t.error_rate, 1)} tone={(t.error_rate ?? 0) > 0.1 ? "bad" : undefined} />
            <Stat label="LLM p50 / p95 / p99" value={<span className="text-base">{ms(t.llm_p50_ms)} / {ms(t.llm_p95_ms)} / {ms(t.llm_p99_ms)}</span>} hint={`${t.llm_calls} calls`} />
            <Stat label="cost (actual usage)" value={t.cost_usd == null ? "–" : usd(t.cost_usd)} hint={`${t.llm_calls_without_cost} LLM calls without cost data`} />
            <Stat label="retry rate" value={pct(t.retry_rate, 1)} hint="leading indicator" />
            <Stat label="cache hit rate" value={pct(t.cache_hit_rate)} hint={t.cached_prompt_tokens ? `provider prefix cache: ${t.cached_prompt_tokens} tok` : "leading indicator"} />
          </div>
        )}
      </Card>
      {ts.data && <Card title="Requests and p95 latency over time"><LineChart xLabel="time bucket" series={[
        { name: "requests", color: "#14b8a6", points: ts.data.points.map((x: any, i: number) => ({ x: i, y: x.requests })) },
        { name: "errors", color: "#f43f5e", points: ts.data.points.map((x: any, i: number) => ({ x: i, y: x.errors })) },
      ]} /></Card>}
      {m.data && (
        <Card title={`Breakdown ${group.replace("_", " ")}`}>
          <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-xs"><thead className="muted"><tr><th className="py-1">{group}</th><th>count</th><th>error rate</th><th>p50</th><th>p95</th><th>p99</th><th>tokens</th><th>cost</th></tr></thead>
            <tbody>{m.data.table.map((r: any) => <tr key={r.group} className="border-t border-gray-100 dark:border-white/5"><td className="py-1 font-mono">{r.group}</td><td>{r.count}</td><td className={r.error_rate > 0.1 ? "text-rose-600" : ""}>{pct(r.error_rate, 1)}</td><td>{ms(r.p50_ms)}</td><td>{ms(r.p95_ms)}</td><td>{ms(r.p99_ms)}</td><td>{r.tokens ?? "–"}</td><td>{r.cost_usd == null ? "–" : usd(r.cost_usd)}</td></tr>)}</tbody></table></div>
          <p className="mt-2 text-[11px] muted">Percentiles, not averages: the tail is what users complain about. Group by prompt version to compare experiment versions.</p>
        </Card>
      )}
    </div>
  );
}

function AlertsTab() {
  const a = useApi<any>("/api/observability/alerts");
  const ev = useAction(async () => { const r = await api("/api/observability/alerts/evaluate", { method: "POST" }); a.reload(); return r; });
  const upd = useAction(async (id: string, body: any) => { await api(`/api/observability/alerts/${id}`, { method: "PATCH", body }); a.reload(); });
  const [baseH, setBaseH] = useState("168");
  const [curH, setCurH] = useState("1");
  const drift = useApi<any>(`/api/observability/drift?baseline_h=${baseH}&current_h=${curH}`);
  const results: any[] = (ev.result as any) ?? [];
  return (
    <div className="space-y-4">
      <Card title="Alert rules" aside={<button className="btn-primary" disabled={ev.loading} onClick={() => ev.run()}>Evaluate now</button>}>
        <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-xs"><thead className="muted"><tr><th className="py-1">rule</th><th>metric</th><th>condition</th><th>window</th><th>current</th><th>state</th><th>enabled</th></tr></thead>
          <tbody>{a.data?.rules.map((r: any) => {
            const res = results.find((x) => x.id === r.id);
            return (
              <tr key={r.id} className="border-t border-gray-100 dark:border-white/5">
                <td className="py-1">{r.name}{r.leading ? <Badge tone="violet">leading</Badge> : null}</td><td className="font-mono">{r.metric}{r.module ? ` (${r.module})` : ""}</td>
                <td>{r.op} <input type="number" step="any" defaultValue={r.threshold} className="input !inline-block !w-24 !py-0.5" onBlur={(e) => +e.target.value !== r.threshold && upd.run(r.id, { threshold: +e.target.value })} /></td>
                <td>{r.window_min} min</td><td>{res ? (res.no_data ? "no data" : res.value) : "–"}</td>
                <td>{res ? (res.breached ? <Badge tone="rose">{res.fired_now ? "FIRED" : "breached"}</Badge> : res.no_data ? <Badge>no data</Badge> : <Badge tone="teal">ok</Badge>) : "–"}</td>
                <td><input type="checkbox" className="accent-teal-600" checked={!!r.enabled} onChange={(e) => upd.run(r.id, { enabled: e.target.checked })} /></td>
              </tr>
            );
          })}</tbody></table></div>
        <p className="mt-2 text-[11px] muted">A rule fires at most once per window (de-duplicated). Lower a threshold and evaluate to test an alert locally.</p>
        <div className="mt-3"><div className="label">Recent firings</div>{a.data?.history.length ? a.data.history.map((h: any) => <div key={h.id} className="text-xs"><span className="muted">{new Date(h.ts * 1000).toLocaleString()}</span> {h.message}</div>) : <span className="text-xs muted">none</span>}</div>
      </Card>
      <Card title="Drift (population stability index)" aside={<div className="flex gap-2"><div className="w-36"><Select value={baseH} onChange={setBaseH} options={[["24", "baseline 24h"], ["168", "baseline 7d"]]} /></div><div className="w-32"><Select value={curH} onChange={setCurH} options={[["0.25", "last 15 min"], ["1", "last hour"], ["6", "last 6h"]]} /></div></div>}>
        {!drift.data ? <Spinner /> : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(drift.data.series).map(([k, v]: any) => (
            <Stat key={k} label={k.replace(/_/g, " ")} value={v.psi == null ? "n/a" : v.psi} tone={v.verdict === "major shift" ? "bad" : v.verdict === "moderate shift" ? "warn" : v.verdict ? "good" : undefined}
              hint={v.psi == null ? `need ≥10 points per window (have ${v.baseline_n}/${v.current_n})` : `${v.verdict} · median ${v.baseline_median} → ${v.current_median}`} />
          ))}</div>
        )}
        <p className="mt-2 text-[11px] muted">PSI &lt; 0.1 stable, 0.1 to 0.25 moderate, &gt; 0.25 major. Compares the recent window against the preceding baseline window.</p>
      </Card>
    </div>
  );
}

function FailuresTab() {
  const [, setParams] = useSearchParams();
  const f = useApi<any[]>("/api/observability/failures?window_h=168");
  return (
    <Card title="Failure classification (last 7 days)">
      {!f.data?.length ? <Empty>No failed spans recorded.</Empty> : (
        <table className="w-full text-left text-xs"><thead className="muted"><tr><th className="py-1">module</th><th>error type</th><th>count</th><th>latest example</th></tr></thead>
          <tbody>{f.data.map((r, i) => <tr key={i} className="border-t border-gray-100 align-top dark:border-white/5"><td className="py-1">{r.module}</td><td><Badge tone="rose">{r.error_type}</Badge></td><td>{r.count}</td><td><button className="link font-mono" onClick={() => setParams({ trace: r.example.trace_id })}>{r.example.span}</button> <span className="muted">{r.example.error?.slice(0, 120)}</span></td></tr>)}</tbody></table>
      )}
      <p className="mt-2 text-[11px] muted">Clicking an example opens it on the Traces tab.</p>
    </Card>
  );
}

function PlaygroundTab() {
  const { status } = useStatus();
  const [prompt, setPrompt] = useState("In one sentence, what is a trace span?");
  const [days, setDays] = useState(14);
  const play = useAction(() => api("/api/observability/playground", { body: { prompt } }));
  const demo = useAction(() => api("/api/observability/demo-traffic", { method: "POST" }));
  const purge = useAction(() => api(`/api/observability/purge?days=${days}`, { method: "POST" }));
  const [, setParams] = useSearchParams();
  const r: any = play.result;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Standalone traced LLM request">
        <textarea className="input min-h-[80px]" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        <button className="btn-primary mt-2" disabled={!status?.default_provider || play.loading} onClick={() => play.run()}>{status?.default_provider ? `Send to ${status.default_provider}` : "No provider configured"}</button>
        <ErrorBox error={play.error} />
        {r && <div className="mt-3 text-sm"><p>{r.text}</p><p className="mt-1 text-xs muted">{r.usage.input_tokens}→{r.usage.output_tokens} tok · {usd(r.usage.cost_usd)} ({r.usage.cost_source}) · {ms(r.usage.latency_ms)} · attempts {r.usage.attempts}</p><button className="link text-xs" onClick={() => setParams({ trace: r.trace_id })}>view trace</button></div>}
      </Card>
      <div className="space-y-4">
        <Card title="Generate demo traffic (offline)">
          <p className="text-sm muted">Runs real offline executions in each module (RAG questions, cache lookups, guarded documents, agent missions) so every chart has data. No paid calls.</p>
          <button className="btn mt-2" disabled={demo.loading} onClick={() => demo.run()}>{demo.loading ? "Running…" : "Generate"}</button>
          <ErrorBox error={demo.error} />{demo.result && <p className="mt-2 text-xs">Done. Check the Traces and Metrics tabs.</p>}
        </Card>
        <Card title="Retention & privacy">
          <p className="text-sm muted">Content capture is <b>{status?.capture_content ? "ON (PII and secrets redacted before storage)" : "OFF"}</b>. With it off, prompts and outputs are stored as length plus hash only. Set LAB_CAPTURE_CONTENT in .env.</p>
          <div className="mt-2 flex items-end gap-2"><Field label="Delete spans older than (days)"><input type="number" className="input w-28" value={days} onChange={(e) => setDays(+e.target.value)} /></Field><button className="btn" onClick={() => purge.run()}>Purge</button></div>
          {purge.result && <p className="mt-2 text-xs">Deleted {(purge.result as any).deleted_spans} spans.</p>}
        </Card>
      </div>
    </div>
  );
}

export default function TraceLens() {
  const [params] = useSearchParams();
  return <Workspace p={p} tabs={[
    { id: "traces", label: "Traces", content: <TracesTab /> },
    { id: "metrics", label: "Metrics", content: <MetricsTab /> },
    { id: "alerts", label: "Alerts & drift", content: <AlertsTab /> },
    { id: "failures", label: "Failures", content: <FailuresTab /> },
    { id: "play", label: "Playground & retention", content: <PlaygroundTab /> },
  ]} focus={params.get("trace") ? { tab: "traces", nonce: params.get("trace")! } : undefined} />;
}
