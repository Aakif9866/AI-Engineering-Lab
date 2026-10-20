import { ReactNode, useEffect, useState } from "react";
import { ApiError } from "../api";

export function Card({ title, aside, children, className = "" }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card motion-safe:animate-rise ${className}`}>
      {(title || aside) && (
        <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h3>}
          {aside}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "bad" | "warn" }) {
  const color = tone === "good" ? "text-teal-700 dark:text-teal-300" : tone === "bad" ? "text-rose-600 dark:text-rose-400" : tone === "warn" ? "text-amber-600 dark:text-amber-400" : "text-gray-900 dark:text-white";
  return (
    <div className="min-w-0 rounded-tl-xl rounded-br-xl border border-gray-200 p-3 dark:border-white/10">
      <div className="label truncate">{label}</div>
      <div className={`text-xl font-semibold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs muted">{hint}</div>}
    </div>
  );
}

const BADGE: Record<string, string> = {
  teal: "border-teal-600/40 bg-teal-50 text-teal-800 dark:border-teal-400/30 dark:bg-teal-400/10 dark:text-teal-200",
  rose: "border-rose-500/40 bg-rose-50 text-rose-700 dark:border-rose-400/30 dark:bg-rose-400/10 dark:text-rose-300",
  amber: "border-amber-500/40 bg-amber-50 text-amber-800 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-200",
  gray: "border-gray-300 bg-gray-50 text-gray-700 dark:border-white/15 dark:bg-white/5 dark:text-gray-300",
  violet: "border-violet-500/40 bg-violet-50 text-violet-700 dark:border-violet-400/30 dark:bg-violet-400/10 dark:text-violet-200",
};
export function Badge({ tone = "gray", children, title }: { tone?: keyof typeof BADGE; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-tl-md rounded-br-md border px-1.5 py-0.5 text-[11px] font-medium ${BADGE[tone]}`}>
      {children}
    </span>
  );
}

export function ErrorBox({ error, onRetry }: { error: ApiError | Error | null; onRetry?: () => void }) {
  if (!error) return null;
  const kind = (error as ApiError).kind;
  const hint = kind === "provider_unavailable" ? "No LLM provider is configured, so this step ran nothing. Turn off the LLM option to use the offline path, or add a key to .env." : kind === "rate_limit" ? "The provider rate-limited the request after bounded retries. Wait and retry." : null;
  return (
    <div role="alert" className="rounded-tl-xl rounded-br-xl border border-rose-400/50 bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-400/10 dark:text-rose-200">
      <div className="font-medium">{error.message}</div>
      {hint && <div className="mt-1 text-xs opacity-90">{hint}</div>}
      {onRetry && <button className="mt-2 text-xs underline" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Spinner({ label = "Working" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs muted" role="status">
      <span className="h-3 w-3 rounded-full border-2 border-teal-500 border-t-transparent motion-safe:animate-spin" />
      {label}…
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-tl-xl rounded-br-xl border border-dashed border-gray-300 p-6 text-center text-sm muted dark:border-white/15">{children}</div>;
}

/** Horizontal bars, values 0..max. Used for metrics comparisons across configurations. */
export function Bars({ rows, max = 1, format = (v: number) => v.toFixed(2) }: { rows: { label: ReactNode; value: number | null; tone?: string; note?: ReactNode }[]; max?: number; format?: (v: number) => string }) {
  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,10rem)_1fr_3.5rem] items-center gap-2 text-xs sm:grid-cols-[minmax(0,14rem)_1fr_4rem]">
          <div className="truncate" title={typeof r.label === "string" ? r.label : undefined}>{r.label}</div>
          <div className="h-2.5 overflow-hidden rounded-r-full bg-gray-100 dark:bg-white/5">
            <div className={`h-full rounded-r-full motion-safe:transition-all motion-safe:duration-500 ${r.tone ?? "bg-teal-500 dark:bg-teal-400"}`} style={{ width: `${r.value == null ? 0 : Math.max(1, (r.value / max) * 100)}%` }} />
          </div>
          <div className="text-right tabular-nums">{r.value == null ? "n/a" : format(r.value)}</div>
        </div>
      ))}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block min-w-0">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] muted">{hint}</span>}
    </label>
  );
}

export function Select<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: (T | [T, string])[] }) {
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value as T)}>
      {options.map((o) => {
        const [v, l] = Array.isArray(o) ? o : [o, o];
        return <option key={v} value={v}>{l}</option>;
      })}
    </select>
  );
}

export function Toggle({ checked, onChange, label, disabled, hint }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; disabled?: boolean; hint?: ReactNode }) {
  return (
    <label className={`flex min-h-[40px] items-start gap-2 text-sm ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <input type="checkbox" className="mt-1 h-4 w-4 accent-teal-600" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        {label}
        {hint && <span className="block text-[11px] muted">{hint}</span>}
      </span>
    </label>
  );
}

export function Json({ value, max = 320 }: { value: unknown; max?: number }) {
  return <pre className="mono overflow-auto rounded-tl-lg rounded-br-lg bg-gray-50 p-3 text-gray-700 dark:bg-ink-pop dark:text-gray-300" style={{ maxHeight: max }}>{JSON.stringify(value, null, 2)}</pre>;
}

/** `focus` switches to a tab whenever its nonce changes (e.g. a link that opens a specific trace). */
export function Tabs({ tabs, initial, focus }: { tabs: { id: string; label: string; content: ReactNode }[]; initial?: string; focus?: { tab: string; nonce: string } }) {
  const [active, setActive] = useState(focus?.tab ?? initial ?? tabs[0].id);
  useEffect(() => { if (focus) setActive(focus.tab); }, [focus?.tab, focus?.nonce]);
  return (
    <div>
      <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-gray-200 dark:border-white/10">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={active === t.id}
            onClick={() => setActive(t.id)}
            className={`relative min-h-[44px] whitespace-nowrap px-3 text-sm transition-colors duration-150 ${active === t.id ? "font-semibold text-gray-900 dark:text-white" : "muted hover:text-gray-900 dark:hover:text-white"}`}
          >
            {t.label}
            {active === t.id && <span className="absolute inset-x-2 -bottom-px h-0.5 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500" />}
          </button>
        ))}
      </div>
      {tabs.map((t) => (
        <div key={t.id} role="tabpanel" hidden={active !== t.id}>
          {active === t.id && t.content}
        </div>
      ))}
    </div>
  );
}

export const pct = (v: number | null | undefined, d = 0) => (v == null ? "n/a" : `${(v * 100).toFixed(d)}%`);
export const ms = (v: number | null | undefined) => (v == null ? "n/a" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${v.toFixed(v < 10 ? 1 : 0)} ms`);
export const usd = (v: number | null | undefined) => (v == null ? "n/a" : v < 0.01 ? `$${v.toFixed(6)}` : `$${v.toFixed(4)}`);

/** Minimal multi-series line chart (SVG). x and y are numbers; points with y == null are skipped. */
export function LineChart({ series, height = 180, xLabel, yLabel, yMin, yMax, marks = [] }: {
  series: { name: string; color: string; points: { x: number; y: number | null }[]; dashed?: boolean }[];
  height?: number; xLabel?: string; yLabel?: string; yMin?: number; yMax?: number; marks?: { x: number; label: string }[];
}) {
  const pts = series.flatMap((s) => s.points.filter((p) => p.y != null)) as { x: number; y: number }[];
  if (!pts.length) return <Empty>No data yet.</Empty>;
  const W = 600, H = height, P = { l: 40, r: 10, t: 10, b: 28 };
  const x0 = Math.min(...pts.map((p) => p.x)), x1 = Math.max(...pts.map((p) => p.x));
  const y0 = yMin ?? Math.min(...pts.map((p) => p.y)), y1 = yMax ?? Math.max(...pts.map((p) => p.y));
  const sx = (x: number) => P.l + ((x - x0) / (x1 - x0 || 1)) * (W - P.l - P.r);
  const sy = (y: number) => H - P.b - ((y - y0) / (y1 - y0 || 1)) * (H - P.t - P.b);
  const ticks = [y0, (y0 + y1) / 2, y1];
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${yLabel ?? ""} vs ${xLabel ?? ""}`}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={P.l} x2={W - P.r} y1={sy(t)} y2={sy(t)} className="stroke-gray-200 dark:stroke-white/10" />
            <text x={P.l - 4} y={sy(t) + 3} textAnchor="end" className="fill-gray-500 text-[10px]">{t.toFixed(2)}</text>
          </g>
        ))}
        {marks.map((m) => (
          <g key={m.label}>
            <line x1={sx(m.x)} x2={sx(m.x)} y1={P.t} y2={H - P.b} className="stroke-amber-500" strokeDasharray="3 3" />
            <text x={sx(m.x) + 3} y={P.t + 10} className="fill-amber-600 text-[10px]">{m.label}</text>
          </g>
        ))}
        {series.map((s) => {
          const ps = s.points.filter((p) => p.y != null) as { x: number; y: number }[];
          return (
            <g key={s.name}>
              <polyline fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? "5 4" : undefined} points={ps.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")} />
              {ps.length < 40 && ps.map((p, i) => <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={2.5} fill={s.color} />)}
            </g>
          );
        })}
        <text x={W / 2} y={H - 6} textAnchor="middle" className="fill-gray-500 text-[10px]">{xLabel}</text>
      </svg>
      <div className="mt-1 flex flex-wrap gap-3 text-xs">
        {series.map((s) => <span key={s.name} className="inline-flex items-center gap-1"><span className="inline-block h-2 w-3" style={{ background: s.color }} />{s.name}</span>)}
      </div>
    </div>
  );
}
