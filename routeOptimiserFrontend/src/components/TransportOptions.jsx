// src/components/TransportOptions.jsx
//
// Multimodal option comparison for the shipment planner.
//
// The planner used to answer one question: "what is the best road route?" That hid the
// decision a despatcher actually makes, which is *what do I put this load on*. A 300 kg
// medical consignment and a 30 tonne rice consignment to the same town are different
// problems with different answers, and the price and the route both change with weight.
//
// So this component shows every mode side by side - including the ones that are ruled out,
// with the reason - because knowing that rail is unavailable because there is no railhead at
// Aizawl is operationally useful, not noise.

import { useState } from "react";
import { Badge, Card, SectionHeading } from "./ui";
import { SERIES_COLORS } from "../lib/accessibility";
import { formatHours, formatInr, formatKm } from "../lib/format";

const CATEGORY_TONE = {
  Road: "neutral",
  Rail: "info",
  Waterway: "info",
  Air: "warning",
  "Human / animal": "neutral",
};

const BLOCKER_LABEL = {
  infrastructure: "No infrastructure",
  access: "Road too damaged",
  data: "Data unavailable",
};

/** Cost per tonne makes very different consignment sizes comparable at a glance. */
const perTonne = (option) => option.cost_breakdown?.cost_per_tonne_inr;

export const TransportOptionCard = ({ option, selected, onSelect, isRecommended }) => {
  if (!option.feasible) {
    return (
      <div className="rounded-lg border border-white/10 bg-surface-sunken/40 p-3 opacity-70">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm text-ink-secondary truncate">{option.label}</p>
            <p className="text-xs text-ink-muted mt-1">{option.reason}</p>
          </div>
          <Badge tone="danger">{BLOCKER_LABEL[option.blocker] || "Unavailable"}</Badge>
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onSelect(option)}
      aria-pressed={selected}
      className={`w-full text-left rounded-lg border p-3 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        selected
          ? "border-accent bg-accent/[0.07]"
          : "border-white/10 bg-surface-sunken/40 hover:border-white/10"
      }`}
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-ink">{option.label}</span>
            <Badge tone={CATEGORY_TONE[option.category] || "neutral"}>{option.category}</Badge>
            {isRecommended && <Badge tone="success">Recommended</Badge>}
            {option.disproportionate_cost && <Badge tone="warning">Premium</Badge>}
          </div>
          <p className="text-xs text-ink-muted mt-1">
            {option.vehicles} × {option.capacity_kg.toLocaleString("en-IN")} kg unit
            {option.vehicles > 1 ? "s" : ""} · {formatKm(option.distance_km)}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-lg text-ink tabular-nums">{formatInr(option.cost_inr)}</p>
          <p className="text-xs text-ink-muted tabular-nums">{formatHours(option.eta_hours)}</p>
        </div>
      </div>

      <dl className="grid grid-cols-3 gap-2 mt-3 text-xs">
        <div>
          <dt className="text-ink-muted">Per tonne</dt>
          <dd className="text-ink-secondary tabular-nums">{formatInr(perTonne(option))}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">Peak risk</dt>
          <dd className="text-ink-secondary tabular-nums">{option.risk_percent}%</dd>
        </div>
        <div>
          <dt className="text-ink-muted">CO₂</dt>
          <dd className="text-ink-secondary tabular-nums">{option.co2_kg.toLocaleString("en-IN")} kg</dd>
        </div>
      </dl>

      {selected && (
        <ul className="mt-3 space-y-1 border-t border-white/10 pt-3">
          {option.why?.map((reason, i) => (
            <li key={i} className="text-xs text-ink-secondary flex gap-2">
              <span className="text-ink-muted shrink-0">·</span>
              <span>{reason}</span>
            </li>
          ))}
          <li className="text-xs text-ink-muted italic pt-1">{option.note}</li>
        </ul>
      )}
    </button>
  );
};

/**
 * Cost-versus-weight curve.
 *
 * Drawn by hand rather than with a charting library, matching the rest of the codebase and
 * keeping the bundle small. The steps matter more than the slope: they are where an extra
 * vehicle gets added, and they are exactly what a planner consolidating a load wants to see.
 */
const CostCurve = ({ curves, currentWeight }) => {
  if (!curves?.length) return null;
  const width = 520;
  const height = 170;
  const pad = { top: 12, right: 12, bottom: 26, left: 56 };

  const allPoints = curves.flatMap((c) => c.points);
  const maxWeight = Math.max(...allPoints.map((p) => p.weight_kg));
  // A single premium option (an airlift at ₹8 lakh) sets the ceiling and squashes every
  // road mode into an indistinguishable line along the axis — the chart then answers
  // "is a helicopter expensive?", which nobody is asking, instead of "where does my
  // cheapest option step?". The scale follows the realistic options and the outlier is
  // allowed to run off the top, which is the honest way to keep both on one axis.
  const roadCosts = curves
    .filter((c) => !c.premium)
    .flatMap((c) => c.points.map((p) => p.cost_inr));
  const maxCost = (roadCosts.length ? Math.max(...roadCosts) : Math.max(...allPoints.map((p) => p.cost_inr))) * 1.05;
  const x = (w) => pad.left + (w / maxWeight) * (width - pad.left - pad.right);
  // Clamp so an off-scale premium option stops at the top edge instead of drawing above it.
  const y = (c) =>
    Math.max(pad.top, height - pad.bottom - (Math.min(c, maxCost) / maxCost) * (height - pad.top - pad.bottom));
  // Fixed categorical order from the shared table, never a local copy and never cycled.
  const colors = SERIES_COLORS;

  return (
    <figure>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-auto"
        role="img"
        aria-label="Cost against consignment weight for the top transport options"
      >
        <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} stroke="#374151" />
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} stroke="#374151" />

        {/* where the consignment currently sits */}
        <line
          x1={x(currentWeight)} y1={pad.top} x2={x(currentWeight)} y2={height - pad.bottom}
          stroke="#64748b" strokeDasharray="3 3"
        />
        <text x={x(currentWeight) + 4} y={pad.top + 9} fontSize="9" fill="#94a3b8">
          this load
        </text>

        {curves.map((curve, ci) => (
          <g key={curve.mode}>
            <polyline
              fill="none"
              stroke={colors[ci % colors.length]}
              strokeWidth="1.8"
              points={curve.points.map((p) => `${x(p.weight_kg)},${y(p.cost_inr)}`).join(" ")}
            />
            {curve.points.map((p, pi) => (
              <circle key={pi} cx={x(p.weight_kg)} cy={y(p.cost_inr)} r="2.2" fill={colors[ci % colors.length]}>
                <title>
                  {curve.label}: {p.weight_kg.toLocaleString("en-IN")} kg → {formatInr(p.cost_inr)} ({p.vehicles} unit
                  {p.vehicles > 1 ? "s" : ""})
                </title>
              </circle>
            ))}
          </g>
        ))}

        <text x={pad.left - 6} y={y(maxCost) + 3} fontSize="9" fill="#6b7280" textAnchor="end">
          {formatInr(maxCost)}
        </text>
        <text x={pad.left - 6} y={height - pad.bottom + 3} fontSize="9" fill="#6b7280" textAnchor="end">
          ₹0
        </text>
        <text x={width - pad.right} y={height - pad.bottom + 16} fontSize="9" fill="#6b7280" textAnchor="end">
          {maxWeight.toLocaleString("en-IN")} kg
        </text>
      </svg>
      <figcaption className="sr-only">
        Each line is one transport mode. Vertical steps are where an additional vehicle is
        required.
      </figcaption>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
        {curves.map((curve, ci) => (
          <li key={curve.mode} className="flex items-center gap-1.5 text-xs text-ink-secondary">
            <span
              className="inline-block w-3 h-0.5 rounded"
              style={{ backgroundColor: colors[ci % colors.length] }}
              aria-hidden="true"
            />
            {curve.label}
            {curve.premium ? <span className="text-ink-muted">(off scale)</span> : null}
          </li>
        ))}
      </ul>
    </figure>
  );
};

const TransportOptions = ({ result, selectedMode, onSelectMode }) => {
  const [showRuledOut, setShowRuledOut] = useState(false);
  const options = result?.transport_options || [];
  if (!options.length) return null;

  const feasible = options.filter((o) => o.feasible);
  const ruledOut = options.filter((o) => !o.feasible);
  const sensitivity = result.weight_sensitivity || {};
  const weight = result.weight_kg;

  return (
    <div className="space-y-4">
      <Card>
        <SectionHeading
          hint={`Priced for ${weight?.toLocaleString("en-IN")} kg · ${feasible.length} of ${options.length} modes usable`}
        >
          Transport options
        </SectionHeading>

        <div className="space-y-2">
          {feasible.map((option) => (
            <TransportOptionCard
              key={option.mode}
              option={option}
              selected={selectedMode === option.mode}
              isRecommended={option.mode === result.recommended_transport}
              onSelect={(o) => onSelectMode(o.mode === selectedMode ? null : o.mode)}
            />
          ))}
        </div>

        {ruledOut.length > 0 && (
          <div className="mt-3">
            <button
              type="button"
              onClick={() => setShowRuledOut((v) => !v)}
              aria-expanded={showRuledOut}
              className="text-sm text-accent hover:text-accent"
            >
              {showRuledOut ? "Hide" : "Show"} {ruledOut.length} unavailable mode
              {ruledOut.length > 1 ? "s" : ""}
            </button>
            {showRuledOut && (
              <div className="space-y-2 mt-2">
                {ruledOut.map((option) => (
                  <TransportOptionCard key={option.mode} option={option} onSelect={() => {}} />
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {sensitivity.summary && (
        <Card>
          <SectionHeading hint="How the price moves as the consignment grows">
            Weight sensitivity
          </SectionHeading>
          <p className="text-sm text-ink-secondary">{sensitivity.summary}</p>
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3 mb-4">
            <div>
              <dt className="text-xs text-ink-muted">Cost now</dt>
              <dd className="text-ink tabular-nums">{formatInr(sensitivity.cost_now_inr)}</dd>
            </div>
            <div>
              <dt className="text-xs text-ink-muted">Spare capacity</dt>
              <dd className="text-ink tabular-nums">
                {sensitivity.headroom_kg?.toLocaleString("en-IN")} kg
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-muted">Next vehicle at</dt>
              <dd className="text-ink tabular-nums">
                {sensitivity.next_vehicle_at_kg?.toLocaleString("en-IN")} kg
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-muted">Step increase</dt>
              <dd className="text-[#fab219] tabular-nums">
                +{formatInr(sensitivity.step_increase_inr)}
              </dd>
            </div>
          </dl>
              <CostCurve
            curves={(sensitivity.cost_curves || []).map((c) => ({
              ...c,
              premium: feasible.find((o) => o.mode === c.mode)?.disproportionate_cost,
            }))}
            currentWeight={weight}
          />
        </Card>
      )}
    </div>
  );
};

export default TransportOptions;
