// src/api/client.js
// Central API client.
//
// The backend URL comes from VITE_API_BASE_URL so the same build can point at localhost in
// development and at the deployed backend in production. It falls back to the original
// hardcoded localhost:5001 so existing local workflows keep working with no .env file.

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:5001"
).replace(/\/$/, "");

export { API_BASE_URL };

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/* The bearer token lives here rather than in React state so that every caller — including
   the offline sync worker, which runs outside the component tree — sends it automatically.
   It is mirrored into localStorage so a refresh does not sign the operator out mid-shift. */
const TOKEN_KEY = "ner.auth.token";
let authToken = null;
try {
  authToken = localStorage.getItem(TOKEN_KEY);
} catch {
  // Private mode or blocked storage: the session simply will not survive a reload.
}

export function setAuthToken(token) {
  authToken = token || null;
  // Responses are scoped to the caller's role, so a cached read from the previous session
  // must never be handed to the next one.
  clearReadCache();
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* non-fatal */
  }
}

export function getAuthToken() {
  return authToken;
}

/*
  Read caching and in-flight de-duplication.

  Screens here overlap heavily: the dashboard opens five requests at once, the map opens
  three, and both ask for the same corridor assessment and the same 27 locations. Navigating
  between them refetched everything each time, so the network graph looked like a stall even
  though every answer was already on the machine.

  Two mechanisms, both small:

    * De-duplication — identical GETs issued while one is still in flight share that one
      promise. This is what stops a page mount from opening the same request three times.
    * A short freshness window per endpoint — long enough to cover a page transition, far
      shorter than the polling interval that keeps the screen live. Reference data that only
      changes on a deploy (locations, cargo types, transport modes) gets minutes; live
      condition data gets seconds.

  Anything that writes clears the whole read cache, because a new incident changes the
  corridor assessment, the dashboard and the analytics all at once. Erring towards clearing
  too much is right here: a needless refetch costs a few milliseconds, a stale road status
  costs someone a wasted drive.
*/
const SECOND = 1000;
const FRESHNESS_MS = [
  // Fixed for the life of a deployment.
  [/^\/api\/ner\/(locations|cargo-types|transport-modes|model-info|data-sources)/, 5 * 60 * SECOND],
  // Live network condition. The screens that show it poll on their own; this only has to
  // survive a page transition.
  [/^\/api\/ner\/(segments|dashboard|analytics|accessibility-summary|road-segments)/, 10 * SECOND],
  // Place lookups are network round trips to OpenStreetMap and are worth holding longer.
  [/^\/api\/ner\/places\//, 5 * 60 * SECOND],
];

function freshnessFor(path) {
  const match = FRESHNESS_MS.find(([pattern]) => pattern.test(path));
  return match ? match[1] : 0;
}

const readCache = new Map();   // path -> { at, body }
const inFlight = new Map();    // path -> Promise

export function clearReadCache() {
  readCache.clear();
}

async function send(path, options) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });

  let body = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON response (proxy error page, gateway timeout) — keep body null.
  }

  if (!response.ok) {
    throw new ApiError(body?.message || `Request failed (${response.status})`, response.status);
  }
  return body;
}

async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();

  if (method !== "GET") {
    // A write can change anything a read returned, so nothing survives it.
    clearReadCache();
    inFlight.clear();
    return send(path, options);
  }

  const ttl = freshnessFor(path);
  if (ttl > 0) {
    const hit = readCache.get(path);
    if (hit && Date.now() - hit.at < ttl) return hit.body;
  }

  const pending = inFlight.get(path);
  if (pending) return pending;

  const promise = send(path, options)
    .then((body) => {
      if (ttl > 0) readCache.set(path, { at: Date.now(), body });
      return body;
    })
    .finally(() => {
      inFlight.delete(path);
    });

  inFlight.set(path, promise);
  return promise;
}

/** Force the next read of these paths to go to the network (used by "refresh" controls). */
export function invalidateReads(pathPrefix) {
  for (const key of readCache.keys()) {
    if (!pathPrefix || key.startsWith(pathPrefix)) readCache.delete(key);
  }
}

export const api = {
  // --- session ---
  login: (username, password) =>
    request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request("/api/auth/logout", { method: "POST" }),
  me: () => request("/api/auth/me"),
  getRoles: () => request("/api/auth/roles"),

  // --- read ---
  health: () => request("/api/ner/health"),
  getLocations: () => request("/api/ner/locations"),
  getSegments: () => request("/api/ner/segments"),
  getSegment: (id) => request(`/api/ner/road-segments/${id}`),
  getDashboard: () => request("/api/ner/dashboard"),
  getAnalytics: () => request("/api/ner/analytics"),
  getAccessibilitySummary: () => request("/api/ner/accessibility-summary"),
  getCargoTypes: () => request("/api/ner/cargo-types"),
  getTransportModes: () => request("/api/ner/transport-modes"),
  getModelInfo: () => request("/api/ner/model-info"),
  // Provenance for every input on every screen. Served by the backend rather than written
  // into the UI so the claim shown to an operator cannot drift from the code that loads it.
  getDataSources: () => request("/api/ner/data-sources"),

  // --- routing ---
  planRoute: (payload) =>
    request("/api/ner/plan-route", { method: "POST", body: JSON.stringify(payload) }),

  // --- places ---
  searchPlaces: (q, limit = 8) =>
    request(`/api/ner/places/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  nearbyPlaces: (lat, lon, radiusKm = 5) =>
    request(`/api/ner/places/nearby?lat=${lat}&lon=${lon}&radius_km=${radiusKm}`),
  resolvePlace: (lat, lon) =>
    request(`/api/ner/places/resolve?lat=${lat}&lon=${lon}`),

  // --- incidents ---
  getIncidents: (limit = 50) => request(`/api/ner/incidents?limit=${limit}`),
  // Dry run: which corridor would a report at this coordinate be filed against? Nothing is
  // stored, so the report form can answer that while the coordinate is still editable.
  previewIncidentAttribution: (lat, lon) =>
    request(`/api/ner/incidents/preview?lat=${lat}&lon=${lon}`),
  reportIncident: (payload) =>
    request("/api/ner/incidents", { method: "POST", body: JSON.stringify(payload) }),
  // Incident lifecycle. Each is a distinct decision with its own authorisation rule, so
  // each gets its own endpoint rather than one call with a status string.
  verifyIncident: (id) =>
    request(`/api/ner/incidents/${id}/verify`, { method: "POST" }),
  rejectIncident: (id, reason) =>
    request(`/api/ner/incidents/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  resolveIncident: (id, reason) =>
    request(`/api/ner/incidents/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  withdrawIncident: (id) =>
    request(`/api/ner/incidents/${id}/withdraw`, { method: "POST" }),
  deleteIncident: (id, reason) =>
    request(`/api/ner/incidents/${id}`, {
      method: "DELETE",
      body: JSON.stringify({ reason }),
    }),
  getIncidentAudit: (id) => request(`/api/ner/incidents/${id}/audit`),

  syncIncidents: (incidents) =>
    request("/api/ner/incidents/sync", {
      method: "POST",
      body: JSON.stringify({ incidents }),
    }),

  // --- shipments ---
  getShipments: (status) =>
    request(`/api/ner/shipments${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  getShipment: (id) => request(`/api/ner/shipments/${id}`),
  createShipment: (payload) =>
    request("/api/ner/shipments", { method: "POST", body: JSON.stringify(payload) }),
  updateShipmentStatus: (id, status) =>
    request(`/api/ner/shipments/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  replanShipment: (id, updateSnapshot = false) =>
    request(`/api/ner/shipments/${id}/replan`, {
      method: "POST",
      body: JSON.stringify({ update_snapshot: updateSnapshot }),
    }),
};

export { ApiError };
