/* The same palette as the web console, so a verifier looking at a report on the wall and the
   reporter who filed it on a phone are reading the same colours for the same things.

   Values are duplicated rather than imported because the two apps are separate bundles with
   no shared package; the web copy in index.css is the source of truth, and the comment above
   each group says what the colour is *for*, so a change stays traceable across both. */
export const T = {
  plane: "#070a0e",
  surface: "#0f141b",
  surfaceRaised: "#161d26",
  surfaceSunken: "#0a0e13",
  hairline: "rgba(255,255,255,0.08)",
  hairlineStrong: "rgba(255,255,255,0.14)",

  ink: "#e6edf5",
  inkSecondary: "#9fb2c6",
  inkMuted: "#6d8299",

  accent: "#38bdf8",
  onAccent: "#04202b",

  // sequential ramp: corridor impediment. brighter = worse.
  imp: ["#5a4c3c", "#8f6129", "#c9782b", "#f0a24c", "#ffcd93"],

  // reserved status roles — state, never magnitude
  good: "#0ca30c",
  goodText: "#5ec95e",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  criticalText: "#f08a8a",
};

/** Severity 1-5 to a ramp step, matching the web app's encoding exactly. */
export const severityColor = (s) => T.imp[Math.min(4, Math.max(0, (s || 1) - 1))];

export const SEVERITY_HINTS = {
  1: "Minor — traffic largely unaffected",
  2: "Slight — some slowing",
  3: "Moderate — one lane or partial obstruction",
  4: "Serious — heavy delays, difficult passage",
  5: "Severe — road impassable",
};

export const INCIDENT_TYPES = [
  { id: "landslide", label: "Landslide" },
  { id: "flood", label: "Flood" },
  { id: "road_block", label: "Road block" },
  { id: "bridge_damage", label: "Bridge damage" },
  { id: "accident", label: "Accident" },
  { id: "other", label: "Other" },
];

export const typeLabel = (id) =>
  INCIDENT_TYPES.find((t) => t.id === id)?.label || id;
