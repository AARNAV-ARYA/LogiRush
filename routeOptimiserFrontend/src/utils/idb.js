// src/utils/idb.js
//
// The one place that knows how this application's IndexedDB database is shaped.
//
// It exists because it went wrong. `offlineQueue.js` opened "ner-logistics" at version 1 and
// `offlineStore.js` opened the same database at version 2, having added the reference and
// photo stores. IndexedDB refuses to open a database at a version lower than the one on
// disk, so once anything touched the store — the offline-readiness panel does, on the report
// screen — every later call from the queue module threw
//
//     VersionError: The requested version (1) is less than the existing version (2)
//
// and the queue silently stopped accepting reports. That is the worst possible failure for
// this feature: a field user submits a report with no signal, is told it is safe on the
// device, and it is not there at all. Two modules cannot each hold an opinion about the
// schema, so now neither does.
//
// Adding a store: add it to STORES and bump DB_VERSION. Upgrades must stay additive — a
// device may be carrying unsynced reports, and losing them is losing field observations
// nobody can reproduce.

const DB_NAME = "ner-logistics";
const DB_VERSION = 2;

export const QUEUE_STORE = "pending_incidents";     // v1
export const REFERENCE_STORE = "reference";         // v2
export const PHOTO_STORE = "photos";                // v2

const STORES = [
  { name: QUEUE_STORE, options: { keyPath: "client_uuid" } },
  { name: REFERENCE_STORE, options: { keyPath: "key" } },
  { name: PHOTO_STORE, options: { keyPath: "client_uuid" } },
];

// One connection for the tab, rather than an open/close per operation. Opening a database is
// not free, and the queue does several operations per sync.
let connection = null;

function openDb() {
  if (connection) return connection;

  connection = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = () => {
      const db = request.result;
      for (const { name, options } of STORES) {
        if (!db.objectStoreNames.contains(name)) db.createObjectStore(name, options);
      }
    };

    request.onsuccess = () => {
      const db = request.result;
      // Another tab wanting a newer schema must not be blocked by this one holding the
      // database open. Close and forget it; the next operation reopens at the new version.
      db.onversionchange = () => {
        db.close();
        connection = null;
      };
      db.onclose = () => {
        connection = null;
      };
      resolve(db);
    };

    request.onerror = () => {
      connection = null;
      reject(request.error);
    };
    request.onblocked = () => {
      connection = null;
      reject(new Error("The offline database is open in another tab and could not be upgraded."));
    };
  });

  return connection;
}

/**
 * Run one transaction against one store.
 *
 * `fn(store)` may return a request, whose result becomes the resolved value — the common
 * case. When a caller needs to chain requests inside the same transaction (read-modify-write
 * on a queued report, say) it returns null instead and wires up its own handlers, and the
 * promise resolves once the transaction commits.
 */
export function run(storeName, mode, fn) {
  return openDb().then(
    (db) =>
      new Promise((resolve, reject) => {
        const transaction = db.transaction(storeName, mode);
        const store = transaction.objectStore(storeName);
        let out;

        const request = fn(store);
        if (request && typeof request === "object" && "onsuccess" in request) {
          request.onsuccess = () => {
            out = request.result;
          };
        }

        transaction.oncomplete = () => resolve(out);
        transaction.onerror = () => reject(transaction.error);
        transaction.onabort = () => reject(transaction.error || new Error("Transaction aborted"));
      })
  );
}
