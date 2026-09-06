/* eslint-disable react/prop-types */
// src/components/ui.jsx
// Shared presentational primitives.
//
// PropTypes are disabled deliberately: React 19 no longer ships PropTypes and adding the
// package purely to satisfy a lint rule the rest of this codebase already doesn't follow
// would mean a new runtime dependency for no benefit.

import { Link } from "react-router-dom";

import { bandForScore, STATUS_COLORS } from "../lib/accessibility";

export const Card = ({ children, className = "", as: Tag = "div", ...rest }) => (
  <Tag className={`panel p-5 ${className}`} {...rest}>
    {children}
  </Tag>
);

export const SectionHeading = ({ children, action, hint }) => (
  <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
    <div className="min-w-0">
      <h2 className="text-[0.9375rem] font-semibold text-ink tracking-tight">{children}</h2>
      {hint ? <p className="text-xs text-ink-muted mt-0.5">{hint}</p> : null}
    </div>
    {action}
  </div>
);

/**
 * Live status dot.
 *
 * An operations screen has to answer "is this current?" without being asked. A quietly
 * pulsing dot does that in the corner of the eye; anything more insistent gets ignored
 * within an hour of a long shift.
 */
export const LiveDot = ({ tone = "good", label }) => (
  <span className="inline-flex items-center gap-1.5">
    <span
      className="w-1.5 h-1.5 rounded-full animate-live shrink-0"
      style={{ backgroundColor: STATUS_COLORS[tone] || STATUS_COLORS.good }}
      aria-hidden="true"
    />
    {label ? <span className="label-micro">{label}</span> : null}
  </span>
);

/**
 * Status pill.
 *
 * Tones map onto the reserved status roles, and each carries a glyph as well as a colour
 * so the meaning survives colourblindness, greyscale printing and a washed-out projector.
 */
export const Badge = ({ children, tone = "neutral", className = "", icon = true }) => {
  const tones = {
    neutral: "bg-white/5 text-ink-secondary border-white/10",
    success: "bg-[#0ca30c]/12 text-[#5ec95e] border-[#0ca30c]/40",
    warning: "bg-[#fab219]/12 text-[#fab219] border-[#fab219]/40",
    danger: "bg-[#d03b3b]/12 text-[#e97676] border-[#d03b3b]/45",
    info: "bg-accent/10 text-accent border-accent/35",
  };
  const glyphs = { success: "✓", warning: "!", danger: "✕", info: "i", neutral: null };
  const glyph = icon ? glyphs[tone] : null;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-xs font-medium whitespace-nowrap ${
        tones[tone] || tones.neutral
      } ${className}`}
    >
      {glyph ? <span aria-hidden="true" className="font-semibold opacity-80">{glyph}</span> : null}
      {children}
    </span>
  );
};

/** Accessibility score pill — colour and label always come from the shared band table. */
export const AccessibilityBadge = ({ score, showLabel = true, impassable = false }) => {
  const band = bandForScore(score);
  if (impassable) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-xs font-semibold bg-[#d03b3b]/15 text-[#e97676] border-[#d03b3b]/50">
        <span aria-hidden="true">✕</span> Impassable
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-xs font-medium ${band.bg} ${band.text} ${band.border}`}
      title={`Accessibility ${score}/100 — ${band.label}`}
    >
      {/* The glyph steps with the band, so the rating is legible without colour at all. */}
      <span aria-hidden="true" className="opacity-80">{band.icon}</span>
      <span className="font-semibold tabular-nums">{score ?? "—"}</span>
      {showLabel && <span className="opacity-75">{band.label}</span>}
    </span>
  );
};

/**
 * A single headline figure.
 *
 * The number is the loudest thing in the tile and wears plain ink rather than a colour,
 * because on this screen colour is spent on data, not on decoration. `tone` is available
 * for the rare figure that is genuinely a status readout.
 */
export const StatCard = ({ label, value, suffix, hint, tone, icon, trend }) => (
  <div className="panel p-4 hover:border-white/[0.14] transition-colors">
    <div className="flex items-center justify-between gap-2">
      <p className="label-micro truncate">{label}</p>
      {icon ? <span className="text-ink-muted shrink-0">{icon}</span> : null}
    </div>
    <p className={`stat-value mt-2 ${tone || "text-ink"}`}>
      {value ?? "—"}
      {value !== null && value !== undefined && suffix ? (
        <span className="text-sm text-ink-muted ml-1 font-normal">{suffix}</span>
      ) : null}
    </p>
    <div className="flex items-center gap-2 mt-1">
      {trend ? <span className="text-xs text-ink-secondary">{trend}</span> : null}
      {hint ? <p className="text-xs text-ink-muted">{hint}</p> : null}
    </div>
  </div>
);

export const Skeleton = ({ className = "h-4 w-full" }) => (
  <div className={`skeleton rounded ${className}`} aria-hidden="true" />
);

export const SkeletonCard = () => (
  <div className="panel p-5 space-y-3">
    <Skeleton className="h-3 w-24" />
    <Skeleton className="h-8 w-32" />
    <Skeleton className="h-3 w-20" />
  </div>
);

export const Spinner = ({ className = "w-4 h-4" }) => (
  <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path
      className="opacity-90"
      fill="currentColor"
      d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
    />
  </svg>
);

export const ErrorState = ({ message, onRetry, title = "Something went wrong" }) => (
  <div
    role="alert"
    className="rounded-xl border border-[#d03b3b]/40 bg-[#d03b3b]/10 px-5 py-4 text-[#f0b4b4]"
  >
    <p className="font-semibold">{title}</p>
    <p className="text-sm text-[#e59a9a] mt-1 break-words">{message}</p>
    {onRetry && (
      <button onClick={onRetry} className="btn-ghost mt-3">
        Try again
      </button>
    )}
  </div>
);

export const EmptyState = ({ title, description, action }) => (
  <div className="text-center py-10 px-4">
    <p className="text-ink font-medium">{title}</p>
    {description ? <p className="text-sm text-ink-muted mt-1">{description}</p> : null}
    {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
  </div>
);

/** Standing reminder that nothing here is real operational data. */
/* The standing honesty notice. It links to the provenance screen because "this data is
   synthetic" raises exactly one question — which parts? — and a notice that cannot answer it
   is decoration. */
export const DemoDataNotice = ({ compact = false }) => (
  <div
    className={`rounded-lg border border-[#fab219]/30 bg-[#fab219]/[0.07] text-[#e0b878] ${
      compact ? "px-3 py-2 text-xs" : "px-4 py-3 text-sm"
    }`}
  >
    <strong className="text-[#fab219]">Demonstration data.</strong>{" "}
    Road risk figures are synthetic and disruption probabilities come from a model trained on
    synthetic data. Not live government data — not for real operational decisions.{" "}
    <Link to="/data-sources" className="underline underline-offset-2 hover:text-[#fab219]">
      See exactly which inputs are live and which are not
    </Link>
    .
  </div>
);

export const Toggle = ({ options, value, onChange, ariaLabel }) => (
  <div
    role="group"
    aria-label={ariaLabel}
    className="inline-flex rounded-lg border border-white/10 bg-surface-sunken p-0.5"
  >
    {options.map((option) => (
      <button
        key={option.value}
        type="button"
        onClick={() => onChange(option.value)}
        aria-pressed={value === option.value}
        className={`px-3 py-1.5 text-xs rounded-md transition-colors min-h-[2.25rem] sm:min-h-0 ${
          value === option.value
            ? "bg-accent/15 text-accent"
            : "text-ink-muted hover:text-ink"
        }`}
      >
        {option.label}
      </button>
    ))}
  </div>
);
