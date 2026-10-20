import { useState } from "react";
import { Link } from "react-router-dom";
import { api, useAction, useApi } from "../api";
import { useStatus, Workspace } from "../components/Layout";
import { Badge, Bars, Card, Empty, ErrorBox, Field, ms, pct, Select, Spinner, Stat, Toggle, usd } from "../components/ui";
import { bySlug } from "../projects";

const p = bySlug("evidence-atlas");

type Cfg = {
  index: { chunk_size: number; overlap: number; strategy: "fixed" | "section" };
  retrieval: { strategy: "bm25" | "dense" | "hybrid"; k: number; candidates: number; reranker: "none" | "overlap" | "cross-encoder"; context_budget: number; prefer_current: boolean; role: "staff" | "investigator" };
};
const DEFAULT: Cfg = {
  index: { chunk_size: 120, overlap: 20, strategy: "section" },
  retrieval: { strategy: "hybrid", k: 5, candidates: 30, reranker: "overlap", context_budget: 600, prefer_current: true, role: "investigator" },
};

function DocBadges({ h }: { h: any }) {
  return (
    <>
      {h.status !== "current" && <Badge tone={h.status === "superseded" ? "amber" : "rose"}>{h.status}</Badge>}
      {h.access === "restricted" && <Badge tone="violet">restricted</Badge>}
      <Badge>{h.type}</Badge>
      {h.date && <span className="text-[11px] italic muted">{h.date}</span>}
    </>
  );
}

function ConfigPanel({ cfg, set }: { cfg: Cfg; set: (c: Cfg) => void }) {
  const ix = (k: keyof Cfg["index"], v: any) => set({ ...cfg, index: { ...cfg.index, [k]: v } });
  const rt = (k: keyof Cfg["retrieval"], v: any) => set({ ...cfg, retrieval: { ...cfg.retrieval, [k]: v } });
  return (
    <Card title="Pipeline configuration" aside={<button className="link text-xs" onClick={() => set(DEFAULT)}>reset</button>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Chunking"><Select value={cfg.index.strategy} onChange={(v) => ix("strategy", v)} options={[["section", "section-aware"], ["fixed", "fixed window"]]} /></Field>
        <Field label={`Chunk size: ${cfg.index.chunk_size} words`}><input type="range" className="w-full accent-teal-600" min={30} max={300} step={10} value={cfg.index.chunk_size} onChange={(e) => ix("chunk_size", +e.target.value)} /></Field>
        <Field label={`Overlap: ${cfg.index.overlap}`}><input type="range" className="w-full accent-teal-600" min={0} max={80} step={5} value={cfg.index.overlap} onChange={(e) => ix("overlap", +e.target.value)} /></Field>
        <Field label="Retrieval"><Select value={cfg.retrieval.strategy} onChange={(v) => rt("strategy", v)} options={[["hybrid", "hybrid (RRF)"], ["bm25", "BM25 only"], ["dense", "dense only"]]} /></Field>
        <Field label="Reranker"><Select value={cfg.retrieval.reranker} onChange={(v) => rt("reranker", v)} options={[["overlap", "idf coverage"], ["none", "none"], ["cross-encoder", "cross-encoder (downloads ~90MB)"]]} /></Field>
        <Field label={`Top k: ${cfg.retrieval.k}`}><input type="range" className="w-full accent-teal-600" min={1} max={10} value={cfg.retrieval.k} onChange={(e) => rt("k", +e.target.value)} /></Field>
        <Field label={`Context budget: ${cfg.retrieval.context_budget} words`}><input type="range" className="w-full accent-teal-600" min={100} max={2000} step={50} value={cfg.retrieval.context_budget} onChange={(e) => rt("context_budget", +e.target.value)} /></Field>
        <Field label="Role (ACL)" hint="staff cannot see restricted docs"><Select value={cfg.retrieval.role} onChange={(v) => rt("role", v)} options={["investigator", "staff"]} /></Field>
      </div>
      <Toggle checked={cfg.retrieval.prefer_current} onChange={(v) => rt("prefer_current", v)} label="Demote superseded / unverified documents" />
    </Card>
  );
}

function AskTab({ cfg, setCfg }: { cfg: Cfg; setCfg: (c: Cfg) => void }) {
  const { status } = useStatus();
  const { data: bench } = useApi<any[]>("/api/rag/benchmark");
  const [q, setQ] = useState("Based on the telephone log and the contract, did FrostLine meet its response SLA?");
  const [useLlm, setUseLlm] = useState(false);
  const [focus, setFocus] = useState<number | null>(null);
  const ask = useAction((body: any) => api("/api/rag/ask", { body }));
  const cmp = useAction(async () => Promise.all((["bm25", "dense", "hybrid"] as const).map((s) => api("/api/rag/ask", { body: { question: q, index: cfg.index, retrieval: { ...cfg.retrieval, strategy: s } } }))));
  const r: any = ask.result;
  const llmReady = !!status?.default_provider;

  return (
    <div className="grid gap-4 xl:grid-cols-[22rem_1fr]">
      <div className="space-y-4">
        <ConfigPanel cfg={cfg} set={setCfg} />
      </div>
      <div className="min-w-0 space-y-4">
        <Card title="Ask the corpus">
          <textarea className="input min-h-[70px]" value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} />
          <div className="mt-2 flex flex-wrap gap-1">
            {bench?.slice(0, 24).filter((_, i) => [1, 3, 9, 10, 18, 19, 20, 21].includes(i)).map((b) => (
              <button key={b.id} className="rounded-tl-md rounded-br-md border border-gray-200 px-2 py-1 text-[11px] hover:border-teal-500 dark:border-white/10" onClick={() => setQ(b.question)} title={b.type}>
                {b.id} · {b.type}
              </button>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Toggle checked={useLlm} onChange={setUseLlm} disabled={!llmReady} label={`Generate with LLM${llmReady ? ` (${status?.default_provider})` : ""}`} hint={llmReady ? "one paid call, ~1–2k tokens" : "offline: extractive generator"} />
            <button className="btn-primary ml-auto" disabled={ask.loading || q.trim().length < 3} onClick={() => { setFocus(null); ask.run({ question: q, ...cfg, use_llm: useLlm }); }}>Retrieve & answer</button>
            <button className="btn" disabled={cmp.loading} onClick={() => cmp.run()}>Compare strategies</button>
          </div>
        </Card>
        <ErrorBox error={ask.error || cmp.error} />
        {ask.loading && <Spinner label="Retrieving" />}

        {cmp.result && (
          <Card title="Same question, three retrieval strategies (offline generator)">
            <div className="grid gap-3 md:grid-cols-3">
              {(cmp.result as any[]).map((res) => (
                <div key={res.retrieval_config.strategy} className="min-w-0 rounded-tl-xl rounded-br-xl border border-gray-200 p-3 dark:border-white/10">
                  <div className="mb-1 text-sm font-semibold">{res.retrieval_config.strategy}</div>
                  <ol className="list-decimal space-y-0.5 pl-4 text-xs">{res.hits.map((h: any) => <li key={h.chunk_id} className="truncate">{h.doc_id}</li>)}</ol>
                  <div className={`mt-2 text-xs ${res.abstained ? "text-amber-600 dark:text-amber-400" : ""}`}>{res.answer.slice(0, 160)}</div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {r && (
          <>
            <Card
              title="Answer"
              aside={<div className="flex flex-wrap gap-1"><Badge tone={r.generator.startsWith("llm") ? "violet" : "gray"}>{r.generator}</Badge><Badge>{r.embedder.split("/").pop()}</Badge><Link className="link text-xs" to={`/tracelens?trace=${r.trace_id}`}>trace ↗</Link></div>}
            >
              {r.abstained ? (
                <div className="rounded-tl-xl rounded-br-xl border border-amber-400/50 bg-amber-50 p-3 text-sm dark:bg-amber-400/10">
                  <div className="font-semibold text-amber-800 dark:text-amber-200">Not enough evidence to answer.</div>
                  <div className="mt-1 text-amber-800/90 dark:text-amber-200/90">{r.answer}</div>
                  {r.reason && <div className="mt-1 text-xs muted">Why: {r.reason}</div>}
                  <div className="mt-2 text-xs muted">The system refuses instead of guessing. The passages it did retrieve are listed below so you can check them yourself.</div>
                </div>
              ) : (
                <p className="text-sm leading-relaxed">
                  {r.answer.split(/(\[S\d+\])/).map((part: string, i: number) => {
                    const m = part.match(/\[S(\d+)\]/);
                    if (!m) return <span key={i}>{part}</span>;
                    const n = +m[1];
                    const ok = n >= 1 && n <= r.hits.length;
                    return <button key={i} onClick={() => setFocus(n)} className={`mx-0.5 rounded px-1 font-mono text-[11px] ${ok ? "bg-teal-100 text-teal-800 hover:bg-teal-200 dark:bg-teal-400/15 dark:text-teal-200" : "bg-rose-100 text-rose-700 line-through"}`} title={ok ? r.hits[n - 1].doc_id : "cites a passage that was never provided"}>S{n}</button>;
                  })}
                </p>
              )}
              {r.usage?.truncated && <div className="mt-2 text-xs text-rose-600">Warning: the provider stopped at max_tokens; this answer is truncated.</div>}
              {!r.abstained && r.verification?.sentences && (
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  <Stat label="Citation validity" value={pct(r.verification.citation_validity)} tone={r.verification.citation_validity === 1 ? "good" : "bad"} hint={`${r.verification.valid_citations}/${r.verification.citations} resolve to provided passages`} />
                  <Stat label="Groundedness (lexical)" value={pct(r.verification.groundedness)} tone={r.verification.groundedness >= 0.8 ? "good" : "warn"} hint="sentences whose words and numbers appear in cited passages" />
                  <Stat label="Model usage" value={r.usage?.input_tokens != null ? `${r.usage.input_tokens}→${r.usage.output_tokens}` : "offline"} hint={r.usage?.input_tokens != null ? `${usd(r.usage.cost_usd)} · ${ms(r.usage.latency_ms)} · cached ${r.usage.cached_tokens ?? 0} tok · ${r.usage.cost_source}` : "no tokens spent"} />
                </div>
              )}
              {!r.abstained && r.verification?.sentences && (
                <details className="mt-3 text-xs">
                  <summary className="cursor-pointer muted">Per-sentence verification</summary>
                  <table className="mt-2 w-full text-left">
                    <thead className="muted"><tr><th className="py-1 pr-2">Sentence</th><th>cites</th><th>words</th><th>numbers</th><th>verdict</th></tr></thead>
                    <tbody>
                      {r.verification.sentences.map((s: any, i: number) => (
                        <tr key={i} className="border-t border-gray-100 align-top dark:border-white/5">
                          <td className="py-1 pr-2">{s.sentence}</td><td>{s.cites.join(",") || "–"}</td><td>{s.word_support}</td><td>{s.numbers_supported ? "✓" : "✗"}</td>
                          <td>{s.supported ? <Badge tone="teal">supported</Badge> : <Badge tone="amber">check</Badge>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}
            </Card>

            <Card title={`Retrieved passages (${r.hits.length})`} aside={<span className="text-xs muted">{r.retrieval_config.strategy} · rerank {r.retrieval_config.reranker} · role {r.retrieval_config.role}</span>}>
              {r.hits.length === 0 && <Empty>No passages passed the access filter and ranking.</Empty>}
              <div className="space-y-2">
                {r.hits.map((h: any, i: number) => (
                  <div key={h.chunk_id} className={`rounded-tl-xl rounded-br-xl border p-3 transition-colors duration-200 ${focus === i + 1 ? "border-teal-500 bg-teal-50/60 dark:bg-teal-400/10" : "border-gray-200 dark:border-white/10"}`}>
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      <span className="font-mono text-xs font-semibold text-teal-700 dark:text-teal-300">S{i + 1}</span>
                      <span className="text-sm font-medium">{h.title}</span>
                      <DocBadges h={h} />
                    </div>
                    <p className="whitespace-pre-line text-xs muted line-clamp-6">{h.text}</p>
                    <div className="mt-2 flex flex-wrap gap-3 font-mono text-[11px] muted">
                      <span>final {h.score}</span>
                      {Object.entries(h.scores).map(([k, v]) => <span key={k}>{k} {String(v)}</span>)}
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            {r.prompt?.length > 0 && (
              <details className="card text-xs">
                <summary className="cursor-pointer text-sm font-semibold">Exact prompt sent to the model</summary>
                {r.prompt.map((m: any, i: number) => <pre key={i} className="mono mt-2 whitespace-pre-wrap rounded bg-gray-50 p-2 dark:bg-ink-pop"><b>{m.role}</b>{"\n"}{m.content}</pre>)}
              </details>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function BenchmarkTab({ cfg }: { cfg: Cfg }) {
  const ev = useAction(() => api("/api/rag/evaluate", { body: cfg }));
  const r: any = ev.result;
  return (
    <div className="space-y-4">
      <Card title="Benchmark: 24 labelled questions (20 answerable, 4 unanswerable)" aside={<button className="btn-primary" disabled={ev.loading} onClick={() => ev.run()}>Run with current config</button>}>
        <p className="text-sm muted">Runs offline with the extractive generator and the configuration from the Ask tab. Retrieval metrics count documents that contain the evidence; answer metrics check required facts, abstention and citations.</p>
        {ev.loading && <Spinner label="Evaluating" />}
        <ErrorBox error={ev.error} />
      </Card>
      {r && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(r.retrieval).map(([k, v]) => <Stat key={k} label={`retrieval ${k}`} value={(v as number)?.toFixed(3)} />)}
            <Stat label="answer accuracy" value={pct(r.answers.accuracy_answerable)} hint="answerable questions" />
            <Stat label="correct abstention" value={pct(r.answers.abstention_on_unanswerable)} hint="unanswerable questions" tone={r.answers.abstention_on_unanswerable === 1 ? "good" : "warn"} />
            <Stat label="false abstention" value={pct(r.answers.false_abstention)} tone={r.answers.false_abstention > 0.1 ? "warn" : "good"} />
            <Stat label="citation validity" value={pct(r.answers.citation_validity)} />
          </div>
          <Card title="Accuracy by question type">
            <Bars rows={Object.entries(r.by_type).map(([k, v]) => ({ label: k, value: v as number, tone: (v as number) < 0.6 ? "bg-amber-500" : undefined }))} format={(v) => pct(v)} />
          </Card>
          <Card title="Per-question results">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-xs">
                <thead className="muted"><tr><th className="py-1">id</th><th>type</th><th>result</th><th>retrieved docs</th><th>answer</th></tr></thead>
                <tbody>
                  {r.rows.map((row: any) => (
                    <tr key={row.id} className="border-t border-gray-100 align-top dark:border-white/5">
                      <td className="py-1 font-mono">{row.id}</td><td>{row.type}</td>
                      <td>{row.correct ? <Badge tone="teal">pass</Badge> : <Badge tone="rose">fail</Badge>}{row.recall != null && <div className="mt-0.5 muted">R {row.recall.toFixed(2)} · MRR {row.mrr.toFixed(2)}</div>}</td>
                      <td className="max-w-[12rem]">{row.retrieved_docs.join(", ")}</td>
                      <td className="max-w-md">{row.answer.slice(0, 200)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function ExperimentsTab() {
  const { data, reload, loading, error } = useApi<any>("/api/rag/experiments");
  const run = useAction(async () => { await api("/api/rag/experiments/run", { method: "POST" }); await reload(); });
  const label = (e: any) => `${e.config.index.strategy}/${e.config.index.chunk_size}w · ${e.config.retrieval.strategy}+${e.config.retrieval.reranker} · k${e.config.retrieval.k} · ${e.config.generator}`;
  return (
    <div className="space-y-4">
      <Card title="Experiment grid" aside={<button className="btn" disabled={run.loading} onClick={() => run.run()}>{run.loading ? "Running…" : "Re-run offline grid"}</button>}>
        <p className="text-sm muted">Vary one dimension at a time: chunking, retrieval strategy, context budget. CLI: <code className="mono">python -m lab.p01_rag.evaluate [--llm]</code>. The generator comparison appears only after a CLI run with <code className="mono">--llm</code>, since that spends real tokens.</p>
        {data && <p className="mt-1 text-xs muted">Last run {new Date(data.started * 1000).toLocaleString()} · {data.duration_s}s · embedder requested: {data.embedder_requested ?? "default"}</p>}
        <ErrorBox error={error || run.error} />
        {loading && <Spinner />}
      </Card>
      {!data && !loading && <Empty>No experiment results yet. Run the grid.</Empty>}
      {data && Object.entries(data.experiments).map(([name, exps]: any) => (
        <Card key={name} title={`Varying: ${name}`}>
          <div className="grid gap-4 lg:grid-cols-2">
            <div><div className="label">Retrieval MRR</div><Bars rows={exps.map((e: any) => ({ label: label(e), value: e.retrieval.mrr }))} /></div>
            <div><div className="label">Answer accuracy (answerable)</div><Bars rows={exps.map((e: any) => ({ label: label(e), value: e.answers.accuracy_answerable, tone: "bg-indigo-500" }))} format={(v) => pct(v)} /></div>
            <div><div className="label">Correct abstention (unanswerable)</div><Bars rows={exps.map((e: any) => ({ label: label(e), value: e.answers.abstention_on_unanswerable, tone: "bg-amber-500" }))} format={(v) => pct(v)} /></div>
            <div><div className="label">Groundedness of answered</div><Bars rows={exps.map((e: any) => ({ label: label(e), value: e.answers.groundedness, tone: "bg-purple-500" }))} format={(v) => pct(v)} /></div>
          </div>
        </Card>
      ))}
    </div>
  );
}

function CorpusTab() {
  const { data, reload, error } = useApi<any[]>("/api/rag/corpus");
  const [open, setOpen] = useState<string | null>(null);
  const doc = useApi<any>(open ? `/api/rag/doc/${open}` : null);
  const [raw, setRaw] = useState("From: dana.okafor@meridian.example\nSubject: R-17 follow-up\n\nFrostLine confirmed sensor S-17B will be replaced on 28 March 2026.");
  const [id, setId] = useState("EMAIL-followup");
  const ingest = useAction(async () => { const r = await api("/api/rag/ingest", { body: { raw, id } }); await reload(); return r; });
  const del = useAction(async (doc_id: string) => { const r = await api(`/api/rag/doc/${doc_id}`, { method: "DELETE" }); await reload(); return r; });
  const sync: any = ingest.result?.index_sync ?? del.result?.index_sync;
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <Card title={`Corpus (${data?.length ?? "…"} documents)`}>
        <ErrorBox error={error} />
        <div className="divide-y divide-gray-100 dark:divide-white/5">
          {data?.map((d) => (
            <div key={d.id} className="py-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <button className="link text-sm font-medium" onClick={() => setOpen(open === d.id ? null : d.id)}>{d.id}</button>
                <span className="text-sm">{d.title}</span>
                <DocBadges h={d} />
                <span className="font-mono text-[11px] muted">#{d.hash}</span>
                {d.source === "ingested" && <button className="ml-auto text-xs text-rose-600 hover:underline" onClick={() => del.run(d.id)}>delete</button>}
              </div>
              {open === d.id && doc.data && <pre className="mono mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 dark:bg-ink-pop">{doc.data.body}</pre>}
            </div>
          ))}
        </div>
      </Card>
      <div className="space-y-4">
        <Card title="Ingest a document">
          <Field label="Document id"><input className="input" value={id} onChange={(e) => setId(e.target.value)} /></Field>
          <div className="mt-2"><Field label="Raw text" hint="Front matter (--- id/title/access ---) or email headers (From/Subject) become metadata."><textarea className="input min-h-[140px] font-mono text-xs" value={raw} onChange={(e) => setRaw(e.target.value)} /></Field></div>
          <button className="btn-primary mt-2 w-full" disabled={ingest.loading} onClick={() => ingest.run()}>Ingest & sync index</button>
          <ErrorBox error={ingest.error || del.error} />
        </Card>
        {sync && (
          <Card title="Incremental sync result">
            <div className="grid grid-cols-2 gap-2">
              <Stat label="re-embedded" value={sync.docs_reembedded} tone="good" />
              <Stat label="unchanged" value={sync.docs_unchanged} />
              <Stat label="removed" value={sync.docs_removed} />
              <Stat label="chunks embedded" value={sync.chunks_embedded} hint={`of ${sync.chunks_total}`} />
            </div>
            <p className="mt-2 text-xs muted">Only documents whose content hash changed were re-chunked and re-embedded ({sync.embedder}).</p>
          </Card>
        )}
      </div>
    </div>
  );
}

export default function EvidenceAtlas() {
  const [cfg, setCfg] = useState<Cfg>(DEFAULT);
  return (
    <Workspace
      p={p}
      tabs={[
        { id: "ask", label: "Ask & inspect", content: <AskTab cfg={cfg} setCfg={setCfg} /> },
        { id: "bench", label: "Benchmark", content: <BenchmarkTab cfg={cfg} /> },
        { id: "exp", label: "Experiments", content: <ExperimentsTab /> },
        { id: "corpus", label: "Corpus & ingestion", content: <CorpusTab /> },
      ]}
    />
  );
}
