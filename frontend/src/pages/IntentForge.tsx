import { useEffect, useState } from "react";
import { api, useAction, useApi, usePoll } from "../api";
import { useStatus, Workspace } from "../components/Layout";
import { Badge, Bars, Card, Empty, ErrorBox, Field, Json, LineChart, pct, Select, Spinner, Stat, usd } from "../components/ui";
import { bySlug } from "../projects";

const p = bySlug("intentforge");
const FIELDS = ["change_type", "component", "priority", "customer_impact", "requires_migration", "owner_team"];

function DatasetTab() {
  const { data, error, loading, reload } = useApi<any>("/api/finetune/dataset");
  const [n, setN] = useState(700);
  const [seed, setSeed] = useState(7);
  const build = useAction(async () => { await api("/api/finetune/dataset/build", { body: { n, seed } }); await reload(); });
  if (loading && !data) return <Spinner />;
  if (!data) return <ErrorBox error={error} />;
  const r = data.report;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="generated" value={r.n_generated} hint={`seed ${r.seed}`} />
        <Stat label="kept" value={r.kept} tone="good" />
        <Stat label="rejected" value={r.rejected} tone="warn" />
        <Stat label="injected bad records caught" value={`${r.injected_invalid_caught}/${r.injected_invalid}`} tone={r.injected_invalid_caught === r.injected_invalid ? "good" : "bad"} />
        <Stat label="dataset hash" value={<span className="font-mono text-base">{r.dataset_hash}</span>} hint="reproducible from seed" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Cleaning: why records were rejected">
          <Bars rows={Object.entries(r.reject_reasons).map(([k, v]) => ({ label: k, value: v as number, tone: "bg-amber-500" }))} max={Math.max(...(Object.values(r.reject_reasons) as number[]))} format={(v) => String(v)} />
          <p className="mt-3 text-xs muted">Order: schema validation → business rules (owner team must own the component; P0 cannot be low impact) → exact duplicates → near duplicates (character 5-gram Jaccard ≥ 0.85). Deduplication runs <b>before</b> splitting, so paraphrased copies can't leak from train into test.</p>
          {Object.entries(data.rejected_examples).map(([k, v]: any) => (
            <details key={k} className="mt-2 text-xs"><summary className="cursor-pointer">{k} example</summary><Json value={{ request: v[0].request, label: v[0].label, reason: v[0].reject_reason }} max={200} /></details>
          ))}
        </Card>
        <Card title="Splits (by content hash, not by order)">
          <Bars rows={Object.entries(r.splits).map(([k, v]) => ({ label: k, value: v as number }))} max={r.kept} format={(v) => String(v)} />
          <div className="mt-3 label">change_type distribution (train vs test)</div>
          <Bars rows={Object.keys(r.label_distribution.train.change_type).flatMap((k) => [
            { label: `${k} · train`, value: r.label_distribution.train.change_type[k] / r.splits.train },
            { label: `${k} · test`, value: (r.label_distribution.test.change_type[k] ?? 0) / r.splits.test, tone: "bg-indigo-500" },
          ])} format={(v) => pct(v)} max={0.4} />
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Training examples (synthetic, template-generated)">
          {data.samples.train.map((s: any) => <div key={s.id} className="mb-3"><p className="text-sm italic">“{s.request}”</p><Json value={s.label} max={160} /></div>)}
        </Card>
        <Card title="Out-of-distribution slice (hand-written, never trained on)">
          <p className="mb-2 text-xs muted">Templates produce a narrow distribution. This slice checks whether a system generalises to how people actually write.</p>
          {data.ood_samples.map((s: any) => <div key={s.id} className="mb-3"><p className="text-sm italic">“{s.request}”</p><Json value={s.label} max={160} /></div>)}
        </Card>
      </div>
      <Card title="Regenerate dataset">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="examples"><input type="number" className="input w-28" value={n} min={100} max={5000} onChange={(e) => setN(+e.target.value)} /></Field>
          <Field label="seed"><input type="number" className="input w-24" value={seed} onChange={(e) => setSeed(+e.target.value)} /></Field>
          <button className="btn" disabled={build.loading} onClick={() => build.run()}>Rebuild</button>
          <span className="text-xs muted">CLI: python -m lab.p02_finetune.data --n {n} --seed {seed}</span>
        </div>
        <ErrorBox error={build.error} />
      </Card>
    </div>
  );
}

function RunMeta({ m }: { m: any }) {
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-4">
        <Stat label="trainable params" value={m.trainable_params.toLocaleString()} hint={`${m.trainable_pct}% of ${m.total_params.toLocaleString()}`} tone="good" />
        <Stat label="frozen params" value={m.frozen_params.toLocaleString()} hint="base weights, never updated" />
        <Stat label="val loss" value={`${m.val_loss_before} → ${m.val_loss_after}`} tone="good" />
        <Stat label="train time" value={`${m.train_seconds}s`} hint={`device ${m.device}`} />
      </div>
      <div className="rounded-tl-xl rounded-br-xl border border-teal-500/40 bg-teal-50/50 p-3 text-sm dark:bg-teal-400/5">
        <div className="font-semibold">What was actually trained</div>
        <p className="mt-1 muted">{m.what_was_trained} on <span className="font-mono">{m.base_model}</span> (revision <span className="font-mono">{m.base_revision?.slice(0, 10) ?? "unknown"}</span>). LoRA r={m.lora_config.r}, α={m.lora_config.alpha} on {m.adapted_modules} modules ({m.lora_config.target_modules.join(", ")}). No API model was fine-tuned.</p>
        <p className="mt-1 text-xs muted">Frozen-weight probe <span className="font-mono">{m.weight_change_evidence.probe_base_weight}</span>: checksum {m.weight_change_evidence.checksum_before} → {m.weight_change_evidence.checksum_after} ({m.weight_change_evidence.base_weight_unchanged ? "unchanged ✓" : "CHANGED ✗"}). Mean |LoRA B| after training: {m.weight_change_evidence.lora_B_mean_abs_after.toExponential(2)} (initialised at 0).</p>
      </div>
      <details className="text-xs"><summary className="cursor-pointer muted">Full run metadata</summary><Json value={m} /></details>
    </div>
  );
}

function TrainTab() {
  const env = useApi<any>("/api/finetune/environment");
  const [hp, setHp] = useState({ epochs: 3, lr: 0.0002, r: 16, alpha: 32, max_train: "" as any });
  const [active, setActive] = useState(false);
  const runs = usePoll<any>("/api/finetune/runs", 2000, active);
  const start = useAction(async () => { const r = await api("/api/finetune/train", { body: { ...hp, max_train: hp.max_train || null } }); setActive(true); await runs.reload(); return r; });
  useEffect(() => { if (runs.data) setActive(runs.data.job_running); }, [runs.data]);
  const latest = runs.data?.runs?.[0];
  const done = runs.data?.runs?.filter((r: any) => r.state === "done") ?? [];
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <Card title="Training configuration">
          {env.data && <p className="mb-3 text-xs muted">Base model <span className="font-mono">{env.data.base_model}</span> · {env.data.base_cached ? "cached locally" : "will download (~270 MB)"} · device <b>{env.data.device}</b> · torch {String(env.data.torch)}</p>}
          <div className="grid grid-cols-2 gap-3">
            <Field label="epochs"><input type="number" className="input" min={1} max={10} value={hp.epochs} onChange={(e) => setHp({ ...hp, epochs: +e.target.value })} /></Field>
            <Field label="learning rate"><input type="number" step="0.0001" className="input" value={hp.lr} onChange={(e) => setHp({ ...hp, lr: +e.target.value })} /></Field>
            <Field label="LoRA rank r"><input type="number" className="input" min={1} max={128} value={hp.r} onChange={(e) => setHp({ ...hp, r: +e.target.value })} /></Field>
            <Field label="LoRA alpha"><input type="number" className="input" value={hp.alpha} onChange={(e) => setHp({ ...hp, alpha: +e.target.value })} /></Field>
            <Field label="max train examples" hint="blank = all"><input type="number" className="input" value={hp.max_train} onChange={(e) => setHp({ ...hp, max_train: e.target.value ? +e.target.value : "" })} /></Field>
          </div>
          <button className="btn-primary mt-3 w-full" disabled={start.loading || active || !env.data?.torch} onClick={() => start.run()}>{active ? "Training…" : "Start real LoRA training"}</button>
          <p className="mt-2 text-xs muted">Runs as a separate process on this machine. About 5 minutes for 3 epochs on an M1 CPU.</p>
          <ErrorBox error={start.error || env.error} />
        </Card>
        <Card title={latest ? `Run ${latest.run_id} · ${latest.state}` : "No runs yet"}>
          {!latest && <Empty>Start a run to see the loss curve live.</Empty>}
          {latest && (
            <>
              {latest.total > 0 && (
                <div className="mb-3">
                  <div className="h-2 overflow-hidden rounded-r-full bg-gray-100 dark:bg-white/5"><div className="h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 motion-safe:transition-all" style={{ width: `${(100 * latest.step) / latest.total}%` }} /></div>
                  <div className="mt-1 text-xs muted">step {latest.step}/{latest.total}{latest.eta_s != null && latest.state === "training" ? ` · ETA ${Math.round(latest.eta_s)}s` : ""}</div>
                </div>
              )}
              <LineChart xLabel="step" series={[
                { name: "train loss", color: "#14b8a6", points: latest.history.map((h: any) => ({ x: h.step, y: h.loss })) },
                { name: "val loss (end of epoch)", color: "#a855f7", points: latest.history.filter((h: any) => h.val_loss != null).map((h: any) => ({ x: h.step, y: h.val_loss })) },
              ]} />
              {latest.state === "failed" && <ErrorBox error={new Error(latest.error)} />}
              {latest.state === "interrupted" && <ErrorBox error={new Error("The training process stopped without finishing (killed or out of memory).")} />}
              {runs.data?.log_tail && latest.state !== "done" && <pre className="mono mt-2 max-h-32 overflow-auto rounded bg-gray-50 p-2 dark:bg-ink-pop">{runs.data.log_tail}</pre>}
            </>
          )}
        </Card>
      </div>
      {done.map((r: any) => <Card key={r.run_id} title={`Artifact: ${r.run_id}`}><RunMeta m={r.metadata} /></Card>)}
    </div>
  );
}

function EvalTab() {
  const { status } = useStatus();
  const [active, setActive] = useState(false);
  const ev = usePoll<any>("/api/finetune/evals", 3000, active);
  const runs = useApi<any>("/api/finetune/runs");
  const [detail, setDetail] = useState<string | null>(null);
  const [slice, setSlice] = useState<"test" | "ood">("ood");
  const d = useApi<any>(detail ? `/api/finetune/evals/${detail}` : null);
  const go = useAction(async (system: string) => { const r = await api("/api/finetune/evaluate", { body: { system } }); if (!r.done) setActive(true); await ev.reload(); return r; });
  useEffect(() => { if (ev.data) setActive(ev.data.job_running); }, [ev.data]);
  const adapters = (runs.data?.runs ?? []).filter((r: any) => r.state === "done").map((r: any) => `adapter:${r.run_id}`);
  const systems = ["rules", "base_prompted", ...adapters, ...(status?.providers.filter((x) => x.usable).map((x) => `api:${x.name}`) ?? [])];
  const evals: any[] = ev.data?.evals ?? [];
  return (
    <div className="space-y-4">
      <Card title="Run evaluations on held-out data">
        <div className="flex flex-wrap gap-2">
          {systems.map((s) => <button key={s} className={s.startsWith("adapter") ? "btn-primary" : "btn"} disabled={go.loading || active} onClick={() => go.run(s)}>{s}{s.startsWith("api") ? " (paid)" : ""}</button>)}
        </div>
        <p className="mt-2 text-xs muted">Model systems run as a background process (about 1 to 3 minutes on CPU). <b>base_prompted</b> is the same SmolLM2 weights with a long instruction prompt: the honest "before" for the adapter.</p>
        {active && <div className="mt-2"><Spinner label="Evaluating" /><pre className="mono mt-1 max-h-24 overflow-auto">{ev.data?.log_tail}</pre></div>}
        <ErrorBox error={go.error} />
      </Card>
      {evals.length === 0 ? <Empty>No evaluations yet. Start with <b>rules</b>, which is instant.</Empty> : (
        <Card title="Baseline vs fine-tuned" aside={<Select value={slice} onChange={setSlice} options={[["ood", "OOD slice (20 hand-written)"], ["test", "held-out test (synthetic)"]]} />}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-xs">
              <thead className="muted"><tr><th className="py-1">system</th><th>JSON valid</th><th>schema valid</th><th>all fields exact</th>{FIELDS.map((f) => <th key={f}>{f.replace("_", " ")}</th>)}<th>summary F1</th><th>prompt tok</th><th>ms/example</th><th>general Qs</th><th>cost</th><th /></tr></thead>
              <tbody>
                {evals.map((e) => {
                  const s = e.slices[slice];
                  return (
                    <tr key={e.system} className="border-t border-gray-100 dark:border-white/5">
                      <td className="py-1.5 font-mono">{e.system}</td><td>{pct(s.json_valid)}</td><td>{pct(s.schema_valid)}</td><td className="font-semibold">{pct(s.exact_all_fields)}</td>
                      {FIELDS.map((f) => <td key={f}>{pct(s.per_field[f])}</td>)}
                      <td>{s.summary_f1.toFixed(2)}</td><td>{e.prompt_tokens_avg ?? "–"}</td><td>{e.latency_ms_per_example}</td>
                      <td>{e.general_accuracy == null ? "–" : pct(e.general_accuracy)}</td><td>{e.cost_usd == null ? "–" : usd(e.cost_usd)}</td>
                      <td><button className="link" onClick={() => setDetail(e.system.replace(":", "_"))}>outputs</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div><div className="label">All-fields exact match · {slice}</div><Bars rows={evals.map((e) => ({ label: e.system, value: e.slices[slice].exact_all_fields, tone: e.system.startsWith("adapter") ? "bg-purple-500" : undefined }))} format={(v) => pct(v)} /></div>
            <div><div className="label">Schema-valid output · {slice}</div><Bars rows={evals.map((e) => ({ label: e.system, value: e.slices[slice].schema_valid, tone: "bg-indigo-500" }))} format={(v) => pct(v)} /></div>
          </div>
          <p className="mt-3 text-xs muted">Read the OOD column before trusting the synthetic test column. A system that wins only on synthetic data has learned the templates, not the task. "general Qs" is the forgetting check: base and adapter answer the same 12 simple questions.</p>
        </Card>
      )}
      {detail && d.data && (
        <Card title={`Outputs: ${d.data.system} · ${slice}`} aside={<button className="link text-xs" onClick={() => setDetail(null)}>close</button>}>
          <div className="space-y-3">
            {d.data.slices[slice].examples.slice(0, 20).map((x: any) => (
              <div key={x.id} className="rounded-tl-xl rounded-br-xl border border-gray-200 p-2 text-xs dark:border-white/10">
                <div className="flex flex-wrap items-center gap-1"><span className="font-mono">{x.id}</span>{x.exact_all_fields ? <Badge tone="teal">exact</Badge> : x.schema_valid ? <Badge tone="amber">valid, wrong fields</Badge> : x.json_valid ? <Badge tone="rose">schema invalid</Badge> : <Badge tone="rose">not JSON</Badge>}</div>
                <p className="mt-1 italic">{x.request}</p>
                <div className="mt-1 flex flex-wrap gap-1">{FIELDS.map((f) => <Badge key={f} tone={x.per_field[f] ? "teal" : "rose"}>{f}: {String(x.gold[f])}</Badge>)}</div>
                <pre className="mono mt-1 whitespace-pre-wrap rounded bg-gray-50 p-1.5 dark:bg-ink-pop">{x.output}</pre>
                {x.error && <div className="text-rose-600">{x.error}</div>}
              </div>
            ))}
          </div>
          {d.data.general && (
            <details className="mt-3 text-xs"><summary className="cursor-pointer">General-capability answers ({pct(d.data.general.accuracy)})</summary>
              <ul className="mt-1 space-y-0.5">{d.data.general.answers.map((a: any) => <li key={a.q}>{a.correct ? "✓" : "✗"} {a.q} → <span className="font-mono">{a.answer}</span></li>)}</ul>
            </details>
          )}
        </Card>
      )}
    </div>
  );
}

export default function IntentForge() {
  return <Workspace p={p} tabs={[
    { id: "data", label: "Dataset pipeline", content: <DatasetTab /> },
    { id: "train", label: "Train (LoRA)", content: <TrainTab /> },
    { id: "eval", label: "Baseline vs fine-tuned", content: <EvalTab /> },
  ]} />;
}
