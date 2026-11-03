"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";

/** Fetch `path` on mount and whenever it changes. `reload()` refetches. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!path) return;
    const mine = ++seq.current;
    setLoading(true);
    try {
      const result = await api<T>(path);
      if (mine === seq.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (mine === seq.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}

/** Poll a Celery task until it finishes. */
export async function waitForTask(taskId: string, timeoutMs = 180_000): Promise<string> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const t = await api<{ state: string }>(`/agents/tasks/${taskId}`);
    if (["SUCCESS", "FAILURE", "REVOKED"].includes(t.state)) return t.state;
    await new Promise((r) => setTimeout(r, 2000));
  }
  return "TIMEOUT";
}
