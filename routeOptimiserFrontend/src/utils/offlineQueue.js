// src/utils/offlineQueue.js
// Offline operation (SIH Module 6).
//
// Field users in NER frequently have no connectivity exactly when an incident most needs
// reporting. This queue lets a report be created offline, stored durably on the device, and
// synced automatically when connectivity returns.
//
// Why IndexedDB rather than localStorage: it survives larger payloads (a report can carry a
// photo), it is transactional, and it is available inside a service worker context.
//
// Sync safety: every report gets a client-generated UUID at creation time on the device. The
// server treats that UUID as unique, so replaying a queued report that already reached the
// server is a no-op instead of a duplicate. That means a failed sync can always be retried
// safely — the client never has to reason about whether a request "half succeeded".

// The queue lives in the shared database defined by idb.js. It used to open
// "ner-logistics" at version 1 on its own, which stopped working the moment the reference
// cache took the same database to version 2 — see idb.js for what that broke.
import { QUEUE_STORE, run } from "./idb";

export function newClientUuid() {
  if (crypto?.randomUUID) return crypto.randomUUID();
  // Fallback for older browsers / insecure contexts.
  return `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function queueIncident(incident) {
  const record = {
    ...incident,
    client_uuid: incident.client_uuid || newClientUuid(),
    queued_at: new Date().toISOString(),
    attempts: 0,
  };
  await run(QUEUE_STORE, "readwrite", (store) => store.put(record));
  return record;
}

export async function getQueuedIncidents() {
  return (await run(QUEUE_STORE, "readonly", (store) => store.getAll())) || [];
}

export async function removeQueuedIncidents(clientUuids) {
  if (!clientUuids?.length) return;
  await run(QUEUE_STORE, "readwrite", (store) => {
    clientUuids.forEach((id) => store.delete(id));
    return null;
  });
}

export async function markAttempt(clientUuid) {
  // Read-modify-write inside one transaction, so a concurrent sync cannot lose a count.
  // Returning null keeps run() from taking over the get request's success handler.
  await run(QUEUE_STORE, "readwrite", (store) => {
    const getRequest = store.get(clientUuid);
    getRequest.onsuccess = () => {
      const record = getRequest.result;
      if (record) {
        record.attempts = (record.attempts || 0) + 1;
        record.last_attempt_at = new Date().toISOString();
        store.put(record);
      }
    };
    return null;
  });
}

/**
 * Flush the queue to the server.
 *
 * Items that the server confirms as `created` or `duplicate` are removed from the queue —
 * a duplicate means the server already has it, so keeping it would retry forever. Items that
 * error are kept for a later attempt, with the attempt count recorded so the UI can surface
 * a report that keeps failing rather than silently retrying it into the void.
 */
export async function syncQueuedIncidents(api) {
  const queued = await getQueuedIncidents();
  if (!queued.length) return { synced: 0, failed: 0, remaining: 0 };

  // Strip local bookkeeping fields; the server only wants the incident itself.
  const LOCAL_ONLY_FIELDS = ["queued_at", "attempts", "last_attempt_at"];
  const payload = queued.map((item) => {
    const incident = { ...item };
    LOCAL_ONLY_FIELDS.forEach((field) => delete incident[field]);
    return incident;
  });

  let response;
  try {
    response = await api.syncIncidents(payload);
  } catch {
    // Still offline or server unreachable — keep everything queued, count one attempt each.
    await Promise.all(queued.map((item) => markAttempt(item.client_uuid)));
    return { synced: 0, failed: queued.length, remaining: queued.length, offline: true };
  }

  const settled = (response.results || [])
    .filter((r) => r.status === "created" || r.status === "duplicate")
    .map((r) => r.client_uuid)
    .filter(Boolean);

  const failed = (response.results || []).filter((r) => r.status === "error");
  await removeQueuedIncidents(settled);
  await Promise.all(failed.map((r) => r.client_uuid && markAttempt(r.client_uuid)));

  return {
    synced: settled.length,
    failed: failed.length,
    remaining: (await getQueuedIncidents()).length,
  };
}

/** Register automatic sync whenever the browser regains connectivity. */
export function registerAutoSync(api, onResult) {
  const handler = async () => {
    const result = await syncQueuedIncidents(api);
    if (onResult) onResult(result);
  };
  window.addEventListener("online", handler);
  return () => window.removeEventListener("online", handler);
}
