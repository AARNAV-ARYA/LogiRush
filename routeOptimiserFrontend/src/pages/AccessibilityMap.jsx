/* eslint-disable react/prop-types */
import { useMemo, useState } from "react";
import { api } from "../api/client";
import RouteMap from "../components/RouteMap";
import { AccessibilityBadge, Badge, ErrorState } from "../components/ui";
import { IconChevron, IconLayers } from "../components/icons";
import { useApi } from "../hooks/useApi";
import { ACCESSIBILITY_BANDS, riskTextClass } from "../lib/accessibility";
import { formatKm, formatPercent } from "../lib/format";

/*
  The network screen.

  It used to be a page: heading, a filter card, a 560 px map in a box, then a table you
  scrolled to. Everything competed for the same vertical inch and the map — the only thing
  on the screen that shows you *where* trouble is — got the smallest share of it.

  This is the arrangement Windy and Zoom Earth converged on, for good reason: the map is the
  canvas and everything else floats over it on glass. Nothing is below the fold because
  there is no fold. The panel that holds filters, the corridor list and the drill-down is
  one surface in three states, so selecting a corridor never costs you the map.
*/

const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "problem", label: "Problem" },
];

/* A continuous ramp reads as a scale; a stack of swatches reads as a list of categories.
   Accessibility is a magnitude, so it gets the bar. */
const RampLegend = () => (
  <div>
    <div className="flex items-center justify-between mb-1">
      <span className="label-micro">Accessibility</span>
      <span className="text-[10px] text-ink-muted tabular-nums">100 → 0</span>
    </div>
    <div
      className="h-2 rounded-full"
      style={{
        background:
          "linear-gradient(90deg, var(--imp-1) 0%, var(--imp-2) 25%, var(--imp-3) 50%, var(--imp-4) 75%, var(--imp-5) 100%)",
      }}
    />
    <div className="flex justify-between mt-1 text-[10px] text-ink-muted">
      <span>Clear</span>
      <span>Impeded</span>
    </div>
    <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2.5 pt-2.5 border-t border-white/10">
      <span className="flex items-center gap-1.5 text-[11px] text-ink-secondary">
        <span
          className="inline-block w-2 h-2 rounded-full"
          style={{ backgroundColor: "var(--status-critical)" }}
        />
        Verified incident
      </span>
      <span className="flex items-center gap-1.5 text-[11px] text-ink-secondary">
        <span
          className="inline-block w-2 h-2 rounded-full border-2 border-dashed"
          style={{ borderColor: "var(--status-warning)" }}
        />
        Unverified
      </span>
      <span className="flex items-center gap-1.5 text-[11px] text-ink-secondary">
        <svg width="18" height="6" aria-hidden="true">
          <line
            x1="0" y1="3" x2="18" y2="3"
            stroke="var(--status-critical)" strokeWidth="2.5" strokeDasharray="1 6"
            strokeLinecap="round"
          />
        </svg>
        Closed
      </span>
    </div>
  </div>
);

const SegmentDetail = ({ segment, onBack }) => {
  const prediction = segment.prediction;
  return (
    <div className="flex flex-col min-h-0">
      <div className="flex items-start gap-2 px-3 pt-3 pb-2 border-b border-white/10 shrink-0">
        <button
          onClick={onBack}
          className="shrink-0 p-1.5 -ml-1 rounded-md text-ink-muted hover:text-ink hover:bg-white/[0.06]"
          aria-label="Back to corridor list"
        >
          <IconChevron width="16" height="16" style={{ transform: "rotate(180deg)" }} />
        </button>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold leading-snug">
            {segment.source_name} → {segment.destination_name}
          </h2>
          <p className="text-[11px] text-ink-muted mt-0.5 truncate">
            {segment.highway_corridor} · {formatKm(segment.distance_km)} ·{" "}
            {segment.travel_time_hours} h
          </p>
        </div>
      </div>

      <div className="overflow-y-auto px-3 py-3 space-y-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <AccessibilityBadge score={segment.accessibility_score} impassable={segment.impassable} />
          <Badge tone={segment.road_status === "Open" ? "success" : "warning"}>
            {segment.road_status}
          </Badge>
          {segment.active_incident_count > 0 && (
            <Badge tone="danger">{segment.active_incident_count} active</Badge>
          )}
        </div>

        <div>
          <p className="label-micro mb-1.5">Risk inputs</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-2">
            {Object.entries(segment.risk_inputs).map(([key, value]) => (
              <div key={key} className="flex items-baseline justify-between gap-2">
                <span className="text-[11px] text-ink-muted capitalize truncate">
                  {key.replace(/_/g, " ")}
                </span>
                <span className="text-xs text-ink tabular-nums shrink-0">{value}</span>
              </div>
            ))}
          </div>
        </div>

        {prediction && (
          <div>
            <p className="label-micro mb-1.5">Disruption ({prediction.model_type})</p>
            <div className="grid grid-cols-3 gap-2">
              {[
                ["Flood", prediction.flood_probability],
                ["Landslide", prediction.landslide_probability],
                ["Combined", prediction.combined_disruption_probability],
              ].map(([label, value], i) => (
                <div key={label} className="rounded-lg px-2 py-1.5" style={{ backgroundColor: "var(--surface-sunken)" }}>
                  <p className="text-[10px] text-ink-muted">{label}</p>
                  <p className={`text-sm tabular-nums ${i === 2 ? riskTextClass(value * 100) : "text-ink"}`}>
                    {formatPercent(value * 100)}
                  </p>
                </div>
              ))}
            </div>
            {prediction.top_drivers?.length ? (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {prediction.top_drivers.map((d) => (
                  <Badge key={d.feature} icon={false}>
                    {d.feature.replace(/_/g, " ")}: {d.value}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
};

const CorridorRow = ({ segment, active, onSelect }) => (
  <button
    onClick={() => onSelect(segment)}
    data-testid="corridor-row"
    className={`w-full text-left px-3 py-2.5 border-l-2 transition-colors ${
      active ? "bg-accent/10 border-l-accent" : "border-l-transparent hover:bg-white/[0.05]"
    }`}
  >
    <div className="flex items-center gap-2">
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{
          backgroundColor: segment.impassable
            ? "var(--status-critical)"
            : ACCESSIBILITY_BANDS.find(
                (b) => segment.accessibility_score >= b.min && segment.accessibility_score <= b.max
              )?.color || "var(--imp-3)",
        }}
      />
      <span className="text-xs text-ink truncate flex-1">
        {segment.source_name} → {segment.destination_name}
      </span>
      <span className="text-xs tabular-nums text-ink-secondary shrink-0">
        {Math.round(segment.accessibility_score)}
      </span>
    </div>
    <p className="text-[10px] text-ink-muted mt-0.5 truncate pl-3.5">
      {segment.highway_corridor} · {formatKm(segment.distance_km)}
      {segment.impassable ? " · closed" : ""}
    </p>
  </button>
);

const AccessibilityMap = () => {
  const segmentsQuery = useApi(() => api.getSegments(), { pollMs: 60000 });
  const locationsQuery = useApi(() => api.getLocations());
  const incidentsQuery = useApi(() => api.getIncidents(100).catch(() => ({ incidents: [] })));

  const [stateFilter, setStateFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  // The panel covers the map on a phone, so it opens only when asked for.
  const [sheetOpen, setSheetOpen] = useState(false);

  const segments = useMemo(() => segmentsQuery.data?.segments || [], [segmentsQuery.data]);
  const locations = useMemo(() => locationsQuery.data?.locations || [], [locationsQuery.data]);
  const incidents = useMemo(() => incidentsQuery.data?.incidents || [], [incidentsQuery.data]);

  const states = useMemo(
    () => ["all", ...Array.from(new Set(locations.map((l) => l.state))).sort()],
    [locations]
  );

  const visible = useMemo(
    () =>
      segments.filter((s) => {
        if (stateFilter !== "all" && s.source_state !== stateFilter) return false;
        if (categoryFilter !== "all" && s.accessibility_category !== categoryFilter) return false;
        if (statusFilter === "open" && (s.impassable || s.road_status !== "Open")) return false;
        if (statusFilter === "problem" && !s.impassable && s.road_status === "Open") return false;
        return true;
      }),
    [segments, stateFilter, categoryFilter, statusFilter]
  );

  const problems = visible.filter((s) => s.impassable || s.road_status !== "Open").length;

  const openDetail = (segment) => {
    setSelected(segment);
    setSheetOpen(true);
  };

  return (
    <div className="relative h-full w-full">
      {/* ---------- canvas ---------- */}
      <div className="absolute inset-0">
        {segmentsQuery.loading ? (
          <div className="h-full w-full skeleton rounded-none" />
        ) : (
          <RouteMap
            bleed
            segments={visible}
            locations={locations}
            incidents={incidents}
            onSelectSegment={openDetail}
            selectedSegmentId={selected?.id}
            fitToHighlight={false}
            showLegend={false}
          />
        )}
      </div>

      {segmentsQuery.error && (
        <div className="absolute top-3 left-3 right-3 md:left-auto md:w-[26rem] z-[600]">
          <ErrorState message={segmentsQuery.error} onRetry={segmentsQuery.refetch} />
        </div>
      )}

      {/* ---------- inspector: docked left on desktop, bottom sheet on a phone ---------- */}
      <div
        className={`absolute z-[500] flex flex-col
          md:left-3 md:top-3 md:bottom-3 md:w-[21rem] md:rounded-xl
          inset-x-0 bottom-0 rounded-t-2xl md:rounded-t-xl
          panel-glass overflow-hidden
          ${sheetOpen ? "top-[15%]" : ""} md:top-3`}
      >
        {/* header — always visible, doubles as the sheet handle on mobile */}
        <button
          className="md:cursor-default flex items-start gap-2 px-3 py-2.5 text-left shrink-0 w-full"
          onClick={() => setSheetOpen((v) => !v)}
          aria-expanded={sheetOpen}
          aria-label={sheetOpen ? "Collapse corridor panel" : "Expand corridor panel"}
        >
          <span
            className="md:hidden absolute left-1/2 -translate-x-1/2 top-1 w-9 h-1 rounded-full"
            style={{ backgroundColor: "var(--hairline-strong)" }}
          />
          <div className="min-w-0 flex-1">
            <h1 className="text-sm font-semibold leading-none mt-0.5">Corridor network</h1>
            <p className="text-[11px] text-ink-muted mt-1.5">
              <span className="tabular-nums text-ink-secondary">{visible.length}</span> shown
              {problems > 0 && (
                <>
                  {" · "}
                  <span className="tabular-nums" style={{ color: "var(--status-warning)" }}>
                    {problems} degraded
                  </span>
                </>
              )}
            </p>
          </div>
          <span className="md:hidden text-ink-muted shrink-0 mt-0.5">
            <IconChevron
              width="16" height="16"
              style={{ transform: sheetOpen ? "rotate(90deg)" : "rotate(-90deg)" }}
            />
          </span>
        </button>

        {/* On a phone the panel covers the map, so its body exists only when opened; a
            max-height clip instead left half a select control peeking under the fold. */}
        <div className={`${sheetOpen ? "flex" : "hidden"} md:flex flex-col min-h-0 flex-1`}>
        {selected ? (
          <SegmentDetail segment={selected} onBack={() => setSelected(null)} />
        ) : (
          <>
            {/* filters */}
            <div className="px-3 pb-3 space-y-2.5 border-b border-white/10 shrink-0">
              <div className="grid grid-cols-2 gap-2">
                <label>
                  <span className="field-label">State</span>
                  <select
                    className="field !mt-1 !py-1.5 !text-xs"
                    value={stateFilter}
                    onChange={(e) => setStateFilter(e.target.value)}
                  >
                    {states.map((s) => (
                      <option key={s} value={s}>{s === "all" ? "All states" : s}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="field-label">Category</span>
                  <select
                    className="field !mt-1 !py-1.5 !text-xs"
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                  >
                    <option value="all">All</option>
                    {ACCESSIBILITY_BANDS.map((b) => (
                      <option key={b.label} value={b.label}>{b.label}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="flex gap-1.5" role="group" aria-label="Filter by road status">
                {STATUS_OPTIONS.map((o) => (
                  <button
                    key={o.value}
                    className="chip flex-1"
                    aria-pressed={statusFilter === o.value}
                    onClick={() => setStatusFilter(o.value)}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            {/* corridor list */}
            <div className="overflow-y-auto flex-1 min-h-0 divide-y divide-white/[0.05]">
              {visible.map((s) => (
                <CorridorRow
                  key={s.id}
                  segment={s}
                  active={selected?.id === s.id}
                  onSelect={openDetail}
                />
              ))}
              {visible.length === 0 && !segmentsQuery.loading && (
                <p className="px-3 py-6 text-xs text-ink-muted text-center">
                  No corridors match these filters.
                </p>
              )}
            </div>

            <div className="px-3 py-2.5 border-t border-white/10 shrink-0">
              <RampLegend />
            </div>
          </>
        )}
        </div>
      </div>

      {/* ---------- provenance, kept on screen but out of the way ---------- */}
      <div className="hidden md:block absolute right-3 top-3 z-[450] panel-glass px-3 py-2 max-w-[15rem]">
        <p className="flex items-center gap-1.5 text-[11px] text-ink-secondary leading-snug">
          <IconLayers width="13" height="13" className="shrink-0" />
          Synthetic risk data · model estimates, not official forecasts
        </p>
      </div>
    </div>
  );
};

export default AccessibilityMap;
