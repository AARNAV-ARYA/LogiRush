/* eslint-disable react-refresh/only-export-components, react/prop-types */
// src/context/SyncContext.jsx
// Global connectivity + offline queue state.
//
// Lives at app level rather than inside the report page because the queue must stay visible
// wherever the user navigates. Someone who files three reports in a valley with no signal
// should see "3 pending" in the header on every screen until they actually sync — a queue
// you can only see on one page is a queue people forget about.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { getQueuedIncidents, syncQueuedIncidents } from "../utils/offlineQueue";
import { estimateStorage, primeOfflineCache, readReference, describeCacheAge } from "../utils/offlineStore";

const SyncContext = createContext(null);

export function SyncProvider({ children }) {
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine
  );
  const [pending, setPending] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const [cacheStatus, setCacheStatus] = useState({ age: null, storage: null });

  const refreshQueue = useCallback(async () => {
    try {
      setPending(await getQueuedIncidents());
    } catch {
      // IndexedDB can be unavailable (private mode, blocked storage). The app must keep
      // working; the user just loses offline queueing, which we surface rather than crash on.
      setPending([]);
    }
  }, []);

  const sync = useCallback(async () => {
    setSyncing(true);
    try {
      const result = await syncQueuedIncidents(api);
      setLastResult(result);
      await refreshQueue();
      return result;
    } finally {
      setSyncing(false);
    }
  }, [refreshQueue]);

  /** How fresh the offline copy of the network is, for the field-readiness readout. */
  const refreshCacheStatus = useCallback(async () => {
    const [segments, storage] = await Promise.all([
      readReference("segments"),
      estimateStorage(),
    ]);
    setCacheStatus({
      age: segments ? describeCacheAge(segments) : null,
      cachedAt: segments?.cached_at || null,
      storage,
    });
  }, []);

  /** Download everything needed to work offline, then report what we now hold. */
  const prepareOffline = useCallback(async () => {
    const result = await primeOfflineCache(api);
    await refreshCacheStatus();
    return result;
  }, [refreshCacheStatus]);

  useEffect(() => {
    refreshQueue();
    refreshCacheStatus();

    const goOnline = () => {
      setOnline(true);
      sync();
      // Back in coverage: top up the offline snapshot while we can. The next dead spot is
      // usually minutes away, not days.
      primeOfflineCache(api).then(refreshCacheStatus);
    };
    const goOffline = () => setOnline(false);

    // The service worker wakes on OS-level connectivity restore and asks us to flush, which
    // covers the common case of the phone being back in signal while the tab is backgrounded.
    const onMessage = (event) => {
      if (event.data?.type === "SYNC_INCIDENTS") sync();
    };
    navigator.serviceWorker?.addEventListener?.("message", onMessage);

    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      navigator.serviceWorker?.removeEventListener?.("message", onMessage);
    };
  }, [refreshQueue, sync, refreshCacheStatus]);

  const value = useMemo(
    () => ({
      online,
      pending,
      pendingCount: pending.length,
      syncing,
      lastResult,
      sync,
      refreshQueue,
      cacheStatus,
      prepareOffline,
      offlineReady: Boolean(cacheStatus.age),
    }),
    [online, pending, syncing, lastResult, sync, refreshQueue, cacheStatus, prepareOffline]
  );

  return <SyncContext.Provider value={value}>{children}</SyncContext.Provider>;
}

export function useSync() {
  const context = useContext(SyncContext);
  if (!context) throw new Error("useSync must be used inside a SyncProvider");
  return context;
}
