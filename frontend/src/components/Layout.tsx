import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Status, useApi } from "../api";
import { Project, PROJECTS } from "../projects";
import { Badge, Tabs } from "./ui";

const StatusCtx = createContext<{ status: Status | null; reload: () => void }>({ status: null, reload: () => {} });
export const useStatus = () => useContext(StatusCtx);

const ICONS: Record<string, string> = {
  "01": "M4 5h10M4 9h16M4 13h7M15 13l2 2 4-4M4 17h7", // documents + check
  "02": "M12 3v4M12 17v4M3 12h4M17 12h4M7 7l2 2M15 15l2 2M7 17l2-2M15 9l2-2M12 9a3 3 0 100 6 3 3 0 000-6z", // tuning dial
  "03": "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6", // stack
  "04": "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3zm-3 9l2 2 4-4", // shield
  "05": "M4 12a8 8 0 0114-5.3M20 12a8 8 0 01-14 5.3M18 3v4h-4M6 21v-4h4", // loop
  "06": "M5 19V5M5 19h14M8 15l3-4 3 2 4-6", // trajectory
  "07": "M3 12h4l2-6 4 12 2-6h6", // pulse
};
export function ProjectIcon({ p, className = "h-5 w-5" }: { p: Project; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={`${className} ${p.hue}`} aria-hidden>
      <path d={ICONS[p.num]} />
    </svg>
  );
}

function ProviderPills({ status }: { status: Status | null }) {
  if (!status) return <Badge>status…</Badge>;
  const live = status.providers.filter((p) => p.usable);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {live.length === 0 ? (
        <Badge tone="amber" title={status.offline_forced ? "LAB_OFFLINE=1" : "No API key configured"}>● offline mode</Badge>
      ) : (
        <Badge tone="teal">● live: {live.map((p) => p.name).join(", ")}</Badge>
      )}
      {status.providers.map((p) => (
        <Badge key={p.name} tone={p.usable ? "teal" : "gray"} title={p.usable ? `model ${p.model}` : "no key set in .env"}>
          {p.name} {p.usable ? "✓" : "–"}
        </Badge>
      ))}
    </div>
  );
}

export function Layout() {
  const { data: status, reload } = useApi<Status>("/api/status");
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const [menu, setMenu] = useState(false);
  const loc = useLocation();
  useEffect(() => setMenu(false), [loc.pathname]);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.theme = dark ? "dark" : "light"; } catch { /* storage unavailable */ }
  }, [dark]);

  const nav = (
    <nav className="space-y-0.5" aria-label="Workspaces">
      <NavLink to="/" end className={({ isActive }) => `block rounded-tl-lg rounded-br-lg px-3 py-2 text-sm ${isActive ? "bg-teal-50 font-semibold text-teal-800 dark:bg-teal-400/10 dark:text-teal-200" : "hover:bg-gray-100 dark:hover:bg-white/5"}`}>Overview</NavLink>
      {PROJECTS.map((p) => (
        <NavLink key={p.slug} to={`/${p.slug}`} className={({ isActive }) => `flex min-h-[44px] items-center gap-2.5 rounded-tl-lg rounded-br-lg px-3 py-1.5 ${isActive ? "bg-teal-50 dark:bg-teal-400/10" : "hover:bg-gray-100 dark:hover:bg-white/5"}`}>
          {({ isActive }) => (
            <>
              <ProjectIcon p={p} className="h-4 w-4 shrink-0" />
              <span className="min-w-0">
                <span className={`block truncate text-sm ${isActive ? "font-semibold text-teal-800 dark:text-teal-200" : ""}`}>{p.num} {p.name}</span>
                <span className="block truncate text-[11px] muted">{p.pattern}</span>
              </span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <StatusCtx.Provider value={{ status, reload }}>
      <div className="h-2 bg-teal-500" />
      <header className="sticky top-0 z-20 border-b border-gray-200 bg-white/90 backdrop-blur dark:border-white/10 dark:bg-ink-page/90">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-3 py-2">
          <button className="btn !min-h-[44px] !px-3 lg:hidden" onClick={() => setMenu(!menu)} aria-expanded={menu} aria-label="Toggle navigation">☰</button>
          <NavLink to="/" className="whitespace-nowrap bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-clip-text text-lg font-bold text-transparent">AI Engineering Lab</NavLink>
          <div className="ml-auto hidden sm:block"><ProviderPills status={status} /></div>
          <button className="btn !min-h-[44px] !px-3" onClick={() => setDark(!dark)} aria-label="Toggle dark mode">{dark ? "☀" : "☾"}</button>
        </div>
        <div className="px-3 pb-2 sm:hidden"><ProviderPills status={status} /></div>
      </header>
      <div className="mx-auto flex max-w-7xl gap-6 px-3 py-4">
        <aside className="hidden w-60 shrink-0 lg:block"><div className="sticky top-20">{nav}</div></aside>
        {menu && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setMenu(false)}><div className="h-full w-72 overflow-y-auto bg-white p-3 shadow-xl dark:bg-ink-pop" onClick={(e) => e.stopPropagation()}>{nav}</div></div>}
        <main key={loc.pathname} className="min-w-0 flex-1 motion-safe:animate-rise"><Outlet /></main>
      </div>
    </StatusCtx.Provider>
  );
}

/** Shared frame for the seven workspaces: header, then Lab/Results tabs supplied by the page, then Learn + Roadmap. */
export function Workspace({ p, tabs, banner, focus }: { p: Project; tabs: { id: string; label: string; content: ReactNode }[]; banner?: ReactNode; focus?: { tab: string; nonce: string } }) {
  return (
    <div className="space-y-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-tl-2xl rounded-br-2xl border border-gray-200 dark:border-white/10"><ProjectIcon p={p} className="h-7 w-7" /></div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-xs muted">
            <span className="font-mono">Project {p.num}</span><span>·</span><span>{p.pattern}</span><Badge tone={p.axis === "Quality" ? "violet" : p.axis === "Both" ? "amber" : "teal"}>axis: {p.axis}</Badge>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white lg:text-4xl">{p.name}</h1>
          <p className="mt-1 max-w-3xl text-sm muted">{p.problem}</p>
          <p className="mt-1 max-w-3xl text-xs italic muted">PDF anchor: {p.pdf}</p>
        </div>
      </header>
      {banner}
      <Tabs
        focus={focus}
        tabs={[
          ...tabs,
          {
            id: "learn", label: "Learn",
            content: (
              <div className="grid gap-3 md:grid-cols-2">
                {p.learn.map((l, i) => (
                  <div key={l.title} className="card motion-safe:animate-rise" style={{ animationDelay: `${i * 50}ms` }}>
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{l.title}</h3>
                    <p className="mt-1 text-sm muted">{l.body}</p>
                  </div>
                ))}
              </div>
            ),
          },
          {
            id: "roadmap", label: "V1 status & V2",
            content: (
              <div className="grid gap-3 md:grid-cols-2">
                <div className="card">
                  <h3 className="mb-2 text-sm font-semibold">Known V1 limitations</h3>
                  <ul className="list-disc space-y-1 pl-5 text-sm muted">{p.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
                </div>
                <div className="card">
                  <h3 className="mb-2 text-sm font-semibold">V2 roadmap</h3>
                  <ul className="list-disc space-y-1 pl-5 text-sm muted">{p.v2.map((l) => <li key={l}>{l}</li>)}</ul>
                </div>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
