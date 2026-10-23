import { useEffect, useState } from "react";

const RETRY_MS = 3000;

/**
 * Load data, then load it again after the delay that `delay` gives for the
 * latest data. A null delay stops. A failed load is tried again.
 */
export function usePolling<T>(
  load: () => Promise<T>,
  delay: (data: T) => number | null,
): { data: T | null; failed: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    const tick = () => {
      load()
        .then((value) => {
          if (stopped) return;
          setData(value);
          setFailed(false);
          const next = delay(value);
          if (next !== null) timer = window.setTimeout(tick, next);
        })
        .catch(() => {
          if (stopped) return;
          setFailed(true);
          timer = window.setTimeout(tick, RETRY_MS);
        });
    };
    tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [load, delay]);

  return { data, failed };
}
