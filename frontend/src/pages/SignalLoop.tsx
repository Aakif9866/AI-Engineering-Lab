import { useState } from "react";
import { Link } from "react-router-dom";
import { api, useAction, useApi } from "../api";
import { Workspace } from "../components/Layout";
import { Badge, Bars, Card, Empty, ErrorBox, Field, Json, pct, Select, Spinner, Stat, Toggle } from "../components/ui";
import { bySlug } from "../projects";

const p = bySlug("signalloop");
const CATS = ["incorrect", "unsupported", "incomplete", "outdated_source", "formatting", "harmful", "other"];

function AssistantTab() {
  const rel = useApi<any[]>("/api/feedback/releases");
  const [user, setUser] = useState("me");
  const [q, setQ] = useState("At what time did the R-17 temperature first cross 8 degrees?");
  const [rating, setRating] = useState<number | null>(null);
  const [cats, setCats] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [correction, setCorrection] = useState("");
  const [consent, setConsent] = useState(false);
  const ask = useAction(async () => { setRating(null); setCats([]); setComment(""); const r = await api("/api/feedback/ask", { body: { question: q, user } }); setCorrection(r.answer); return r; });
  const send = useAction(() => api("/api/feedback/rate", { body: { interaction_id: (ask.result as any).interaction_id, user, rating, categories: cats, comment, correction: correction === (ask.result as any).answer ? "" : correction, consent } }));
  const signal = useAction((kind: string) => api("/api/feedback/signal", { body: { interaction_id: (ask.result as any).interaction_id, user, kind } }));
  const seed = useAction(() => api("/api/feedback/demo-seed", { method: "POST" }));
  const r: any = ask.result;
  const prod = rel.data?.find((x) => x.status === "production");
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
      <div className="min-w-0 space-y-4">
        <Card title="Research assistant" aside={prod && <Badge tone="teal">production: {prod.name}</Badge>}>
          <div className="grid gap-3 sm:grid-cols-[1fr_8rem]">
            <Field label="Question about the Depot 7 investigation"><input className="input" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
            <Field label="User id" hint="stored only as a salted hash"><input className="input" value={user} onChange={(e) => setUser(e.target.value)} /></Field>
          </div>
          <button className="btn-primary mt-3" disabled={ask.loading} onClick={() => ask.run()}>Ask</button>
          <ErrorBox error={ask.error} />
        </Card>
        {r && (
          <Card title="Answer" aside={<Link className="link text-xs" to={`/tracelens?trace=${r.trace_id}`}>trace ↗</Link>}>
            <p className={`text-sm ${r.abstained ? "text-amber-700 dark:text-amber-300" : ""}`}>{r.answer}</p>
            <div className="mt-2 flex flex-wrap gap-1">{r.hits.map((h: any) => <Badge key={h.chunk_id}>{h.ref} {h.doc_id}</Badge>)}</div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button className={`btn ${rating === 1 ? "!bg-teal-600 !text-white" : ""}`} onClick={() => setRating(1)} aria-pressed={rating === 1}>👍 Helpful</button>
              <button className={`btn ${rating === -1 ? "!bg-rose-600 !border-rose-600 !text-white" : ""}`} onClick={() => setRating(-1)} aria-pressed={rating === -1}>👎 Not right</button>
              <span className="mx-1 h-6 w-px bg-gray-200 dark:bg-white/10" />
              <button className="link text-xs" onClick={() => { signal.run("regenerate"); ask.run(); }}>regenerate</button>
              <button className="link text-xs" onClick={() => { navigator.clipboard?.writeText(r.answer); signal.run("copy"); }}>copy</button>
              {signal.result && <span className="text-[11px] muted">implicit signal “{(signal.result as any).kind}” recorded</span>}
            </div>
            {rating !== null && (
              <div className="mt-3 space-y-2 rounded-tl-xl rounded-br-xl border border-gray-200 p-3 dark:border-white/10">
                {rating < 0 && <div className="flex flex-wrap gap-x-3">{CATS.map((c) => <Toggle key={c} checked={cats.includes(c)} onChange={(v) => setCats(v ? [...cats, c] : cats.filter((x) => x !== c))} label={c.replace("_", " ")} />)}</div>}
                <Field label="Comment (optional)"><input className="input" value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
                {rating < 0 && <Field label="Edit the answer into what it should have said" hint="the highest-value signal: an (original, corrected) pair"><textarea className="input min-h-[80px]" value={correction} onChange={(e) => setCorrection(e.target.value)} /></Field>}
                <Toggle checked={consent} onChange={setConsent} label="Allow this to be used for training (reviewed first)" />
                <button className="btn-primary" disabled={send.loading || (rating < 0 && cats.length === 0)} onClick={() => send.run()}>Send feedback</button>
                {send.result && (
                  <div className="text-xs">
                    Saved as <Badge tone={(send.result as any).status === "duplicate" ? "amber" : "teal"}>{(send.result as any).status}</Badge>
                    {(send.result as any).contains_pii && <Badge tone="violet">PII redacted: {(send.result as any).pii_kinds.join(", ")}</Badge>}
                    {(send.result as any).risk >= 0.4 && <Badge tone="rose">flagged suspicious</Badge>}
                    <span className="ml-1 muted">It goes to the review queue. Nothing trains automatically.</span>
                  </div>
                )}
                <ErrorBox error={send.error} />
              </div>
            )}
          </Card>
        )}
      </div>
      <Card title="Cold start">
        <p className="text-sm muted">No real users yet? Seed eight <b>simulated</b> feedback items: a duplicate, a correction containing a phone number, a poisoning attempt, and a power user who dominates volume (a bias trap).</p>
        <button className="btn mt-3 w-full" disabled={seed.loading} onClick={() => seed.run()}>Seed simulated feedback</button>
        {seed.result && <p className="mt-2 text-xs">Created {(seed.result as any).created} items. Open the review queue.</p>}
        <ErrorBox error={seed.error} />
      </Card>
    </div>
  );
}

function ReviewTab() {
  const { data, reload, loading } = useApi<any>("/api/feedback/queue");
  const [draft, setDraft] = useState<Record<string, { must: string; abstain: boolean; dataset: string }>>({});
  const act = useAction(async (id: string, action: string) => {
    const d = draft[id] ?? { must: "", abstain: false, dataset: "eval" };
    const must = d.must.trim() ? d.must.split(";").map((g) => g.split("|").map((x) => x.trim()).filter(Boolean)).filter((g) => g.length) : null;
    const r = await api(`/api/feedback/items/${id}/review`, { body: { action, reviewer: "me", must_contain: must, abstain: d.abstain, dataset: d.dataset } });
    await reload();
    return r;
  });
  const del = useAction(async (id: string) => { const r = await api(`/api/feedback/items/${id}`, { method: "DELETE" }); await reload(); return r; });
  if (loading && !data) return <Spinner />;
  return (
    <div className="space-y-4">
      <ErrorBox error={act.error || del.error} />
      {del.result && <div className="text-xs">Deletion: {JSON.stringify(del.result)}</div>}
      {!data?.clusters?.length ? <Empty>The queue is empty. Leave feedback or seed simulated feedback on the Assistant tab.</Empty> : data.clusters.map((c: any, i: number) => (
        <Card key={i} title={<>Issue cluster: <span className="text-teal-700 dark:text-teal-300">{c.category}</span> · “{c.example_question}”</>} aside={<div className="flex gap-1"><Badge tone="rose">severity {c.severity}</Badge><Badge>{c.size} reports · {c.users} users</Badge></div>}>
          <div className="space-y-2">{c.items.map((f: any) => {
            const d = draft[f.id] ?? { must: "", abstain: false, dataset: "eval" };
            const set = (k: string, v: any) => setDraft({ ...draft, [f.id]: { ...d, [k]: v } });
            return (
              <div key={f.id} className="rounded-tl-xl rounded-br-xl border border-gray-200 p-3 text-xs dark:border-white/10">
                <div className="flex flex-wrap items-center gap-1"><span className="font-mono">{f.id}</span>{f.status === "duplicate" && <Badge tone="amber">duplicate of {f.duplicate_of}</Badge>}{f.contains_pii ? <Badge tone="violet">contained PII (redacted)</Badge> : null}{f.risk >= 0.4 && <Badge tone="rose">suspicious {f.risk.toFixed(2)}</Badge>}{f.consent ? <Badge tone="teal">training consent</Badge> : <Badge>no training consent</Badge>}<span className="muted">user {f.user_hash}</span></div>
                <div className="mt-1"><span className="label inline">Answer given</span> {f.answer}</div>
                {f.comment && <div><span className="label inline">Comment</span> {f.comment}</div>}
                {f.correction && <div><span className="label inline">Correction</span> <span className="text-teal-800 dark:text-teal-200">{f.correction}</span></div>}
                <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
                  <input className="input" placeholder="facts a correct answer must contain: 01:35|1:35 ; 8 degrees" value={d.must} onChange={(e) => set("must", e.target.value)} />
                  <Toggle checked={d.abstain} onChange={(v) => set("abstain", v)} label="should abstain" />
                  <Select value={d.dataset} onChange={(v) => set("dataset", v)} options={[["eval", "→ eval set"], ["train", "→ training set"]]} />
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button className="btn !min-h-[32px] !py-1 text-xs" onClick={() => act.run(f.id, "approve")}>approve</button>
                  <button className="btn !min-h-[32px] !py-1 text-xs" onClick={() => act.run(f.id, "reject")}>reject</button>
                  <button className="btn !min-h-[32px] !py-1 text-xs" onClick={() => act.run(f.id, "duplicate")}>close as duplicate</button>
                  <button className="ml-auto text-xs text-rose-600 hover:underline" onClick={() => del.run(f.id)}>delete (user request)</button>
                </div>
              </div>
            );
          })}</div>
        </Card>
      ))}
    </div>
  );
}

function AnalyticsTab() {
  const { data, error } = useApi<any>("/api/feedback/analytics");
  if (!data) return error ? <ErrorBox error={error} /> : <Spinner />;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="participation" value={pct(data.participation_rate)} hint={`${data.feedback} feedback / ${data.interactions} interactions`} />
        <Stat label="ratings" value={`${data.ratings.up} 👍 · ${data.ratings.down} 👎`} hint="explicit feedback skews to the extremes (J-curve)" />
        <Stat label="top user's share of feedback" value={pct(data.top_user_share)} tone={(data.top_user_share ?? 0) > 0.3 ? "warn" : undefined} hint="bias risk: one user steering the data" />
        <Stat label="flywheel latency (median)" value={data.flywheel_latency_hours_median == null ? "n/a" : `${data.flywheel_latency_hours_median.toFixed(2)} h`} hint="feedback → approved example" />
        <Stat label="PII flagged" value={data.pii_flagged} />
        <Stat label="suspicious (injection-like)" value={data.suspicious} tone={data.suspicious ? "bad" : undefined} />
        <Stat label="approved by top contributor" value={pct(data.approved_top_user_share)} />
        <Stat label="open in queue" value={data.status.new + data.status.duplicate} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Recurring failure categories">{Object.keys(data.categories).length ? <Bars rows={Object.entries(data.categories).map(([k, v]) => ({ label: k, value: v as number, tone: "bg-rose-500" }))} max={Math.max(...(Object.values(data.categories) as number[]))} format={(v) => String(v)} /> : <Empty>None yet</Empty>}</Card>
        <Card title="Implicit signals">{data.signals.length ? data.signals.map((s: any) => <div key={s.kind} className="flex justify-between border-t border-gray-100 py-1 text-sm dark:border-white/5"><span>{s.kind}</span><span className="tabular-nums">{s.n}{s.sim != null && <span className="muted"> · mean similarity to the original {s.sim.toFixed(2)}</span>}</span></div>) : <Empty>None yet</Empty>}
          <p className="mt-2 text-xs muted">Regenerations are noisy: the user may just be exploring. Calibrate implicit signals against explicit ratings before trusting them.</p></Card>
      </div>
      <Card title="Review status"><Bars rows={Object.entries(data.status).map(([k, v]) => ({ label: k, value: v as number }))} max={Math.max(1, data.feedback)} format={(v) => String(v)} /></Card>
    </div>
  );
}

function ReleaseTab() {
  const rel = useApi<any[]>("/api/feedback/releases");
  const sets = useApi<any[]>("/api/feedback/evalsets");
  const exs = useApi<any[]>("/api/feedback/examples");
  const [name, setName] = useState("frozen-v1");
  const [cand, setCand] = useState({ name: "hybrid-v2", strategy: "hybrid", k: 5, reranker: "overlap", prefer_current: true, min_coverage: 0.35 });
  const [setId, setSetId] = useState("");
  const [days, setDays] = useState(30);
  const freeze = useAction(async () => { const r = await api("/api/feedback/evalsets", { body: { name } }); await sets.reload(); setSetId(r.id); return r; });
  const create = useAction(async () => { const r = await api("/api/feedback/releases", { body: cand }); await rel.reload(); return r; });
  const gate = useAction(async (id: string) => { const r = await api(`/api/feedback/releases/${id}/gate?evalset_id=${setId}`, { method: "POST" }); await rel.reload(); return r; });
  const promote = useAction(async (id: string, rollback = false) => { const r = await api(`/api/feedback/releases/${id}/promote?rollback=${rollback}`, { method: "POST" }); await rel.reload(); return r; });
  const retention = useAction(() => api(`/api/feedback/retention?days=${days}`, { method: "POST" }));
  const g: any = gate.result;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Approved examples (${exs.data?.length ?? 0})`}>
          {!exs.data?.length ? <Empty>Approve feedback in the review queue first.</Empty> : exs.data.map((e) => (
            <div key={e.id} className="border-t border-gray-100 py-1 text-xs dark:border-white/5"><Badge tone={e.dataset === "train" ? "violet" : "teal"}>{e.dataset}</Badge> {e.question} <span className="muted">must contain {JSON.stringify(e.must_contain_json)}{e.abstain ? " · abstain" : ""}</span></div>
          ))}
        </Card>
        <Card title="Frozen evaluation sets">
          <div className="flex gap-2"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /><button className="btn-primary whitespace-nowrap" onClick={() => freeze.run()}>Freeze snapshot</button></div>
          <p className="mt-1 text-[11px] muted">24 seed benchmark items (cold start) plus every approved eval example. Content-hashed and immutable; deleting source feedback invalidates the set.</p>
          <div className="mt-2 space-y-1">{sets.data?.map((s) => (
            <label key={s.id} className="flex cursor-pointer items-center gap-2 text-xs"><input type="radio" name="evalset" checked={setId === s.id} onChange={() => setSetId(s.id)} disabled={!!s.invalidated_reason} className="accent-teal-600" />
              <b>{s.name}</b> <span className="font-mono">#{s.content_hash}</span> {s.n_items} items ({s.n_feedback} from feedback) {s.intact ? <Badge tone="teal">intact</Badge> : <Badge tone="rose">hash mismatch</Badge>}{s.invalidated_reason && <Badge tone="rose">{s.invalidated_reason}</Badge>}</label>
          ))}</div>
          <ErrorBox error={freeze.error} />
        </Card>
      </div>
      <Card title="Releases and the gate">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Field label="Candidate name"><input className="input" value={cand.name} onChange={(e) => setCand({ ...cand, name: e.target.value })} /></Field>
          <Field label="Retrieval"><Select value={cand.strategy} onChange={(v) => setCand({ ...cand, strategy: v })} options={["hybrid", "bm25", "dense"]} /></Field>
          <Field label="k"><input type="number" className="input" min={1} max={10} value={cand.k} onChange={(e) => setCand({ ...cand, k: +e.target.value })} /></Field>
          <Field label="Reranker"><Select value={cand.reranker} onChange={(v) => setCand({ ...cand, reranker: v })} options={["overlap", "none"]} /></Field>
          <Field label="Abstention gate" hint="0 = never abstain"><input type="number" step={0.05} className="input" min={0} max={1} value={cand.min_coverage} onChange={(e) => setCand({ ...cand, min_coverage: +e.target.value })} /></Field>
          <div className="flex items-end"><button className="btn w-full" onClick={() => create.run()}>Create candidate</button></div>
        </div>
        <ErrorBox error={create.error || gate.error || promote.error} />
        <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[640px] text-left text-xs">
          <thead className="muted"><tr><th className="py-1">release</th><th>status</th><th>config</th><th>gate</th><th /></tr></thead>
          <tbody>{rel.data?.map((r) => (
            <tr key={r.id} className="border-t border-gray-100 dark:border-white/5">
              <td className="py-1.5 font-medium">{r.name}</td><td><Badge tone={r.status === "production" ? "teal" : r.status === "candidate" ? "amber" : "gray"}>{r.status}</Badge></td>
              <td className="font-mono">{r.config_json.strategy}/k{r.config_json.k}/{r.config_json.reranker}/gate {r.config_json.min_coverage}</td>
              <td>{r.gate_json ? (r.gate_json.passed ? <Badge tone="teal">passed on {r.gate_json.evalset}</Badge> : <Badge tone="rose">blocked</Badge>) : "–"}</td>
              <td className="space-x-2 whitespace-nowrap">
                {r.status !== "production" && <button className="link" disabled={!setId} onClick={() => gate.run(r.id)}>{setId ? "run gate" : "freeze a set first"}</button>}
                {r.status === "candidate" && <button className="link" onClick={() => promote.run(r.id)}>promote</button>}
                {r.status === "retired" && <button className="link" onClick={() => promote.run(r.id, true)}>roll back to this</button>}
              </td>
            </tr>
          ))}</tbody>
        </table></div>
        <p className="mt-2 text-[11px] muted">"promote" is always clickable on purpose: the backend refuses (HTTP 403) unless a passing gate is on file.</p>
      </Card>
      {g && (
        <Card title={<>Gate verdict: {g.passed ? <Badge tone="teal">PASS</Badge> : <Badge tone="rose">BLOCKED</Badge>} <span className="text-xs muted">vs {g.baseline_release} on {g.evalset} #{g.evalset_hash}</span></>}>
          <table className="w-full text-left text-xs"><thead className="muted"><tr><th className="py-1">check</th><th>rule</th><th>production</th><th>candidate</th><th /></tr></thead>
            <tbody>{g.checks.map((c: any) => (
              <tr key={c.metric} className="border-t border-gray-100 dark:border-white/5"><td className="py-1 font-mono">{c.metric}</td><td>{c.rule}</td><td>{typeof c.baseline === "number" ? c.baseline.toFixed?.(3) ?? c.baseline : String(c.baseline)}</td><td>{typeof c.candidate === "number" ? c.candidate.toFixed?.(3) ?? c.candidate : String(c.candidate)}</td><td>{c.passed ? "✓" : <Badge tone="rose">fail</Badge>}</td></tr>
            ))}</tbody></table>
          {g.changed_rows.length > 0 && <details className="mt-2 text-xs"><summary className="cursor-pointer">{g.changed_rows.length} items changed outcome</summary><Json value={g.changed_rows} max={240} /></details>}
        </Card>
      )}
      <Card title="Retention">
        <div className="flex flex-wrap items-end gap-2"><Field label="Delete unreviewed / rejected feedback older than (days)"><input type="number" className="input w-28" value={days} onChange={(e) => setDays(+e.target.value)} /></Field><button className="btn" onClick={() => retention.run()}>Apply retention</button></div>
        {retention.result && <p className="mt-2 text-xs">{JSON.stringify(retention.result)}</p>}
      </Card>
    </div>
  );
}

export default function SignalLoop() {
  return <Workspace p={p} tabs={[
    { id: "assistant", label: "Assistant & feedback", content: <AssistantTab /> },
    { id: "review", label: "Review queue", content: <ReviewTab /> },
    { id: "analytics", label: "Analytics", content: <AnalyticsTab /> },
    { id: "release", label: "Datasets & release gate", content: <ReleaseTab /> },
  ]} />;
}
