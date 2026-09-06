// src/lib/accessibility.js
// Single source of truth for how an accessibility score is presented.
//
// The bands mirror the backend's CATEGORY_BANDS exactly (accessibility_engine.py). If the
// backend's thresholds ever change, this is the one place the UI needs updating — and the
// e2e tests assert the two agree, so a drift shows up as a failing test rather than a
// map that quietly disagrees with the API.
//
// Colour
// ------
// These five bands are an ORDERED MAGNITUDE, so they use one hue stepped by lightness
// rather than five different hues. The previous green → lime → yellow → orange → red scale
// was a rainbow, and it failed on its own terms: lime against yellow measures ΔE 2.3 under
// protanopia (8 is the target), so two adjacent bands were indistinguishable to a
// red-green colourblind operator, and because amber is the lightest of those hues the scale
// did not read as ordered in greyscale or through a projector either.
//
// The ramp below is validated: one hue (17° spread), monotone lightness, every adjacent
// gap ≥ 0.06 L, and the dimmest step still clears the panel surface at 2.25:1. It encodes
// IMPEDIMENT, so a good corridor is dim bronze that recedes and a failing one glows — on a
// dark map the eye goes to the trouble, which is the whole job of the screen.
//
// Secondary encoding
// ------------------
// On the map a corridor's colour would otherwise carry the meaning alone, so every band
// also carries a stroke width and a dash pattern (`weight`, `dash`). A degraded road is
// thin and broken even in greyscale. `impassable` is a STATE, not a magnitude, so it uses
// the reserved critical status colour with an icon and label rather than a ramp step.

export const ACCESSIBILITY_BANDS = [
  { min: 80, max: 100, label: "Excellent", color: "#5a4c3c", text: "text-ink-secondary", bg: "bg-white/5",             border: "border-white/10",              weight: 5, dash: null,      icon: "●" },
  { min: 60, max: 80,  label: "Good",      color: "#8f6129", text: "text-[#c08a4e]",     bg: "bg-[#8f6129]/12",        border: "border-[#8f6129]/35",          weight: 4, dash: null,      icon: "●" },
  { min: 40, max: 60,  label: "Moderate",  color: "#c9782b", text: "text-[#c9782b]",     bg: "bg-[#c9782b]/12",        border: "border-[#c9782b]/35",          weight: 4, dash: "10 5",    icon: "◐" },
  { min: 20, max: 40,  label: "Poor",      color: "#f0a24c", text: "text-[#f0a24c]",     bg: "bg-[#f0a24c]/12",        border: "border-[#f0a24c]/35",          weight: 3, dash: "6 6",     icon: "◔" },
  { min: 0,  max: 20,  label: "Critical",  color: "#ffcd93", text: "text-[#ffcd93]",     bg: "bg-[#ffcd93]/12",        border: "border-[#ffcd93]/40",          weight: 3, dash: "2 6",     icon: "○" },
];

/** Reserved status roles. State, never magnitude — and never reused as a series colour. */
export const STATUS_COLORS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
};

/** Fixed categorical order for transport-mode series. Validated for CVD on the panel surface. */
export const SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500"];

/** A closed corridor is a state, so it gets the critical status colour plus its own dash. */
export const IMPASSABLE_STYLE = { color: STATUS_COLORS.critical, weight: 3, dash: "1 7", icon: "✕" };

export function bandForScore(score) {
  if (score === null || score === undefined || Number.isNaN(score)) {
    return { label: "Unknown", color: "#6d8299", text: "text-ink-muted", bg: "bg-white/5", border: "border-white/10", weight: 2, dash: "3 5", icon: "?" };
  }
  // Top band is inclusive at 100; the rest are [min, max).
  return (
    ACCESSIBILITY_BANDS.find((b) => (b.min === 80 ? score >= 80 : score >= b.min && score < b.max)) ||
    ACCESSIBILITY_BANDS[ACCESSIBILITY_BANDS.length - 1]
  );
}

export function accessibilityColor(score) {
  return bandForScore(score).color;
}

export function accessibilityTextClass(score) {
  return bandForScore(score).text;
}

/** Everything the map needs to draw a corridor so colour is never the only signal. */
export function corridorStyle(score, impassable = false) {
  if (impassable) {
    return { color: IMPASSABLE_STYLE.color, weight: IMPASSABLE_STYLE.weight, dashArray: IMPASSABLE_STYLE.dash };
  }
  const band = bandForScore(score);
  return { color: band.color, weight: band.weight, dashArray: band.dash };
}

/** Risk is "higher is worse" — the same ramp, read from the other end. */
export function riskColor(percent) {
  if (percent === null || percent === undefined) return "#6d8299";
  if (percent >= 75) return "#ffcd93";
  if (percent >= 55) return "#f0a24c";
  if (percent >= 35) return "#c9782b";
  return "#8f6129";
}

export function riskTextClass(percent) {
  if (percent === null || percent === undefined) return "text-ink-muted";
  if (percent >= 75) return "text-[#ffcd93]";
  if (percent >= 55) return "text-[#f0a24c]";
  if (percent >= 35) return "text-[#c9782b]";
  return "text-ink-secondary";
}

export const INCIDENT_TYPE_LABELS = {
  landslide: "Landslide",
  flood: "Flood",
  road_block: "Road Block",
  bridge_damage: "Bridge Damage",
  accident: "Accident",
  other: "Other",
};

export function incidentLabel(type) {
  return INCIDENT_TYPE_LABELS[type] || type;
}
