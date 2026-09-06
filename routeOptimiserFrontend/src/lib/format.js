// src/lib/format.js
// Display formatting helpers. Centralised so numbers look the same everywhere.

export function formatInr(value) {
  if (value === null || value === undefined) return "—";
  return `₹${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function formatHours(hours) {
  if (hours === null || hours === undefined) return "—";
  if (hours < 24) return `${Number(hours).toFixed(1)} h`;
  const days = Math.floor(hours / 24);
  const rest = Math.round(hours % 24);
  return rest ? `${days}d ${rest}h` : `${days}d`;
}

export function formatKm(km) {
  if (km === null || km === undefined) return "—";
  return `${Number(km).toLocaleString("en-IN", { maximumFractionDigits: 0 })} km`;
}

/**
 * A short distance, at the precision that distance deserves.
 *
 * `formatKm` rounds to whole kilometres, which is right for a 340 km corridor and useless
 * for "how far is this report from the road" — where the honest answers are 400 m, 3.2 km
 * and 1,756 km, and rounding the first to "0 km" turns a real measurement into a shrug.
 */
export function formatDistance(km) {
  if (km === null || km === undefined) return "—";
  const value = Number(km);
  if (!Number.isFinite(value)) return "—";
  if (value < 1) return `${Math.round(value * 1000)} m`;
  if (value < 10) return `${value.toFixed(1)} km`;
  return formatKm(value);
}

export function formatPercent(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(digits)}%`;
}

export function formatScore(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(1);
}

/** Relative time, e.g. "3 h ago". Field reports are judged mostly by how fresh they are. */
export function timeAgo(isoString) {
  if (!isoString) return "—";
  const then = new Date(isoString).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} d ago`;
  return new Date(isoString).toLocaleDateString("en-IN");
}

export function titleCase(value) {
  if (!value) return "";
  return String(value)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
