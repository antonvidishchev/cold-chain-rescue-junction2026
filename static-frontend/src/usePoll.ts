import { useEffect, useRef, useState } from 'react';

export function usePoll<T>(key: string, load: (signal: AbortSignal) => Promise<T>, intervalMs = 20_000) {
  const loader = useRef(load);
  useEffect(() => { loader.current = load; }, [load]);
  const [revision, refresh] = useState(0);
  const [state, setState] = useState<{ key: string; data?: T; error?: string; updated?: string; loading: boolean }>({ key, loading: true });
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Keyed render state hides prior selections while this request is pending.
    async function run() {
      const started = Date.now();
      try {
        const data = await loader.current(controller.signal);
        if (active) setState({ key, data, updated: new Date().toISOString(), loading: false });
      } catch (error) {
        if (active) setState(previous => ({ ...(previous.key === key ? previous : { key }), loading: false, error: error instanceof Error ? error.message : 'Unable to reach the service.' }));
      } finally {
        // Fixed-rate schedule: a slow request does not stretch the interval.
        // A hidden tab stops polling and fetches again as soon as it is visible.
        if (active && !document.hidden) timer = setTimeout(run, Math.max(0, intervalMs - (Date.now() - started)));
      }
    }
    function onVisibility() {
      if (!document.hidden && active) { clearTimeout(timer); void run(); }
    }
    document.addEventListener('visibilitychange', onVisibility);
    void run();
    return () => { active = false; controller.abort(); clearTimeout(timer); document.removeEventListener('visibilitychange', onVisibility); };
  }, [key, revision, intervalMs]);
  const current = state.key === key ? state : { key, loading: true };
  return { ...current, refresh: () => { setState(previous => ({ ...previous, loading: true })); refresh(value => value + 1); } };
}
