// src/utils/offlineStore.js
//
// Durable on-device cache of the reference data the app needs to keep working with no
// connectivity at all.
//
// Large parts of Arunachal, Mizoram and interior Manipur have no usable mobile data, and
// that is precisely where a blocked road most needs reporting and a convoy most needs
// re-routing. A field user who opens the app in one of those places should still see the
// corridor network, still be able to plan a route, and still be able to file a report — the
// only thing they should lose is freshness, and the app should say so rather than pretend.
//
// Reference data (locations, corridor conditions, cargo profiles, transport rate cards) is
// refreshed opportunistically whenever a request succeeds, and read from here when it fails.
// Every cached entry carries the time it was stored so the UI can tell the operator how old
// the picture is.

// The database schema and connection live in idb.js, which is the only module allowed an
// opinion about either — see the note there about the version clash that made that necessary.
import { PHOTO_STORE, REFERENCE_STORE, run } from "./idb";

// ---------------------------------------------------------------- reference cache

export async function cacheReference(key, value) {
  try {
    await run(REFERENCE_STORE, "readwrite", (store) =>
      store.put({ key, value, cached_at: new Date().toISOString() })
    );
  } catch {
    // A cache write failing must never break the request that succeeded.
  }
}

export async function readReference(key) {
  try {
    return (await run(REFERENCE_STORE, "readonly", (store) => store.get(key))) || null;
  } catch {
    return null;
  }
}

/** Age of the cached copy in hours, or null if we have never cached it. */
export function cacheAgeHours(entry) {
  if (!entry?.cached_at) return null;
  return (Date.now() - new Date(entry.cached_at).getTime()) / 3600000;
}

export function describeCacheAge(entry) {
  const hours = cacheAgeHours(entry);
  if (hours === null) return "never synced";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min old`;
  if (hours < 48) return `${Math.round(hours)} h old`;
  return `${Math.round(hours / 24)} days old`;
}

/**
 * Pull down everything needed to run offline and store it.
 *
 * Called when the app is online so that going offline later is a non-event. Failures are
 * swallowed deliberately: a partial cache is better than none, and this runs in the
 * background where an error dialog would be noise.
 */
export async function primeOfflineCache(api) {
  const jobs = [
    ["locations", () => api.getLocations()],
    ["segments", () => api.getSegments()],
    ["cargo-types", () => api.getCargoTypes()],
    ["transport-modes", () => api.getTransportModes()],
    ["accessibility-summary", () => api.getAccessibilitySummary()],
    ["dashboard", () => api.getDashboard()],
  ];
  const results = await Promise.allSettled(
    jobs.map(async ([key, fetcher]) => {
      const value = await fetcher();
      await cacheReference(key, value);
      return key;
    })
  );
  return {
    cached: results.filter((r) => r.status === "fulfilled").length,
    total: jobs.length,
    at: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------- photos

/**
 * Shrink a captured photo before storing it.
 *
 * A phone camera JPEG is several megabytes; over a 2G link in a valley that is a sync that
 * never finishes. Resizing to 1024 px and re-encoding gets a legible photograph of a washed
 * out culvert down to roughly 100-200 KB, which will actually get through.
 */
export function compressImage(file, maxDimension = 1024, quality = 0.7) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the selected image"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("Could not decode the selected image"));
      img.onload = () => {
        const scale = Math.min(1, maxDimension / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve({
          dataUrl: canvas.toDataURL("image/jpeg", quality),
          width: canvas.width,
          height: canvas.height,
        });
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

export async function storePhoto(clientUuid, dataUrl) {
  await run(PHOTO_STORE, "readwrite", (store) =>
    store.put({ client_uuid: clientUuid, data_url: dataUrl, stored_at: new Date().toISOString() })
  );
}

export async function readPhoto(clientUuid) {
  try {
    return (await run(PHOTO_STORE, "readonly", (store) => store.get(clientUuid))) || null;
  } catch {
    return null;
  }
}

export async function deletePhoto(clientUuid) {
  try {
    await run(PHOTO_STORE, "readwrite", (store) => store.delete(clientUuid));
  } catch {
    // Best effort; an orphaned thumbnail is harmless.
  }
}

export async function estimateStorage() {
  if (!navigator.storage?.estimate) return null;
  try {
    const { usage, quota } = await navigator.storage.estimate();
    return { usage, quota, percent: quota ? Math.round((usage / quota) * 100) : null };
  } catch {
    return null;
  }
}
