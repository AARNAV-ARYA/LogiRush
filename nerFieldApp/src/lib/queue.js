import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Network from "expo-network";
import { api } from "./api";

/*
  The offline queue.

  This is the reason the app exists. A reporter is standing at a slip in a valley with no
  signal — the moment they have the most useful information is exactly the moment they can
  least send it. So submission never fails: it is written to the device first and sent when
  there is a network, which may be hours later on the drive back.

  Two properties make that safe:

    * Every report carries a client-generated UUID and the server de-duplicates on it, so a
      retry that actually succeeded but whose response was lost cannot create a second
      landslide in the record. This is why sync can be fired as often as we like.

    * `reported_at` is stamped on the device at the moment of observation, not on arrival.
      A report that syncs six hours later describes the road as it was six hours ago, and the
      backend's seven-day window measures from the event, not the upload.
*/

const QUEUE_KEY = "ner.queue.v1";
const SENT_KEY = "ner.sent.v1";

function uuid() {
  // crypto.randomUUID is not present on all RN runtimes; this is only an idempotency key,
  // not a security token, so a timestamp-plus-entropy form is sufficient and dependency-free.
  return (
    `${Date.now().toString(36)}-` +
    Array.from({ length: 4 }, () => Math.random().toString(36).slice(2, 8)).join("-")
  );
}

async function read(key) {
  try {
    return JSON.parse((await AsyncStorage.getItem(key)) || "[]");
  } catch {
    return [];
  }
}

async function write(key, value) {
  await AsyncStorage.setItem(key, JSON.stringify(value));
}

export const getQueue = () => read(QUEUE_KEY);
export const getSent = () => read(SENT_KEY);

/** Queue a report. Always succeeds — that is the point. */
export async function enqueue(report) {
  const queue = await read(QUEUE_KEY);
  const item = {
    ...report,
    client_uuid: report.client_uuid || uuid(),
    reported_at: report.reported_at || new Date().toISOString(),
    queued_at: new Date().toISOString(),
    attempts: 0,
    last_error: null,
  };
  queue.push(item);
  await write(QUEUE_KEY, queue);
  return item;
}

export async function isOnline() {
  try {
    const state = await Network.getNetworkStateAsync();
    return Boolean(state.isConnected && state.isInternetReachable !== false);
  } catch {
    return true; // if we cannot tell, try the network rather than refusing to
  }
}

/**
 * Push everything queued.
 *
 * A 4xx means the server rejected the *content*: retrying forever would pin a permanently
 * bad report at the head of the queue and block everything behind it, so those are dropped
 * from the queue and kept with their error for the reporter to see. Anything else — offline,
 * 5xx, timeout — stays queued, because the report is fine and the network is not.
 */
export async function sync() {
  const queue = await read(QUEUE_KEY);
  if (queue.length === 0) return { sent: 0, failed: 0, remaining: 0 };
  if (!(await isOnline())) return { sent: 0, failed: 0, remaining: queue.length, offline: true };

  const payload = queue.map(({ attempts, last_error, queued_at, ...rest }) => rest);

  let results;
  try {
    const response = await api.syncIncidents(payload);
    results = response.results || [];
  } catch {
    const bumped = queue.map((item) => ({ ...item, attempts: item.attempts + 1 }));
    await write(QUEUE_KEY, bumped);
    return { sent: 0, failed: 0, remaining: bumped.length, offline: true };
  }

  const byUuid = Object.fromEntries(results.map((r) => [r.client_uuid, r]));
  const stillQueued = [];
  const sentNow = [];

  for (const item of queue) {
    const outcome = byUuid[item.client_uuid];
    if (!outcome) {
      stillQueued.push({ ...item, attempts: item.attempts + 1 });
    } else if (outcome.status === "error") {
      sentNow.push({ ...item, server_status: "rejected", last_error: outcome.message });
    } else {
      sentNow.push({
        ...item,
        server_status: outcome.status,          // created | duplicate
        incident_id: outcome.incident_id,
        // Where the server decided this report belongs. Worth keeping: a fix taken under a
        // hillside can be a long way out, and this is the reporter's only chance to notice
        // that what they filed landed somewhere they did not mean.
        attribution: outcome.attribution || null,
        synced_at: new Date().toISOString(),
      });
    }
  }

  await write(QUEUE_KEY, stillQueued);
  const sent = await read(SENT_KEY);
  await write(SENT_KEY, [...sentNow, ...sent].slice(0, 100));

  const delivered = sentNow.filter((s) => s.server_status !== "rejected");
  return {
    // The most recent successful one, so the report screen can say where it landed rather
    // than only that it left the phone.
    lastAttribution: delivered.length ? delivered[delivered.length - 1].attribution : null,
    sent: delivered.length,
    failed: sentNow.filter((s) => s.server_status === "rejected").length,
    remaining: stillQueued.length,
  };
}
