// src/hooks/useApi.js
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Data fetching with loading/error/refetch and optional polling.
 *
 * Two details that matter in practice:
 *  - `isRefreshing` is tracked separately from `loading`, so a background poll doesn't blank
 *    out a screen the user is reading.
 *  - Results from a stale request are discarded after unmount, which otherwise produces
 *    React state-update warnings and can flash old data when navigating quickly.
 */
export function useApi(fetcher, { immediate = true, pollMs = 0, deps = [] } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(immediate);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const mounted = useRef(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async ({ background = false } = {}) => {
    if (background) setIsRefreshing(true);
    else setLoading(true);
    try {
      const result = await fetcherRef.current();
      if (!mounted.current) return null;
      setData(result);
      setError(null);
      setLastUpdated(new Date());
      return result;
    } catch (e) {
      if (mounted.current) setError(e.message || "Request failed");
      return null;
    } finally {
      if (mounted.current) {
        setLoading(false);
        setIsRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    if (immediate) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!pollMs) return undefined;
    const timer = setInterval(() => run({ background: true }), pollMs);
    return () => clearInterval(timer);
  }, [pollMs, run]);

  return { data, error, loading, isRefreshing, lastUpdated, refetch: run, setData };
}
