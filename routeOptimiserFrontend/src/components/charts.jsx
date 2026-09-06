/* eslint-disable react/prop-types */
// src/components/charts.jsx
// Hand-rolled SVG charts.
//
// Deliberately dependency-free. A charting library (Recharts, Chart.js) would add 100-200 kB
// to a bundle that field users may load over a weak connection, to draw four simple charts.
// Plain SVG is small, themeable with the same tokens as the rest of the UI, and accessible
// (each chart exposes a text summary for screen readers, and values are also available in
// the adjacent tables).

import { useState } from "react";
import { ACCESSIBILITY_BANDS, accessibilityColor, riskColor } from "../lib/accessibility";

// Chart ink. Grid and axis are deliberately recessive — the data should be the only
// thing with contrast on the panel. These mirror the tokens in index.css.
const INK = "#e6edf5";
const INK_MUTED = "#6d8299";
const GRID = "#1c242f";
const AXIS = "#2a3644";

/** Horizontal bars — used for per-state accessibility comparison. */
export const BarChart = ({ data, max = 100, valueSuffix = "", colorFor, ariaLabel }) => {
  if (!data?.length) return null;
  return (
    <div className="space-y-2.5" role="img" aria-label={ariaLabel}>
      {data.map((item) => {
        const pct = Math.max(0, Math.min(100, (item.value / max) * 100));
        const color = colorFor ? colorFor(item.value) : "#3987e5";
        return (
          <div key={item.label}>
            <div className="flex items-baseline justify-between gap-2 mb-1">
              <span className="text-sm text-ink-secondary truncate">{item.label}</span>
              <span className="text-sm font-semibold tabular-nums text-ink">
                {item.value?.toFixed ? item.value.toFixed(1) : item.value}
                {valueSuffix}
              </span>
            </div>
            {/* Thin mark, rounded data-end, anchored to the baseline. The track is a
                surface tint rather than a solid grey so it never competes with the value. */}
            <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden" title={`${item.label}: ${item.value}${valueSuffix}`}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, backgroundColor: color }}
              />
            </div>
            {item.sublabel ? (
              <p className="text-[11px] text-ink-muted mt-0.5">{item.sublabel}</p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
};

/** Single stacked bar showing how segments distribute across the five categories. */
export const DistributionBar = ({ distribution }) => {
  const total = distribution.reduce((sum, d) => sum + d.count, 0);
  if (!total) return null;

  // Derived from the shared band table rather than restated here. A private copy is how a
  // chart ends up quietly disagreeing with the map about what "Poor" looks like.
  const colorByCategory = Object.fromEntries(
    ACCESSIBILITY_BANDS.map((b) => [b.label, b.color])
  );
  const iconByCategory = Object.fromEntries(
    ACCESSIBILITY_BANDS.map((b) => [b.label, b.icon])
  );

  return (
    <div>
      <div
        className="flex h-3 rounded-full overflow-hidden bg-white/[0.06]"
        role="img"
        aria-label={distribution.map((d) => `${d.category}: ${d.count}`).join(", ")}
      >
        {distribution.map((d) =>
          d.count > 0 ? (
            <div
              key={d.category}
              style={{
                width: `${(d.count / total) * 100}%`,
                backgroundColor: colorByCategory[d.category],
              }}
              title={`${d.category}: ${d.count} of ${total}`}
            />
          ) : null
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3">
        {distribution.map((d) => (
          <div key={d.category} className="flex items-center gap-1.5 text-xs">
            <span
              className="w-2.5 h-2.5 rounded-sm shrink-0"
              style={{ backgroundColor: colorByCategory[d.category] }}
            />
            <span className="text-ink-secondary">
              <span aria-hidden="true" className="mr-1 opacity-70">{iconByCategory[d.category]}</span>
              {d.category}
            </span>
            <span className="text-ink font-semibold tabular-nums">{d.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

/**
 * Accessibility (x) against predicted disruption risk (y).
 *
 * The top-left quadrant — low accessibility, high risk — is where operational attention
 * belongs, so it is shaded. This is the one view that makes "which corridors are actually
 * in trouble" obvious at a glance.
 */
export const RiskScatter = ({ points, onSelect, selectedId }) => {
  const width = 520;
  const height = 300;
  const pad = { top: 16, right: 16, bottom: 36, left: 44 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const valid = points.filter(
    (p) => p.accessibility !== null && p.disruption_percent !== null
  );

  const x = (accessibility) => pad.left + (accessibility / 100) * plotW;
  const y = (risk) => pad.top + (1 - risk / 100) * plotH;

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full min-w-[420px]"
        role="img"
        aria-label={`Scatter plot of ${valid.length} corridors: accessibility against predicted disruption risk`}
      >
        {/* Danger quadrant: accessibility below 50, risk above 50 */}
        <rect
          x={x(0)}
          y={y(100)}
          width={x(50) - x(0)}
          height={y(50) - y(100)}
          fill="#ffb970"
          opacity="0.05"
        />
        <text x={x(2)} y={y(96)} fill="#ffb970" fontSize="10" opacity="0.8">
          needs attention
        </text>

        {[0, 25, 50, 75, 100].map((tick) => (
          <g key={`grid-${tick}`}>
            <line
              x1={x(tick)}
              y1={pad.top}
              x2={x(tick)}
              y2={pad.top + plotH}
              stroke={GRID}
              strokeWidth="1"
            />
            <line
              x1={pad.left}
              y1={y(tick)}
              x2={pad.left + plotW}
              y2={y(tick)}
              stroke={GRID}
              strokeWidth="1"
            />
            <text x={x(tick)} y={height - 14} fill={INK_MUTED} fontSize="10" textAnchor="middle">
              {tick}
            </text>
            <text x={pad.left - 8} y={y(tick) + 3} fill={INK_MUTED} fontSize="10" textAnchor="end">
              {tick}
            </text>
          </g>
        ))}

        <text
          x={pad.left + plotW / 2}
          y={height - 1}
          fill={INK_MUTED}
          fontSize="11"
          textAnchor="middle"
        >
          Accessibility →
        </text>
        <text
          x={12}
          y={pad.top + plotH / 2}
          fill={INK_MUTED}
          fontSize="11"
          textAnchor="middle"
          transform={`rotate(-90 12 ${pad.top + plotH / 2})`}
        >
          Disruption risk →
        </text>

        {valid.map((p) => {
          const selected = p.id === selectedId;
          return (
            <circle
              key={p.id}
              cx={x(p.accessibility)}
              cy={y(p.disruption_percent)}
              r={selected ? 8 : p.impassable ? 6 : 5}
              /* Position already carries accessibility and risk. Colouring every dot by
                 accessibility as well made the whole plot one hue and hid the outlier, so
                 dots are neutral and the critical status colour is spent only on a closed
                 corridor — the one thing a reader must not miss. */
              fill={p.impassable ? "#d03b3b" : "#7f97ad"}
              stroke={selected ? INK : "#0f141b"}
              strokeWidth={selected ? 2 : 1}
              opacity={p.impassable ? 1 : 0.9}
              style={{ cursor: onSelect ? "pointer" : "default" }}
              onClick={() => onSelect?.(p)}
            >
              <title>
                {`${p.label} (${p.corridor})\nAccessibility ${p.accessibility}/100\nRisk ${p.disruption_percent}%`}
              </title>
            </circle>
          );
        })}
      </svg>
    </div>
  );
};

/** Semicircular gauge for a single headline score. */
export const Gauge = ({ value, label, max = 100, invert = false }) => {
  const clamped = Math.max(0, Math.min(max, value ?? 0));
  const ratio = clamped / max;
  const radius = 70;
  const cx = 90;
  const cy = 84;
  const circumference = Math.PI * radius;
  const color = invert ? riskColor(clamped) : accessibilityColor(clamped);

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 180 100" className="w-full max-w-[200px]" role="img" aria-label={`${label}: ${clamped}`}>
        <path
          d={`M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
          fill="none"
          stroke={GRID}
          strokeWidth="12"
          strokeLinecap="round"
        />
        <path
          d={`M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${ratio * circumference} ${circumference}`}
          className="transition-all duration-700"
        />
        <text x={cx} y={cy - 12} textAnchor="middle" fill={INK} fontSize="28" fontWeight="600">
          {value === null || value === undefined ? "—" : Math.round(clamped)}
        </text>
        <text x={cx} y={cy + 8} textAnchor="middle" fill={INK_MUTED} fontSize="11">
          {label}
        </text>
      </svg>
    </div>
  );
};
