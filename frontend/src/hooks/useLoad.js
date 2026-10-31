import { useEffect, useState } from "react";
import { api } from "../services/api";

const reportCache = new Map();
const REPORT_CACHE_TTL_MS = 5 * 60 * 1000;
const REPORT_SESSION_TTL_MS = 24 * 60 * 60 * 1000;

function readStoredReport(key) {
  if (!key || typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const cached = JSON.parse(raw);
    if (!cached?.data || Date.now() - Number(cached.savedAt) > REPORT_SESSION_TTL_MS) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    return cached;
  } catch {
    return null;
  }
}

function writeStoredReport(key, data) {
  if (!key || typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(key, JSON.stringify({ data, savedAt: Date.now() }));
  } catch {
    // Storage can be disabled or full; the in-memory cache still works.
  }
}

function announceCachedReport(key, status) {
  if (key && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("qor-report-cache-state", { detail: { key, status } }));
  }
}

export function useLoad(path, refresh, options = {}) {
  const cacheableReport = Boolean(path && (path.startsWith("/report?") || path.startsWith("/dashboard/summary?") || path.startsWith("/marketplace-summary?")) && options.cacheScope != null);
  const storageKey = cacheableReport
    ? `qor-report:v1:${String(options.cacheScope)}:${path}`
    : null;
  const identity = `${path || ""}\u001f${String(options.cacheScope ?? "")}`;
  const storedForRender = readStoredReport(storageKey);
  const [state, setState] = useState(() => ({
    ...(storedForRender ? { data: storedForRender.data, stale: true } : {}),
    loading: Boolean(path),
    identity,
  }));
  const visibleState = state.identity === identity
    ? state
    : { ...(storedForRender ? { data: storedForRender.data, stale: true } : {}), loading: Boolean(path), identity };

  useEffect(() => {
    let live = true;
    if (!path) {
      setState({ data: null, identity });
      return () => { live = false; };
    }
    const cacheKey = cacheableReport
      ? `${String(options.cacheScope)}\u001f${path}\u001f${String(refresh ?? "")}`
      : null;
    const cached = cacheKey ? reportCache.get(cacheKey) : null;
    if (cached && Date.now() - cached.savedAt < REPORT_CACHE_TTL_MS) {
      setState({ data: cached.data, identity, loading: false });
      return () => { live = false; };
    }
    const stored = readStoredReport(storageKey);
    if (stored) announceCachedReport(storageKey, "refreshing");
    const controller = new globalThis.AbortController();
    const debounceMs = Math.max(0, Number(options.debounceMs) || 0);
    setState({ ...(stored ? { data: stored.data, stale: true } : {}), loading: true, identity });
    const request = () => {
      api(path, { signal: controller.signal })
        .then((data) => {
          if (cacheKey) reportCache.set(cacheKey, { data, savedAt: Date.now() });
          writeStoredReport(storageKey, data);
          announceCachedReport(storageKey, "clear");
          if (live) setState({ data, loading: false, stale: false, identity });
        })
        .catch((error) => {
          if (stored) announceCachedReport(storageKey, "error");
          if (live) setState({ ...(stored ? { data: stored.data, stale: true } : { error: error.message }), loading: false, identity });
        });
    };
    const timer = setTimeout(request, debounceMs);
    return () => {
      live = false;
      clearTimeout(timer);
      controller.abort();
      if (stored) announceCachedReport(storageKey, "clear");
    };
  }, [path, refresh, options.cacheScope, options.debounceMs, identity, storageKey, cacheableReport]);

  return visibleState.data ? { ...visibleState, loading: false } : visibleState;
}
