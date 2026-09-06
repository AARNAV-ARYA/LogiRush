import Constants from "expo-constants";
import AsyncStorage from "@react-native-async-storage/async-storage";

/*
  The API client.

  The base URL defaults to 10.0.2.2, which is how the Android emulator reaches the host
  machine's localhost — the single most common thing to get wrong when running this against a
  laptop backend. On a physical handset it has to be the laptop's LAN address, so the app
  lets the reporter set it on the sign-in screen rather than requiring a rebuild.
*/

const API_PORT = 5001;

/**
 * Where is the backend?
 *
 * On a physical iPhone this is the single most common thing to get wrong: the phone is not
 * the laptop, so `localhost` means the phone itself and fails with no useful message. The
 * right answer is the laptop's address on the shared Wi-Fi — which is a value nobody should
 * have to look up, because Expo already knows it.
 *
 * When a project runs through Expo Go, `hostUri` is the address Metro is being served from
 * ("192.168.1.20:8081"): by definition the laptop, reachable from the phone, on this network.
 * Taking its host and swapping in the API port gets the backend right on the first launch,
 * on any network, with nothing typed in.
 *
 * Falls back to 10.0.2.2 (how the Android emulator reaches its host) and remains editable on
 * the Sign in screen for the cases this cannot infer — a tunnel, or a deployed backend.
 */
function inferBase() {
  /* A deployed backend, named once and baked into the bundle.

     This is the setting that makes the app and the web console one system rather than two.
     Left unset, the app talks to whatever laptop is serving Metro — which is the right
     default while developing and completely wrong in every other situation: reports filed
     from the phone land in that laptop's SQLite file and are invisible to the deployed
     console, which is exactly the "the databases are not connected" symptom. Setting
     EXPO_PUBLIC_API_BASE_URL to the same backend URL the website uses (VITE_API_BASE_URL)
     points both clients at one database.

     Expo inlines any EXPO_PUBLIC_* variable at bundle time, so this is read from a .env file
     next to package.json with nothing else to configure. */
  const configured =
    process.env.EXPO_PUBLIC_API_BASE_URL || Constants.expoConfig?.extra?.apiBaseUrl;
  if (configured) return configured.replace(/\/$/, "");

  const hostUri =
    Constants.expoConfig?.hostUri ||
    Constants.expoGoConfig?.debuggerHost ||
    Constants.manifest2?.extra?.expoGo?.debuggerHost ||
    "";
  const host = hostUri.split("/")[0].split(":")[0];

  // A tunnel serves Metro from an .exp.direct domain, which does not host the API — there is
  // nothing sensible to infer, so say so on the Sign in screen rather than guessing wrong.
  if (host && !host.endsWith(".exp.direct") && host !== "localhost" && host !== "127.0.0.1") {
    return `http://${host}:${API_PORT}`;
  }
  return `http://10.0.2.2:${API_PORT}`;
}

const DEFAULT_BASE = inferBase();

const BASE_KEY = "ner.api.base";
const TOKEN_KEY = "ner.auth.token";

let base = DEFAULT_BASE;
let token = null;

export async function loadSession() {
  const [storedBase, storedToken] = await Promise.all([
    AsyncStorage.getItem(BASE_KEY),
    AsyncStorage.getItem(TOKEN_KEY),
  ]);
  if (storedBase) base = storedBase;
  token = storedToken || null;
  return { base, token };
}

export async function setBase(url) {
  base = (url || DEFAULT_BASE).replace(/\/$/, "");
  await AsyncStorage.setItem(BASE_KEY, base);
}

export function getBase() {
  return base;
}

/** What the app worked out on its own, so the Sign in screen can offer it as a reset. */
export function getInferredBase() {
  return inferBase();
}

export async function setToken(value) {
  token = value || null;
  if (value) await AsyncStorage.setItem(TOKEN_KEY, value);
  else await AsyncStorage.removeItem(TOKEN_KEY);
}

export function getToken() {
  return token;
}

async function request(path, { method = "GET", body, timeoutMs = 12000 } = {}) {
  // A field connection either answers quickly or not at all. Without a timeout the fetch can
  // hang for the platform default — well over a minute — and the reporter is left holding a
  // spinner at a blocked road rather than being told to queue it and move on.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${base}${path}`, {
      method,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const error = new Error(payload?.message || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return payload;
  } finally {
    clearTimeout(timer);
  }
}

/* Every report this app files is stamped with where it came from, so the verifier reading
   the queue on the web console can see it was filed from a phone in the field rather than
   typed at a desk. Same endpoint, same table, same database as the console — the stamp is
   the only difference between the two channels. */
export const REPORT_SOURCE = "app";

export const api = {
  login: (username, password) =>
    request("/api/auth/login", { method: "POST", body: { username, password } }),
  me: () => request("/api/auth/me"),
  getSegments: () => request("/api/ner/segments"),
  getIncidents: (limit = 100) => request(`/api/ner/incidents?limit=${limit}`),
  reportIncident: (payload) =>
    request("/api/ner/incidents", { method: "POST", body: { source: REPORT_SOURCE, ...payload } }),
  syncIncidents: (incidents) =>
    request("/api/ner/incidents/sync", {
      method: "POST",
      body: { incidents: incidents.map((i) => ({ source: REPORT_SOURCE, ...i })) },
    }),
  withdrawIncident: (id) =>
    request(`/api/ner/incidents/${id}/withdraw`, { method: "POST" }),
};
