/* eslint-disable react/prop-types */
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import RouteTimeline from "../components/RouteTimeline";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  SectionHeading,
  Spinner,
  Toggle,
} from "../components/ui";
import { useApi } from "../hooks/useApi";
import { riskTextClass } from "../lib/accessibility";
import { formatHours, formatInr, formatKm, formatPercent, timeAgo, titleCase } from "../lib/format";

const STATUS_FLOW = ["planned", "dispatched", "in_transit", "delivered"];
const STATUS_TONES = {
  planned: "neutral",
  dispatched: "info",
  in_transit: "warning",
  delivered: "success",
  cancelled: "danger",
};

/** Shows what changed between the snapshot taken at dispatch and current conditions. */
const ReplanResult = ({ result, onDismiss }) => {
  if (!result) return null;
  const tone = !result.routable ? "danger" : result.route_changed ? "warning" : "success";
  const border =
    tone === "danger"
      ? "state-error-light"
      : tone === "warning"
      ? "state-warning"
      : "state-success";

  return (
    <div className={`mt-3 rounded-lg border px-4 py-3 ${border}`}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-ink">{result.summary}</p>
        <button onClick={onDismiss} className="text-ink-muted hover:text-ink-secondary" aria-label="Dismiss">
          ✕
        </button>
      </div>

      {result.route_changed && result.current_route && (
        <div className="mt-3 text-sm">
          <p className="text-ink-muted text-xs uppercase tracking-wider mb-1">New route</p>
          <p className="text-ink">{result.current_route.path_names.join(" → ")}</p>
        </div>
      )}

      {Object.keys(result.differences || {}).length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
          {Object.entries(result.differences).map(([field, diff]) => {
            // For ETA and risk, up is bad. For accessibility, up is good.
            const higherIsBetter = field.includes("accessibility");
            const improved = higherIsBetter ? diff.delta > 0 : diff.delta < 0;
            return (
              <div key={field}>
                <p className="text-[11px] uppercase tracking-wider text-ink-muted">
                  {field.replace(/_/g, " ")}
                </p>
                <p className="text-sm text-ink-secondary tabular-nums">
                  {diff.before} →{" "}
                  <span className={improved ? "tone-good" : "tone-serious"}>
                    {diff.after}
                  </span>
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

/* Lifecycle as a track rather than a word. A status badge tells you the state; the track
   tells you the state *and* what is left, which is the question someone scanning a list of
   forty convoys is actually asking. Cancelled has no position on the track, so it keeps the
   badge and drops the track entirely rather than pretending to sit somewhere on it. */
const StatusTrack = ({ status }) => {
  const index = STATUS_FLOW.indexOf(status);
  if (index < 0) return null;
  return (
    <ol className="flex items-center gap-1 mt-3" aria-label={`Status: ${titleCase(status)}`}>
      {STATUS_FLOW.map((step, i) => {
        const done = i <= index;
        return (
          <li key={step} className="flex items-center gap-1 flex-1 last:flex-none">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: done ? "var(--accent)" : "var(--hairline-strong)" }}
              title={titleCase(step)}
            />
            <span className={`text-[10px] whitespace-nowrap ${done ? "text-ink-secondary" : "text-ink-muted"}`}>
              {titleCase(step)}
            </span>
            {i < STATUS_FLOW.length - 1 && (
              <span
                className="h-px flex-1 min-w-[0.75rem]"
                style={{ backgroundColor: i < index ? "var(--accent-dim)" : "var(--hairline)" }}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
};

const ShipmentRow = ({ shipment, onChanged }) => {
  const [busy, setBusy] = useState(false);
  const [replan, setReplan] = useState(null);
  const [error, setError] = useState(null);
  const [showJourney, setShowJourney] = useState(false);
  const route = shipment.planned_route;

  const nextStatus = STATUS_FLOW[STATUS_FLOW.indexOf(shipment.status) + 1];

  const advance = async () => {
    if (!nextStatus) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateShipmentStatus(shipment.id, nextStatus);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const doReplan = async () => {
    setBusy(true);
    setError(null);
    try {
      setReplan(await api.replanShipment(shipment.id, false));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="py-4 first:pt-0 last:pb-0" data-testid="shipment-row">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-ink-muted text-xs">#{shipment.id}</span>
            <Badge tone={STATUS_TONES[shipment.status]}>{titleCase(shipment.status)}</Badge>
            <Badge>{titleCase(shipment.cargo_type)}</Badge>
            <Badge tone={shipment.urgency === "critical" ? "danger" : "neutral"}>
              {shipment.urgency} urgency
            </Badge>
          </div>
          <p className="text-ink mt-2 font-medium">
            {route ? route.path_names[0] : shipment.origin_id}
            <span className="text-ink-muted mx-1.5">→</span>
            {route ? route.path_names[route.path_names.length - 1] : shipment.destination_id}
          </p>
          <p className="text-xs text-ink-muted mt-1">
            Created {timeAgo(shipment.created_at)}
            {shipment.weight_kg ? ` · ${shipment.weight_kg.toLocaleString("en-IN")} kg` : ""}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={doReplan} disabled={busy} className="btn-ghost">
            {busy ? <Spinner /> : null}
            Re-check route
          </button>
          {nextStatus && (
            <button onClick={advance} disabled={busy} className="btn-primary">
              Mark {titleCase(nextStatus)}
            </button>
          )}
        </div>
      </div>

      <StatusTrack status={shipment.status} />

      {route && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-ink-muted">ETA</p>
            <p className="text-ink-secondary tabular-nums">{formatHours(route.eta_hours)}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wider text-ink-muted">Distance</p>
            <p className="text-ink-secondary tabular-nums">{formatKm(route.total_distance_km)}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wider text-ink-muted">Cost</p>
            <p className="text-ink-secondary tabular-nums">{formatInr(route.estimated_cost_inr)}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wider text-ink-muted">Peak risk</p>
            <p className={`tabular-nums ${riskTextClass(route.peak_segment_risk_percent)}`}>
              {formatPercent(route.peak_segment_risk_percent, 0)}
            </p>
          </div>
        </div>
      )}

      {route?.segments?.length > 0 && (
        <div className="mt-3">
          <button
            onClick={() => setShowJourney((v) => !v)}
            className="text-xs text-accent link-inline"
            aria-expanded={showJourney}
          >
            {showJourney ? "Hide" : "Show"} journey · {route.path_names.length - 1} leg
            {route.path_names.length === 2 ? "" : "s"}
          </button>
          {showJourney && (
            <div className="mt-3 pt-3 border-t border-white/10">
              <RouteTimeline route={route} dense />
            </div>
          )}
        </div>
      )}

      {error && <p className="text-sm tone-bad mt-2">{error}</p>}
      <ReplanResult result={replan} onDismiss={() => setReplan(null)} />
    </div>
  );
};

const Shipments = () => {
  const [statusFilter, setStatusFilter] = useState("all");
  const query = useApi(() => api.getShipments(statusFilter === "all" ? undefined : statusFilter), {
    deps: [statusFilter],
  });

  const shipments = query.data?.shipments || [];

  return (
    <div className="max-w-6xl mx-auto px-4 py-5 sm:py-6">
      <header className="flex items-start justify-between gap-4 flex-wrap mb-5">
        <div>
          <h1>Shipments</h1>
          <p className="text-ink-secondary mt-1 text-sm">
            Planned consignments and their route snapshots
          </p>
        </div>
        <Link to="/shipment-planner" className="btn-primary">
          Plan new shipment
        </Link>
      </header>

      <div className="mb-4">
        <Toggle
          ariaLabel="Filter shipments by status"
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: "all", label: "All" },
            ...STATUS_FLOW.map((s) => ({ value: s, label: titleCase(s) })),
          ]}
        />
      </div>

      {query.error && <ErrorState message={query.error} onRetry={query.refetch} />}

      {query.loading ? (
        <Card>
          <div className="space-y-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-20 skeleton rounded-lg" />
            ))}
          </div>
        </Card>
      ) : shipments.length ? (
        <Card>
          <SectionHeading hint="Re-check compares the stored plan against live conditions">
            {shipments.length} shipment{shipments.length === 1 ? "" : "s"}
          </SectionHeading>
          <div className="divide-y divide-white/[0.07]">
            {shipments.map((shipment) => (
              <ShipmentRow key={shipment.id} shipment={shipment} onChanged={query.refetch} />
            ))}
          </div>
        </Card>
      ) : (
        <Card>
          <EmptyState
            title="No shipments yet"
            description="Plan a route and save it as a shipment to track it here."
            action={
              <Link to="/shipment-planner" className="btn-primary">
                Plan a shipment
              </Link>
            }
          />
        </Card>
      )}
    </div>
  );
};

export default Shipments;
