// public/sw.js
// Service worker for offline operation (SIH Module 6).
//
// Strategy:
//   * App shell (HTML/JS/CSS)  -> cache-first, so the app opens with no connectivity at all.
//   * GET /api/ner/*           -> network-first with cache fallback, so a field user sees the
//                                 last known accessibility picture instead of an error screen.
//   * POST/PUT                 -> never cached. Incident submissions are queued in IndexedDB
//                                 by the app itself (see src/utils/offlineQueue.js), which is
//                                 durable and idempotent; caching writes here would risk
//                                 double-submission.

const CACHE_VERSION = "ner-v2";
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const DATA_CACHE = `${CACHE_VERSION}-data`;
const SHELL_ASSETS = ["/", "/index.html", "/manifest.webmanifest"];

// The build emits hashed asset filenames, so they cannot be listed here at author time.
// Instead every same-origin asset the app requests is added to the shell cache the first
// time it is fetched. After one online visit the whole app - JS, CSS, fonts, icons - is on
// the device, which is what makes a genuinely cold start work with no signal at all.
const PRECACHEABLE = /\.(?:js|css|woff2?|png|svg|jpg|jpeg|webp|ico)$/;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => !key.startsWith(CACHE_VERSION)).map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  if (request.method !== "GET") return; // writes go through the IndexedDB queue, not the SW

  const url = new URL(request.url);

  if (url.pathname.startsWith("/api/ner/")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(DATA_CACHE).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() =>
          caches.match(request).then(
            (cached) =>
              cached ||
              new Response(
                JSON.stringify({ status: "error", message: "Offline and no cached data available" }),
                { status: 503, headers: { "Content-Type": "application/json" } }
              )
          )
        )
    );
    return;
  }

  if (request.mode === "navigate") {
    // Network-first so a reconnected device picks up a new build, falling back to the cached
    // shell. Without the fallback the app would show the browser's offline page - useless to
    // someone standing at a washed-out culvert trying to file a report.
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(SHELL_CACHE).then((cache) => cache.put("/index.html", copy));
          return response;
        })
        .catch(() => caches.match("/index.html").then((cached) => cached || caches.match("/")))
    );
    return;
  }

  if (url.origin === self.location.origin && PRECACHEABLE.test(url.pathname)) {
    // Cache-first: hashed filenames mean a cached asset is never stale, and serving from
    // disk keeps the app instant on a slow connection as well as usable on none.
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          })
      )
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});

// Background sync: when the OS reports connectivity restored it wakes the worker, which asks
// any open tab to flush the queued reports. This matters because a field user typically
// pockets the phone the moment the form is submitted - the tab may never be focused again in
// coverage, and without this the reports would sit on the device unsent.
self.addEventListener("sync", (event) => {
  if (event.tag === "ner-sync-incidents") {
    event.waitUntil(
      self.clients.matchAll({ includeUncontrolled: true }).then((clients) => {
        clients.forEach((client) => client.postMessage({ type: "SYNC_INCIDENTS" }));
      })
    );
  }
});
