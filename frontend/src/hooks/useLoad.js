import { useEffect, useState } from "react";
import { api } from "../services/api";

const reportCache = new Map();
const REPORT_CACHE_TTL_MS = 5 * 60 * 1000;

export function useLoad(path, refresh, options = {}) {
  const [state, setState] = useState(() => ({ loading: Boolean(path) }));

  useEffect(() => {
    let live = true;
    if (!path) {
      setState({ data: null });
      return () => { live = false; };
    }
    const cacheableReport = (path.startsWith("/report?") || path.startsWith("/dashboard/summary?")) &&
      options.cacheScope != null;
    const cacheKey = cacheableReport
      ? `${String(options.cacheScope)}\u001f${path}\u001f${String(refresh ?? "")}`
      : null;
    const cached = cacheKey ? reportCache.get(cacheKey) : null;
    if (cached && Date.now() - cached.savedAt < REPORT_CACHE_TTL_MS) {
      setState({ data: cached.data });
      return () => { live = false; };
    }
    const controller = new globalThis.AbortController();
    const debounceMs = Math.max(0, Number(options.debounceMs) || 0);
    setState({ loading: true });
    const request = () => {
      api(path, { signal: controller.signal })
        .then((data) => {
          if (cacheKey) reportCache.set(cacheKey, { data, savedAt: Date.now() });
          if (live) setState({ data });
        })
        .catch((error) => { if (live) setState({ error: error.message }); });
    };
    const timer = setTimeout(request, debounceMs);
    return () => { live = false; clearTimeout(timer); controller.abort(); };
  }, [path, refresh, options.cacheScope, options.debounceMs]);

  return state;
}
