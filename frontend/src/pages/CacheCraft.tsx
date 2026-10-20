import { useState } from "react";
import { Link } from "react-router-dom";
import { api, useAction, useApi } from "../api";
import { useStatus, Workspace } from "../components/Layout";
import { Badge, Bars, Card, Empty, ErrorBox, Field, LineChart, ms, pct, Select, Spinner, Stat, Toggle, usd } from "../components/ui";
import { bySlug } from "../projects";

const p = bySlug("cachecraft");
type Cfg = { mode: "off" | "exact" | "semantic"; threshold: number; reject_band: number; ttl_s: number; prompt_version: string; provider: string | null; temperature: number; scope_aware: boolean; dependency_check: boolean };
const DEFAULT: Cfg = { mode: "semantic", threshold: 0.9, reject_band: 0.1, ttl_s: 3600, prompt_version: "faq-v1", provider: null, temperature: 0, scope_aware: true, dependency_check: true };
const EVENT_TONE: Record<string, any> = { hit_exact: "teal", hit_semantic: "teal", miss: "gray", rejected_match: "amber", bypass: "violet", upstream_error: "rose" };
const EXAMPLES = [
  ["paraphrase pair", "How much does the Pro plan cost?", "What's the price of Nimbus Pro?"],
  ["confusable pair", "Can I get a refund within 30 days of purchase?", "Can I get a refund after 30 days?"],
  ["confusable pair", "What is the storage limit on the free plan?", "What is the storage limit on the Pro plan?"],
  ["personal", "When does my plan renew?", ""],
  ["volatile", "Is Nimbus down right now?", ""],
];

function GatewayTab({ cfg, setCfg }: { cfg: Cfg; setCfg: (c: Cfg) => void }) {
  const { status } = useStatus();
  const [q, setQ] = useState("How much does the Pro plan cost?");
  const [user, setUser] = useState("u1");
  const [ns, setNs] = useState("faq");
  const entries = useApi<any[]>(`/api/cache/entries?namespace=${ns}`);
  const events = useApi<any>("/api/cache/events?limit=25");
  const ask = useAction(async () => { const r = await api("/api/cache/ask", { body: { question: q, user_id: user, namespace: ns, config: cfg } }); entries.reload(); events.reload(); return r; });
  const clear = useAction(async () => { await api(`/api/cache/namespace/${ns}`, { method: "DELETE" }); entries.reload(); });
  const purge = useAction(async () => { const r = await api("/api/cache/purge-fingerprints", { body: { question: "x", namespace: ns, config: cfg } }); entries.reload(); return r; });
  const r: any = ask.result;
  const set = (k: keyof Cfg, v: any) => setCfg({ ...cfg, [k]: v });
  return (
    <div className="grid gap-4 xl:grid-cols-[22rem_1fr]">
      <Card title="Cache policy">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Mode"><Select value={cfg.mode} onChange={(v) => set("mode", v)} options={[["semantic", "exact → semantic"], ["exact", "exact only"], ["off", "no cache"]]} /></Field>
          <Field label="TTL (s)"><input type="number" className="input" value={cfg.ttl_s} min={1} onChange={(e) => set("ttl_s", +e.target.value)} /></Field>
          <div className="col-span-2"><Field label={`Semantic threshold: ${cfg.threshold.toFixed(2)}`} hint={`similarities within ${cfg.reject_band} below are logged as rejected matches`}><input type="range" min={0.5} max={0.99} step={0.01} value={cfg.threshold} onChange={(e) => set("threshold", +e.target.value)} className="w-full accent-teal-600" /></Field></div>
          <Field label="Prompt version" hint="part of the key"><input className="input" value={cfg.prompt_version} onChange={(e) => set("prompt_version", e.target.value)} /></Field>
          <Field label="Temperature" hint="part of the key"><input type="number" step={0.1} min={0} max={2} className="input" value={cfg.temperature} onChange={(e) => set("temperature", +e.target.value)} /></Field>
        </div>
        <Toggle checked={cfg.scope_aware} onChange={(v) => set("scope_aware", v)} label="User-scoped keys for personal questions" hint="turn off to see cross-user leaks" />
        <Toggle checked={cfg.dependency_check} onChange={(v) => set("dependency_check", v)} label="Dependency-aware invalidation" hint="turn off, edit an article, see stale answers" />
        <Toggle checked={!!cfg.provider} disabled={!status?.default_provider} onChange={(v) => set("provider", v ? status?.default_provider : null)} label={`Real upstream model${status?.default_provider ? ` (${status.default_provider})` : ""}`} hint={cfg.provider ? "misses cost real tokens" : "offline answerer, modelled 800 ms latency"} />
      </Card>
      <div className="min-w-0 space-y-4">
        <Card title="Send a request through the gateway">
          <div className="grid gap-3 sm:grid-cols-[1fr_6rem_8rem]">
            <Field label="Question"><input className="input" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
            <Field label="User"><Select value={user} onChange={setUser} options={["u1", "u2", "u3"]} /></Field>
            <Field label="Namespace"><input className="input" value={ns} onChange={(e) => setNs(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))} /></Field>
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {EXAMPLES.flatMap(([kind, a, b]) => [a, b].filter(Boolean).map((x) => (
              <button key={x} onClick={() => setQ(x)} className="rounded-tl-md rounded-br-md border border-gray-200 px-2 py-1 text-[11px] hover:border-teal-500 dark:border-white/10" title={kind}>{kind}: {x.slice(0, 34)}…</button>
            )))}
          </div>
          <button className="btn-primary mt-3" disabled={ask.loading} onClick={() => ask.run()}>Ask</button>
          <ErrorBox error={ask.error} />
        </Card>
        {r && (
          <Card title="Decision" aside={<div className="flex items-center gap-2"><Badge tone={EVENT_TONE[r.event]}>{r.event}</Badge>{r.trace_id && <Link className="link text-xs" to={`/tracelens?trace=${r.trace_id}`}>trace ↗</Link>}</div>}>
            {r.event === "upstream_error" ? <ErrorBox error={new Error(r.error)} /> : <p className="text-sm">{r.answer}</p>}
            <div className="mt-3 grid gap-2 sm:grid-cols-4">
              <Stat label="scope" value={r.scope} hint={`key scope: ${r.scope_key}`} />
              <Stat label="similarity" value={r.similarity == null ? "–" : r.similarity.toFixed(3)} hint={r.matched_question ? `nearest: “${r.matched_question}”` : `threshold ${cfg.threshold}`} tone={r.event === "rejected_match" ? "warn" : undefined} />
              <Stat label="latency" value={ms(r.modelled_ms)} hint={r.cost_kind === "estimated" && r.event !== "hit_exact" && r.event !== "hit_semantic" ? `measured ${ms(r.measured_ms)} + modelled upstream` : `measured ${ms(r.measured_ms)}`} />
              <Stat label={r.event.startsWith("hit") ? "cost avoided" : "cost"} value={usd(r.event.startsWith("hit") ? r.cost_avoided_usd : r.cost_usd)} hint={`${r.cost_kind}${r.cached_tokens ? ` · provider prefix cache: ${r.cached_tokens} tok` : ""}`} />
            </div>
            {r.similarity != null && (
              <div className="mt-3">
                <div className="relative h-3 rounded-r-full bg-gray-100 dark:bg-white/5">
                  <div className="absolute inset-y-0 bg-amber-400/40" style={{ left: `${(cfg.threshold - cfg.reject_band) * 100}%`, width: `${cfg.reject_band * 100}%` }} />
                  <div className="absolute inset-y-0 w-0.5 bg-teal-600" style={{ left: `${cfg.threshold * 100}%` }} />
                  <div className="absolute -top-0.5 h-4 w-1.5 rounded bg-gray-900 dark:bg-white" style={{ left: `calc(${Math.max(0, r.similarity) * 100}% - 3px)` }} />
                </div>
                <div className="mt-1 text-[11px] muted">0 ··· similarity ··· 1 · teal line = threshold · amber = reject band</div>
              </div>
            )}
            {r.evicted?.length > 0 && <div className="mt-2 text-xs text-amber-700 dark:text-amber-300">Evicted before lookup: {r.evicted.map((e: any) => `“${e.question}” (${e.reason})`).join(", ")}</div>}
            <div className="mt-2 font-mono text-[11px] muted">fingerprint {r.fingerprint} · deps {JSON.stringify(r.deps)}</div>
          </Card>
        )}
        <Card title={`Entries in namespace “${ns}” (${entries.data?.length ?? 0})`} aside={<div className="flex gap-2"><button className="btn !min-h-[32px] !py-1 text-xs" onClick={() => purge.run()}>purge old fingerprints</button><button className="btn !min-h-[32px] !py-1 text-xs" onClick={() => clear.run()}>clear</button></div>}>
          {purge.result && <div className="mb-2 text-xs muted">Purged {(purge.result as any).deleted} unreachable entries.</div>}
          {!entries.data?.length ? <Empty>Empty. Misses write through to the cache.</Empty> : (
            <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-xs">
              <thead className="muted"><tr><th className="py-1">question</th><th>scope</th><th>hits</th><th>age</th><th>deps</th><th>cost</th></tr></thead>
              <tbody>{entries.data.map((e) => (
                <tr key={e.id} className="border-t border-gray-100 dark:border-white/5"><td className="py-1 pr-2">{e.question}</td><td className="font-mono">{e.scope_key}</td><td>{e.hits}</td><td>{e.age_s}s{e.expired && <Badge tone="amber">expired</Badge>}</td><td>{e.deps_current ? <Badge tone="teal">current</Badge> : <Badge tone="rose">stale</Badge>}</td><td>{usd(e.cost_usd)} <span className="muted">{e.cost_kind}</span></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </Card>
        <Card title="Recent gateway events (interactive only)">
          <div className="mb-2 flex flex-wrap gap-2">{events.data?.summary?.map((s: any) => <Badge key={s.event} tone={EVENT_TONE[s.event]}>{s.event}: {s.n}</Badge>)}</div>
          <div className="max-h-64 overflow-auto text-xs">{events.data?.events?.map((e: any) => (
            <div key={e.id} className="flex gap-2 border-t border-gray-100 py-1 dark:border-white/5"><Badge tone={EVENT_TONE[e.event]}>{e.event}</Badge><span className="truncate">{e.question}</span><span className="ml-auto muted">{e.user_id} · {e.similarity?.toFixed?.(2) ?? ""}</span></div>
          ))}</div>
        </Card>
      </div>
    </div>
  );
}

function KbTab() {
  const { data, reload } = useApi<any>("/api/cache/kb");
  const [sel, setSel] = useState("pricing_pro");
  const [text, setText] = useState("The Pro plan costs $10 per month, or $100 per year when billed annually.");
  const [purge, setPurge] = useState(true);
  const edit = useAction(async () => { const r = await api(`/api/cache/kb/${sel}`, { body: { answer: text, purge } }); reload(); return r; });
  const reset = useAction(async () => { await api("/api/cache/kb-reset", { method: "POST" }); reload(); });
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <Card title="Help-center articles (each answer has a content version hash)">
        <div className="divide-y divide-gray-100 dark:divide-white/5">{data?.articles.map((a: any) => (
          <div key={a.id} className="py-2 text-sm">
            <div className="flex flex-wrap items-center gap-1.5"><span className="font-medium">{a.title}</span><Badge>{a.scope}</Badge><Badge tone="violet">group {a.group}</Badge><span className="font-mono text-[11px] muted">v{a.version}</span>{a.edited && <Badge tone="amber">edited</Badge>}</div>
            <p className="text-xs muted">{a.answer}</p>
          </div>
        ))}</div>
      </Card>
      <Card title="Change the underlying data">
        <Field label="Article"><Select value={sel} onChange={setSel} options={data?.articles.map((a: any) => [a.id, a.title]) ?? []} /></Field>
        <div className="mt-2"><Field label="New answer"><textarea className="input min-h-[90px]" value={text} onChange={(e) => setText(e.target.value)} /></Field></div>
        <Toggle checked={purge} onChange={setPurge} label="Purge dependent entries now" hint="off = rely on the lookup-time version check" />
        <button className="btn-primary mt-2 w-full" disabled={edit.loading} onClick={() => edit.run()}>Save article</button>
        <button className="btn mt-2 w-full" onClick={() => reset.run()}>Reset knowledge base</button>
        {edit.result && <p className="mt-2 text-xs muted">New version {(edit.result as any).article.version}; purged {(edit.result as any).purged_entries} entries. Ask about it on the Gateway tab to see the dependency check work.</p>}
        <ErrorBox error={edit.error} />
      </Card>
    </div>
  );
}

function CompareTab() {
  const { data, reload, loading } = useApi<any>("/api/cache/experiments");
  const sample = useApi<any>("/api/cache/workload/sample");
  const run = useAction(async () => { await api("/api/cache/experiments/run", { body: { n: 240, seed: 11 } }); await reload(); });
  return (
    <div className="space-y-4">
      <Card title="Labelled workload: no cache vs exact vs semantic" aside={<button className="btn-primary" disabled={run.loading} onClick={() => run.run()}>{run.loading ? "Running 9 modes…" : "Run comparison"}</button>}>
        {sample.data && <p className="text-sm muted">240 queries: {Object.entries(sample.data.kinds).map(([k, v]) => `${v} ${k}`).join(", ")}. At query {sample.data.events[0].at} the Pro price changes from $8 to $10. Each query carries its true intent, so every hit is checked for correctness.</p>}
        {(loading || run.loading) && <Spinner />}
        <ErrorBox error={run.error} />
      </Card>
      {!data ? <Empty>No results yet.</Empty> : (
        <>
          <Card title={`Results · embedder ${data.embedder.split("/").pop()} · upstream ${data.upstream}`}>
            <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-xs">
              <thead className="muted"><tr><th className="py-1">mode</th><th>hit rate</th><th>exact / semantic</th><th>false hits</th><th>rejected</th><th>upstream calls</th><th>p50 / p95 latency*</th><th>cost spent</th><th>cost avoided</th></tr></thead>
              <tbody>{data.modes.map((m: any) => (
                <tr key={m.label} className={`border-t border-gray-100 dark:border-white/5 ${m.label.includes("NO") ? "bg-rose-50/50 dark:bg-rose-400/5" : ""}`}>
                  <td className="py-1.5 font-medium">{m.label}</td><td>{pct(m.hit_rate)}</td><td>{m.events.hit_exact} / {m.events.hit_semantic}</td>
                  <td className={m.false_hits ? "font-semibold text-rose-600 dark:text-rose-400" : ""}>{m.false_hits} ({pct(m.false_hit_rate, 1)})</td><td>{m.events.rejected_match}</td><td>{m.upstream_calls}</td>
                  <td>{ms(m.latency_modelled_ms.p50)} / {ms(m.latency_modelled_ms.p95)}</td><td>{usd(m.cost_spent_usd)}</td><td>{usd(m.cost_avoided_usd)}</td>
                </tr>
              ))}</tbody>
            </table></div>
            <p className="mt-2 text-[11px] muted">*Offline upstream: measured gateway time plus a modelled 800 ms model call (clearly simulated). Costs are {data.modes[0].cost_kind}, from configured pricing. A hit counts as false when it answered a different intent, another user's account, or stale data.</p>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Hit rate vs false-hit rate"><Bars rows={data.modes.flatMap((m: any) => [{ label: `${m.label} · hits`, value: m.hit_rate }, { label: `${m.label} · false`, value: m.false_hit_rate, tone: "bg-rose-500" }])} format={(v) => pct(v)} /></Card>
            <Card title="False hits (what a user would have seen)">
              {data.modes.filter((m: any) => m.false_hits).map((m: any) => (
                <details key={m.label} className="mb-2 text-xs"><summary className="cursor-pointer font-medium">{m.label}: {m.false_hits}</summary>
                  <ul className="mt-1 space-y-1">{m.false_hit_examples.map((x: any, i: number) => <li key={i}>“{x.question}” ({x.user}) got the answer for <b>{x.served_label}</b>{x.matched ? <> via “{x.matched}” @ {x.similarity}</> : null}</li>)}</ul>
                </details>
              ))}
              {!data.modes.some((m: any) => m.false_hits) && <Empty>No false hits in any mode.</Empty>}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function SweepTab() {
  const { data, loading, error } = useApi<any>("/api/cache/sweep");
  if (loading || !data) return error ? <ErrorBox error={error} /> : <Spinner />;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="labelled pairs" value={data.pairs} hint={`${data.positives} paraphrase pairs`} />
        <Stat label="best F1 threshold" value={data.best_f1.threshold.toFixed(2)} hint={`P ${data.best_f1.precision.toFixed(2)} · R ${data.best_f1.recall.toFixed(2)} · ${data.best_f1.false_positives} FP`} />
        <Stat label="lowest zero-FP threshold" value={data.lowest_zero_false_positive?.threshold.toFixed(2) ?? "none"} hint={data.lowest_zero_false_positive ? `recall ${data.lowest_zero_false_positive.recall.toFixed(2)}` : ""} tone="good" />
      </div>
      <Card title={`Precision / recall vs threshold · ${data.embedder.split("/").pop()}`}>
        <LineChart xLabel="threshold" yMin={0} yMax={1} series={[
          { name: "precision", color: "#14b8a6", points: data.rows.map((r: any) => ({ x: r.threshold, y: r.precision })) },
          { name: "recall", color: "#a855f7", points: data.rows.map((r: any) => ({ x: r.threshold, y: r.recall })) },
          { name: "share of confusable pairs wrongly matched", color: "#f43f5e", dashed: true, points: data.rows.map((r: any) => ({ x: r.threshold, y: r.confusable_false_positives / Math.max(1, data.rows[0].confusable_false_positives) })) },
        ]} marks={[{ x: data.best_f1.threshold, label: "best F1" }]} />
      </Card>
      <Card title="Similarity distributions">
        <Bars max={1} rows={Object.entries(data.similarity_summary).flatMap(([k, v]: any) => [{ label: `${k} median`, value: v.median, tone: k === "duplicate" ? "bg-teal-500" : k === "confusable" ? "bg-rose-500" : "bg-gray-400" }, { label: `${k} max`, value: v.max, tone: k === "duplicate" ? "bg-teal-300" : k === "confusable" ? "bg-rose-300" : "bg-gray-300" }])} />
        <p className="mt-2 text-xs muted">If confusable pairs (refund within vs after 30 days) score as high as true paraphrases, no single threshold separates them: that is the semantic-caching design problem. {data.caveat}</p>
      </Card>
    </div>
  );
}

export default function CacheCraft() {
  const [cfg, setCfg] = useState<Cfg>(DEFAULT);
  return <Workspace p={p} tabs={[
    { id: "gw", label: "Gateway", content: <GatewayTab cfg={cfg} setCfg={setCfg} /> },
    { id: "kb", label: "Knowledge base & invalidation", content: <KbTab /> },
    { id: "cmp", label: "Workload comparison", content: <CompareTab /> },
    { id: "sweep", label: "Threshold tuning", content: <SweepTab /> },
  ]} />;
}
