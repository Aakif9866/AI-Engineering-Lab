import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {
  constructor(message: string, public status: number, public kind?: string) {
    super(message);
  }
}

/** Visitor-supplied provider keys: kept only in this browser, sent with each request, never stored server-side. */
export const KEY_PROVIDERS = ["deepseek", "groq"] as const;
export function getKey(p: string): string {
  try { return localStorage.getItem(`key:${p}`) ?? ""; } catch { return ""; }
}
export function setKey(p: string, v: string) {
  try { v ? localStorage.setItem(`key:${p}`, v) : localStorage.removeItem(`key:${p}`); } catch { /* storage unavailable */ }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = opts.body !== undefined ? { "Content-Type": "application/json" } : {};
  for (const p of KEY_PROVIDERS) if (getKey(p)) headers[`X-${p[0].toUpperCase()}${p.slice(1)}-Key`] = getKey(p);
  const res = await fetch(path, {
    method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const d = data?.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x: any) => `${x.loc?.slice(1).join(".")}: ${x.msg}`).join("; ") : res.statusText;
    throw new ApiError(msg || `HTTP ${res.status}`, res.status, data?.error);
  }
  return data as T;
}

/** GET on mount + manual reload. */
export function useApi<T = any>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

/** Wraps a mutating call with loading/error state. */
export function useAction<A extends any[], T>(fn: (...a: A) => Promise<T>) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const run = useCallback(
    async (...a: A) => {
      setLoading(true);
      setError(null);
      try {
        const r = await fn(...a);
        setResult(r);
        return r;
      } catch (e) {
        setError(e as ApiError);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [fn],
  );
  return { run, loading, error, result, setResult };
}

export type Status = {
  offline_forced: boolean;
  public: boolean;
  default_provider: string | null;
  providers: { name: string; configured: boolean; usable: boolean; model: string; price: any }[];
  embedder: string;
  embedder_fallback: string | null;
  capture_content: boolean;
};

/** Poll a GET endpoint while `active` is true (training/eval progress). */
export function usePoll<T = any>(path: string | null, ms: number, active: boolean) {
  const q = useApi<T>(path);
  useEffect(() => {
    if (!active || !path) return;
    const t = setInterval(q.reload, ms);
    return () => clearInterval(t);
  }, [active, path, ms, q.reload]);
  return q;
}
