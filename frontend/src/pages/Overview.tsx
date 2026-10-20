import { Link } from "react-router-dom";
import { useApi } from "../api";
import { ProjectIcon, useStatus } from "../components/Layout";
import { Badge, ms, pct } from "../components/ui";
import { PROJECTS } from "../projects";

type ModuleStat = { module: string; requests: number; errors: number; blocked: number; p95_ms: number | null; last_ts: number | null };

export default function Overview() {
  const { status } = useStatus();
  const { data } = useApi<{ modules: Record<string, ModuleStat> }>("/api/overview");

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white lg:text-6xl">Seven patterns, built for real.</h1>
        <p className="mt-3 max-w-3xl text-sm muted lg:text-base">
          Each workspace implements one production LLM design pattern from the reference guide: a working mechanism, a labelled benchmark, failure cases and a test suite.
          Everything runs offline; DeepSeek and Groq are used only when you turn them on.
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <Badge tone={status?.default_provider ? "teal" : "amber"}>{status?.default_provider ? `LLM calls available via ${status.default_provider}` : "offline: deterministic baselines only"}</Badge>
          <Badge>embedder: {status?.embedder ?? "…"}</Badge>
          <Badge tone={status?.capture_content ? "amber" : "teal"}>trace content capture {status?.capture_content ? "ON (PII-redacted)" : "off"}</Badge>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Workspaces</h2>
          <span className="text-xs muted">activity from TraceLens spans</span>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {PROJECTS.map((p, i) => {
            const m = data?.modules?.[p.slug];
            return (
              <Link
                key={p.slug}
                to={`/${p.slug}`}
                style={{ animationDelay: `${i * 50}ms` }}
                className="group relative flex min-h-[190px] flex-col overflow-hidden rounded-tl-3xl rounded-br-3xl border border-gray-200 bg-white p-4 motion-safe:animate-rise motion-safe:transition-all motion-safe:duration-200 hover:border-teal-500 motion-safe:hover:-translate-y-1 hover:shadow-lg dark:border-white/10 dark:bg-ink-card dark:hover:border-teal-400"
              >
                <div className="flex items-center gap-2">
                  <ProjectIcon p={p} className="h-6 w-6" />
                  <span className="font-mono text-xs muted">{p.num}</span>
                  <Badge tone={p.axis === "Quality" ? "violet" : p.axis === "Both" ? "amber" : "teal"}>{p.axis}</Badge>
                </div>
                <h3 className="mt-2 text-lg font-semibold text-gray-900 line-clamp-1 dark:text-white">{p.name}</h3>
                <div className="text-xs font-medium text-teal-700 dark:text-teal-300">{p.pattern}</div>
                <p className="mt-1 text-sm muted line-clamp-3">{p.tagline}</p>
                <div className="mt-auto pt-2 font-mono text-[11px] muted transition-opacity duration-300 group-hover:opacity-0">
                  {m && m.requests > 0 ? `${m.requests} traced requests · p95 ${ms(m.p95_ms)} · errors ${pct(m.errors / m.requests)}${m.blocked ? ` · ${m.blocked} blocked by guardrails` : ""}` : "no traced activity yet"}
                </div>
                <div className="absolute inset-x-0 -bottom-16 border-t border-teal-500 bg-white px-4 py-3 text-sm font-medium text-teal-700 transition-all duration-300 group-hover:bottom-0 dark:bg-ink-pop dark:text-teal-300">
                  Open workspace →
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="text-sm font-semibold">Two axes (from the guide)</h2>
          <p className="mt-1 text-sm muted">Some patterns mainly raise quality. Others control cost and risk once quality is acceptable. Feedback feeds both. A strong design names this trade-off instead of treating every pattern as a free win.</p>
          <table className="mt-3 w-full text-left text-sm">
            <thead className="text-xs muted"><tr><th className="py-1">Pattern</th><th>Primary goal</th><th>Axis</th></tr></thead>
            <tbody>
              {[["RAG", "Ground output in external data", "Quality"], ["Fine-tuning", "Specialise model behaviour", "Quality"], ["Caching", "Reduce latency and cost", "Cost / Risk"], ["Guardrails & Defensive UX", "Enforce safety, degrade gracefully", "Cost / Risk"], ["User Feedback", "Build the data flywheel", "Both"], ["Agentic Evals", "Score trajectories, not just answers", "Quality"], ["LLM Observability", "See what happened in production", "Cost / Risk"]].map(([a, b, c]) => (
                <tr key={a} className="border-t border-gray-100 dark:border-white/5"><td className="py-1 pr-2">{a}</td><td className="pr-2 muted">{b}</td><td>{c}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h2 className="text-sm font-semibold">Suggested learning path</h2>
          <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm">
            <li><Link className="link" to="/tracelens">TraceLens</Link>: open it first and keep it open. Every action elsewhere becomes a trace here.</li>
            <li><Link className="link" to="/evidence-atlas">Evidence Atlas</Link>: compare BM25, dense and hybrid retrieval, then ask an unanswerable question.</li>
            <li><Link className="link" to="/cachecraft">CacheCraft</Link>: sweep the semantic threshold and watch false hits appear.</li>
            <li><Link className="link" to="/trustboundary">TrustBoundary</Link>: run the adversarial corpus with the compromised model.</li>
            <li><Link className="link" to="/missionreplay">MissionReplay</Link>: compare a careful agent with a reckless one on identical scenarios.</li>
            <li><Link className="link" to="/signalloop">SignalLoop</Link>: leave a correction, approve it, then try to promote a regressing candidate.</li>
            <li><Link className="link" to="/intentforge">IntentForge</Link>: build the dataset, train the adapter, and compare against the baseline.</li>
          </ol>
          <p className="mt-3 text-xs muted">The patterns are not mutually exclusive: a production RAG system needs guardrails, caching, defensive UX, observability and a feedback loop, all measured against an eval harness.</p>
        </div>
      </section>
    </div>
  );
}
