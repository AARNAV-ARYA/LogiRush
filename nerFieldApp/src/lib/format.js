// src/lib/format.js
// Display helpers shared by the field app's screens.

/**
 * A distance at the precision it deserves: metres when it is metres, kilometres otherwise.
 * Rounding 0.6 km to "1 km" throws away the thing that makes the number worth showing.
 */
export function formatDistance(km) {
  if (km === null || km === undefined) return "—";
  const value = Number(km);
  if (!Number.isFinite(value)) return "—";
  if (value < 1) return `${Math.round(value * 1000)} m`;
  if (value < 10) return `${value.toFixed(1)} km`;
  return `${Math.round(value).toLocaleString("en-IN")} km`;
}

/**
 * One line saying where a report landed on the corridor network.
 *
 * The honest version of this has two cases, and the second one matters more: a report the
 * server could not tie to any corridor will not affect a single route, and the reporter is
 * the only person who can tell whether that is a bad coordinate or genuinely remote ground.
 * Saying nothing — which is what the app did before — leaves them assuming it counted.
 */
export function attributionLine(attribution) {
  if (!attribution) return null;
  if (attribution.on_network) {
    return `Matched to ${attribution.segment_label} · ${formatDistance(attribution.distance_km)} from it`;
  }
  return `No corridor within ${attribution.snap_radius_km} km — nearest is ${formatDistance(
    attribution.distance_km
  )} away, so this will not affect routing. Check the coordinates.`;
}
