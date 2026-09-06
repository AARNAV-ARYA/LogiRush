/* eslint-disable react/prop-types */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { BarChart, DistributionBar, Gauge, RiskScatter } from "../components/charts";
import RouteMap from "../components/RouteMap";
import {
  AccessibilityBadge, Badge, Card, ErrorState, LiveDot, SectionHeading, Spinner,
} from "../components/ui";
import { IconAlert } from "../components/icons";
import { useApi } from "../hooks/useApi";
import { accessibilityColor, incidentLabel, riskTextClass } from "../lib/accessibility";
import { formatPercent, formatScore, timeAgo } from "../lib/format";

/*
  The overview screen.

  What it was: four large stat cards, then charts, then two lists, stacked down a page you
  scrolled. Everything had equal weight, which is another way of saying nothing had any, and
  the platform's own map appeared nowhere on its front page.

  What an incident wall actually does — and what the disaster-dashboard reference gets right
  — is put the exception first and the aggregates last. So: a banner that exists only when a
  corridor is actually closed, one dense readout strip instead of four cards competing to be
  the headline, the live network beside a feed of what people are reporting, and the analysis
  charts underneath for the half of the job that is not triage.
*/

const Metric = ({ label, value, suffix, hint, tone = "text-ink", dot }) => (
  <div className="px-4 py-3 flex-1 min-w-[8.5rem]">
    <div className="flex items-center gap-1.5">
      {dot}
      <span className="label-micro">{label}</span>
    </div>
    <p className={`mt-1 text-2xl leading-none font-semibold tabular-nums ${tone}`}>
      {value}
      {suffix && <span className="text-sm font-normal text-ink-muted ml-0.5">{suffix}</span>}
    </p>
    <p className="mt-1 text-[11px] text-ink-muted truncate">{hint}</p>
  </div>
);

const Dashboard = () => {
  const [selectedPoint, setSelectedPoint] = useState(null);

  // Poll on the spec's 30-second accessibility-refresh budget. Background refreshes don't
  // blank the screen (see useApi), so the page stays readable while it updates.
  const dashboard = useApi(() => api.getDashboard(), { pollMs: 30000 });
  const analytics = useApi(() => api.getAnalytics(), { pollMs: 30000 });
  const segmentsQuery = useApi(() => api.getSegments(), { pollMs: 60000 });
  const locationsQuery = useApi(() => api.getLocations());
  // Model metadata is static for the life of the process, so it is fetched once, not polled.
  const model = useApi(() => api.getModelInfo());

  const data = dashboard.data;
  const stats = analytics.data;
  const segments = useMemo(() => segmentsQuery.data?.segments || [], [segmentsQuery.data]);
  const locations = useMemo(() => locationsQuery.data?.locations || [], [locationsQuery.data]);

  const blocked = data?.impassable_count || 0;

  return (
    <div className="min-h-full flex flex-col">
      {/* ---------- exception banner: present only when something is actually closed ---------- */}
      {blocked > 0 && (
        <div
          className="flex items-center gap-2.5 px-4 py-2.5 shrink-0"
          style={{
            backgroundColor: "rgb(var(--status-critical-rgb) / 0.14)",
            borderBottom: "1px solid rgb(var(--status-critical-rgb) / 0.35)",
          }}
          role="status"
        >
          <IconAlert width="16" height="16" style={{ color: "var(--status-critical)" }} />
          <p className="text-sm text-ink">
            <span className="font-semibold tabular-nums">{blocked}</span> corridor
            {blocked === 1 ? " is" : "s are"} impassable and excluded from routing.
          </p>
          <Link to="/accessibility-map" className="ml-auto text-xs text-accent shrink-0 link-inline">
            Inspect →
          </Link>
        </div>
      )}

      {/* ---------- header ---------- */}
      <div className="flex items-center gap-3 px-4 pt-4 pb-3 flex-wrap shrink-0">
        <div>
          <h1 className="text-lg">Operations Overview</h1>
          <p className="text-[11px] text-ink-muted mt-0.5">
            Eight North Eastern states · synthetic risk data, model estimates
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {dashboard.lastUpdated && (
            <LiveDot
              tone="good"
              label={dashboard.lastUpdated.toLocaleTimeString("en-IN", {
                hour: "2-digit", minute: "2-digit",
              })}
            />
          )}
          <button
            onClick={() => { dashboard.refetch(); analytics.refetch(); }}
            className="btn-ghost !min-h-[2rem] !py-1 !text-xs"
            disabled={dashboard.isRefreshing}
          >
            {dashboard.isRefreshing ? <Spinner /> : null}
            Refresh
          </button>
        </div>
      </div>

      {dashboard.error && (
        <div className="px-4 pb-3">
          <ErrorState
            title="Could not reach the backend"
            message={dashboard.error}
            onRetry={dashboard.refetch}
          />
        </div>
      )}

      {/* ---------- readout strip ---------- */}
      <div className="px-4 shrink-0">
        <div className="panel flex flex-wrap divide-x divide-white/[0.07]">
          {data ? (
            <>
              <Metric
                label="Accessibility"
                value={formatScore(data.overall_accessibility)}
                suffix="/100"
                hint="Network average"
                dot={
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: accessibilityColor(data.overall_accessibility) }}
                  />
                }
              />
              <Metric
                label="Disruption risk"
                value={formatScore(data.average_disruption_probability_percent)}
                suffix="%"
                hint="Predicted, not observed"
                tone={riskTextClass(data.average_disruption_probability_percent)}
              />
              <Metric
                label="Impassable"
                value={blocked}
                hint={`of ${data.total_segments} corridors`}
                tone={blocked > 0 ? "tone-bad" : "tone-good"}
              />
              <Metric
                label="Active incidents"
                value={data.active_incident_count}
                hint="Last 7 days"
                tone="tone-serious"
              />
            </>
          ) : (
            [0, 1, 2, 3].map((i) => (
              <div key={i} className="px-4 py-3 flex-1 min-w-[8.5rem] space-y-2">
                <div className="h-2.5 w-16 skeleton" />
                <div className="h-6 w-20 skeleton" />
                <div className="h-2 w-24 skeleton" />
              </div>
            ))
          )}
        </div>
      </div>

      {/* ---------- live network + report feed ---------- */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_20rem] gap-4 p-4">
        <Card className="!p-0 overflow-hidden flex flex-col">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/10">
            <h2 className="text-sm font-semibold">Live network</h2>
            <span className="text-[11px] text-ink-muted">{segments.length} corridors</span>
            <Link to="/accessibility-map" className="ml-auto text-xs text-accent link-inline">
              Open map →
            </Link>
          </div>
          <div className="h-[clamp(260px,38vh,420px)]">
            {segmentsQuery.loading ? (
              <div className="h-full skeleton rounded-none" />
            ) : (
              <RouteMap
                bleed
                segments={segments}
                locations={locations}
                incidents={data?.recent_incidents || []}
                fitToHighlight={false}
                showLegend={false}
              />
            )}
          </div>
        </Card>

        {/* The feed is the thing an operator watches, so it is a rail, not a card at the
            bottom of a scroll. Its own scroll keeps the map fixed beside it. */}
        <Card className="!p-0 overflow-hidden flex flex-col max-h-[clamp(320px,46vh,520px)]">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/10 shrink-0">
            <h2 className="text-sm font-semibold">Field reports</h2>
            <Link to="/incidents" className="ml-auto text-xs text-accent link-inline">Review →</Link>
          </div>
          <div className="overflow-y-auto divide-y divide-white/[0.06] flex-1 min-h-0">
            {data?.recent_incidents?.length ? (
              data.recent_incidents.map((incident) => (
                <div key={incident.id} className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-1.5 h-1.5 rounded-full shrink-0"
                      style={{
                        backgroundColor:
                          incident.severity >= 4
                            ? "var(--status-critical)"
                            : incident.severity >= 3
                            ? "var(--status-warning)"
                            : "var(--ink-muted)",
                      }}
                    />
                    <span className="text-xs text-ink font-medium">
                      {incidentLabel(incident.type)}
                    </span>
                    <span className="text-[10px] text-ink-muted tabular-nums">
                      S{incident.severity}
                    </span>
                    <span className="ml-auto text-[10px] text-ink-muted shrink-0">
                      {timeAgo(incident.reported_at)}
                    </span>
                  </div>
                  <p className="text-[11px] text-ink-secondary mt-1 line-clamp-2 pl-3.5">
                    {incident.description || "No description"}
                  </p>
                  <div className="pl-3.5 mt-1">
                    <Badge
                      icon={false}
                      tone={
                        incident.verification_status === "verified" ? "success"
                        : incident.verification_status === "rejected" ? "danger"
                        : "neutral"
                      }
                    >
                      {incident.verification_status}
                    </Badge>
                  </div>
                </div>
              ))
            ) : (
              <p className="px-4 py-8 text-xs text-ink-muted text-center">
                No reports in the last 7 days.
              </p>
            )}
          </div>
        </Card>
      </div>

      {/* ---------- analysis ---------- */}
      {data && (
        <div className="px-4 pb-4 space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card className="lg:col-span-2">
              <SectionHeading hint="Bottom-left needs attention">
                Risk vs Accessibility
              </SectionHeading>
              {stats ? (
                <>
                  <RiskScatter
                    points={stats.risk_scatter}
                    onSelect={setSelectedPoint}
                    selectedId={selectedPoint?.id}
                  />
                  {selectedPoint && (
                    <div className="mt-3 p-3 rounded-lg bg-surface-sunken border border-white/10">
                      <p className="text-sm text-ink">{selectedPoint.label}</p>
                      <p className="text-xs text-ink-muted mt-0.5">
                        {selectedPoint.corridor} · accessibility {selectedPoint.accessibility}/100 ·
                        risk {formatPercent(selectedPoint.disruption_percent)}
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <div className="h-[300px] skeleton rounded-lg" />
              )}
            </Card>

            <Card>
              <SectionHeading hint="Network average">Accessibility</SectionHeading>
              <Gauge value={data.overall_accessibility} label="of 100" />
              <div className="mt-5">
                <p className="label-micro mb-3">Corridor distribution</p>
                {stats ? (
                  <DistributionBar distribution={stats.accessibility_distribution} />
                ) : (
                  <div className="h-3 skeleton rounded-full" />
                )}
              </div>

              {/* Model provenance sits with the number it produced, not in a doc nobody opens. */}
              {model.data && (
                <div className="mt-6 pt-5 border-t border-white/10">
                  <p className="label-micro mb-2">Prediction model</p>
                  <div className="flex items-center gap-2 flex-wrap mb-3">
                    <Badge tone="info">{model.data.model_type.replace(/_/g, " ")}</Badge>
                    <Badge tone="warning">{model.data.training.data} training data</Badge>
                  </div>
                  <div className="space-y-1.5">
                    {model.data.feature_importances.slice(0, 4).map((feature) => (
                      <div key={feature.feature} className="flex items-center gap-2">
                        <span className="text-xs text-ink-secondary flex-1 truncate">
                          {feature.feature.replace(/_/g, " ")}
                        </span>
                        <div className="w-16 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                          <div
                            className="h-full bg-accent/60 rounded-full"
                            style={{
                              width: `${(feature.importance / model.data.feature_importances[0].importance) * 100}%`,
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <p className="text-[11px] text-ink-muted mt-3 leading-relaxed">
                    Used only to predict disruption. Never for accessibility scoring, route
                    selection or incident verification.
                  </p>
                </div>
              )}
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <SectionHeading hint="Lowest average accessibility first">
                State Comparison
              </SectionHeading>
              {stats ? (
                /* No colorFor by design: bar length already encodes the score. Colouring it
                   by that same value is one channel repeating another. */
                <BarChart
                  ariaLabel="Average accessibility by state"
                  data={stats.state_breakdown.map((s) => ({
                    label: s.state,
                    value: s.average_accessibility,
                    sublabel: `${s.segment_count} corridor(s)${
                      s.impassable_count ? ` · ${s.impassable_count} impassable` : ""
                    }`,
                  }))}
                />
              ) : (
                <div className="space-y-3">
                  {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-8 skeleton rounded" />)}
                </div>
              )}
            </Card>

            <Card>
              <SectionHeading
                action={<Link to="/accessibility-map" className="text-sm text-accent">View map →</Link>}
              >
                High-Risk Corridors
              </SectionHeading>
              <div className="divide-y divide-white/[0.07]">
                {data.high_risk_corridors?.map((corridor) => (
                  <div key={corridor.id} className="flex items-center justify-between gap-3 py-2.5 first:pt-0">
                    <div className="min-w-0">
                      <p className="text-sm text-ink truncate">
                        {corridor.source_name} → {corridor.destination_name}
                      </p>
                      <p className="text-xs text-ink-muted truncate">
                        {corridor.highway_corridor} · {corridor.road_status}
                      </p>
                    </div>
                    <AccessibilityBadge
                      score={corridor.accessibility_score}
                      impassable={corridor.impassable}
                    />
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;
