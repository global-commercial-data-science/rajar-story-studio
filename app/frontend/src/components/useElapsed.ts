import { useEffect, useState } from "react";

/** Seconds since `active` became true (0 while inactive). */
export function useElapsed(active: boolean) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) { setSeconds(0); return; }
    const start = Date.now();
    const id = setInterval(() => setSeconds(Math.round((Date.now() - start) / 1000)), 500);
    return () => clearInterval(id);
  }, [active]);
  return seconds;
}
