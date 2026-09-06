/* eslint-disable react/prop-types */
/*
  Hand-drawn stroke icons.

  An icon set is a dependency that costs 40-80 kB for the dozen glyphs a screen this size
  actually uses, and field users load this over a valley uplink. These are drawn on a 24-grid
  with a 1.75 stroke so they hold their weight against Inter at label sizes and stay legible
  at the 20 px the rail renders them at.
*/
const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
};

export const IconDashboard = (p) => (
  <svg {...base} {...p}><rect x="3" y="3" width="7" height="8" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="11" width="7" height="10" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /></svg>
);

export const IconMap = (p) => (
  <svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18Z" /></svg>
);

export const IconRoute = (p) => (
  <svg {...base} {...p}><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="6" r="2.5" /><path d="M8.5 18h5a3.5 3.5 0 0 0 0-7h-3a3.5 3.5 0 0 1 0-7h5" /></svg>
);

export const IconTruck = (p) => (
  <svg {...base} {...p}><path d="M2 7.5h11v9H2z" /><path d="M13 10.5h4l3 3v3h-7z" /><circle cx="6.5" cy="18.5" r="1.8" /><circle cx="17" cy="18.5" r="1.8" /></svg>
);

export const IconAlert = (p) => (
  <svg {...base} {...p}><path d="M12 3.8 2.6 19.2a1.2 1.2 0 0 0 1 1.8h16.8a1.2 1.2 0 0 0 1-1.8Z" /><path d="M12 9.5v4.2" /><path d="M12 17.2h.01" /></svg>
);

export const IconReport = (p) => (
  <svg {...base} {...p}><path d="M12 21s7-5.4 7-11a7 7 0 1 0-14 0c0 5.6 7 11 7 11Z" /><path d="M12 7.2v5.6" /><path d="M9.2 10h5.6" /></svg>
);

export const IconMenu = (p) => (
  <svg {...base} {...p}><path d="M4 7h16M4 12h16M4 17h16" /></svg>
);

export const IconClose = (p) => (
  <svg {...base} {...p}><path d="M6 6l12 12M18 6L6 18" /></svg>
);

export const IconLayers = (p) => (
  <svg {...base} {...p}><path d="m12 3 9 5-9 5-9-5Z" /><path d="m3 13 9 5 9-5" /></svg>
);

export const IconChevron = (p) => (
  <svg {...base} {...p}><path d="m9 5 7 7-7 7" /></svg>
);
