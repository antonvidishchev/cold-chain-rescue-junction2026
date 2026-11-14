import { useEffect, useRef, useState } from 'react';

export function usePoll<T>(key: string, load: (signal: AbortSignal) => Promise<T>) {
  const loader = useRef(load);
  useEffect(() => { loader.current = load; }, [load]);
  const [revision, refresh] = useState(0);
  const [state, setState] = useState<{ key: string; data?: T; error?: string; updated?: string; loading: boolean }>({ key, loading: true });
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    // Keyed render state hides prior selections while this request is pending.
    async function run() {
      try {
        const data = await loader.current(controller.signal);
        if (active) setState({ key, data, updated: new Date().toISOString(), loading: false });
      } catch (error) {
        if (active) setState(previous => ({ ...(previous.key === key ? previous : { key }), loading: false, error: error instanceof Error ? error.message : 'Unable to reach the service.' }));
      } finally {
        if (active) timer = setTimeout(run, 20_000);
      }
    }
    void run();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [key, revision]);
  const current = state.key === key ? state : { key, loading: true };
  return { ...current, refresh: () => { setState(previous => ({ ...previous, loading: true })); refresh(value => value + 1); } };
}
