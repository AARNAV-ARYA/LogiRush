/* eslint-disable react/prop-types */
import { useEffect, useMemo, useState } from "react";
import TransportOptions from "../components/TransportOptions";
import { planOffline } from "../utils/offlinePlanner";
import { primeOfflineCache } from "../utils/offlineStore";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import RouteMap from "../components/RouteMap";
import RouteTimeline from "../components/RouteTimeline";
import PlaceSearch from "../components/PlaceSearch";
import NearbyFacilities from "../components/NearbyFacilities";
import {
  AccessibilityBadge,
  Badge,
  Card,
  DemoDataNotice,
  ErrorState,
  SectionHeading,
  Spinner,
} from "../components/ui";
import { useApi } from "../hooks/useApi";
import { riskTextClass } from "../lib/accessibility";
import { formatHours, formatInr, formatKm, formatPercent } from "../lib/format";

const URGENCIES = ["low", "normal", "high", "critical"];

/** Visualises how the cargo profile weights the five objectives. */
const WeightBars = ({ weights }) => {
  const max = Math.max(...Object.values(weights));
  return (
    <div className="space-y-1.5">
      {Object.entries(weights)
        .sort((a, b) => b[1] - a[1])
        .map(([name, weight]) => (
          <div key={name} className="flex items-center gap-2">
            <span className="text-xs text-ink-secondary w-24 capitalize shrink-0">{name}</span>
            <div className="flex-1 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
              <div
                className="h-full bg-accent rounded-full transition-all duration-500"
                style={{ width: `${(weight / max) * 100}%` }}
              />
            </div>
            <span className="text-xs text-ink-muted tabular-nums w-10 text-right">
              {(weight * 100).toFixed(0)}%
            </span>
          </div>
        ))}
    </div>
  );
};

const RouteCard = ({ route, primary, onHover, isActive }) => (
  <div
    onMouseEnter={() => onHover?.(route)}
    className={`rounded-xl border p-4 sm:p-5 transition-colors ${
      primary
        ? "border-accent/50 bg-accent/[0.07]"
        : isActive
        ? "border-white/10 bg-surface/60"
        : "border-white/10 bg-surface/30"
    }`}
    data-testid={primary ? "recommended-route" : "alternative-route"}
  >
    <div className="flex items-start justify-between gap-3 flex-wrap">
      <div className="min-w-0">
        <Badge tone={primary ? "info" : "neutral"}>
          {primary ? "Recommended" : `Alternative ${route.rank - 1}`}
        </Badge>
        <p className="text-ink font-medium mt-2 leading-snug" data-testid="route-path">
          {route.path_names[0]}
          <span className="text-ink-muted mx-1.5">→</span>
          {route.path_names[route.path_names.length - 1]}
        </p>
        {/* Where it goes, not just where it ends. Two routes between the same pair of towns
            are the same headline and completely different journeys — the whole point of a
            risk-aware alternative is the detour it takes, and "3 legs" does not say that. */}
        <p
          className="text-[11px] text-ink-muted mt-1"
          data-testid="route-waypoints"
          data-path={route.path_names.join(" > ")}
        >
          {route.path_names.length > 2 ? (
            <>via {route.path_names.slice(1, -1).join(", ")}</>
          ) : (
            <>direct</>
          )}
          <span className="tabular-nums">
            {" · "}
            {route.path_names.length - 1} leg{route.path_names.length === 2 ? "" : "s"}
          </span>
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-2xl font-bold text-accent tabular-nums">
          {formatHours(route.eta_hours)}
        </p>
        <p className="text-xs text-ink-muted">estimated transit</p>
      </div>
    </div>

    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
      <div>
        <p className="text-[11px] uppercase tracking-wider text-ink-muted">Distance</p>
        <p className="text-ink tabular-nums">{formatKm(route.total_distance_km)}</p>
      </div>
      <div>
        <p className="text-[11px] uppercase tracking-wider text-ink-muted">Est. cost</p>
        <p className="text-ink tabular-nums">{formatInr(route.estimated_cost_inr)}</p>
      </div>
      <div>
        <p className="text-[11px] uppercase tracking-wider text-ink-muted">Worst link</p>
        <AccessibilityBadge score={route.worst_segment_accessibility} showLabel={false} />
      </div>
      <div>
        <p className="text-[11px] uppercase tracking-wider text-ink-muted">Peak risk</p>
        <p className={`tabular-nums ${riskTextClass(route.peak_segment_risk_percent)}`}>
          {formatPercent(route.peak_segment_risk_percent, 0)}
        </p>
      </div>
    </div>

    <details className="mt-4 group">
      <summary className="cursor-pointer text-sm text-accent hover:text-accent select-none">
        Why this route?
      </summary>
      <ul className="mt-2.5 space-y-1 text-sm text-ink-secondary list-disc list-inside">
        {route.explanation.reasons.map((reason, index) => (
          <li key={index}>{reason}</li>
        ))}
      </ul>
      <p className="mt-3 text-xs pl-3 border-l-2" style={{ color: 'rgba(250, 178, 25, 0.8)', borderColor: 'rgba(250, 178, 25, 0.35)' }}>
        {route.explanation.caveat}
      </p>

      <div className="mt-4 pt-4 border-t border-white/10">
        <p className="label-micro mb-3">Journey</p>
        <RouteTimeline route={route} dense />
      </div>
    </details>
  </div>
);

const ShipmentPlanner = () => {
  const navigate = useNavigate();
  const locationsQuery = useApi(() => api.getLocations());
  const cargoQuery = useApi(() => api.getCargoTypes());
  const segmentsQuery = useApi(() => api.getSegments());

  const [form, setForm] = useState({
    origin: "",
    destination: "",
    cargo_type: "general",
    urgency: "normal",
    weight_kg: "1000",
  });
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [planning, setPlanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(null);
  const [hovered, setHovered] = useState(null);
  // The place the trader chose, which may be an address rather than a corridor node. The
  // form keeps the node id the router needs; these keep what was actually asked for, so the
  // interface can show the difference and list handover points around the real location.
  const [originPlace, setOriginPlace] = useState(null);
  const [destinationPlace, setDestinationPlace] = useState(null);
  // Which transport mode the operator is inspecting. Each mode may have been routed over a
  // different sub-network, so selecting one changes the route drawn on the map.
  const [selectedMode, setSelectedMode] = useState(null);

  const locations = useMemo(
    () => (locationsQuery.data?.locations || []).slice().sort((a, b) => a.name.localeCompare(b.name)),
    [locationsQuery.data]
  );
  const cargoTypes = cargoQuery.data?.cargo_types || [];

  useEffect(() => {
    if (locations.length && !form.origin) {
      const toPlace = (l) => ({
        id: l.id, name: l.name, label: `${l.name}, ${l.state}`,
        context: `${l.district} district · ${l.state}`,
        latitude: l.latitude, longitude: l.longitude,
        routable: true, location_id: l.id, planFrom: null, offsetKm: 0,
      });
      setForm((f) => ({ ...f, origin: locations[0].id, destination: locations[1]?.id || "" }));
      setOriginPlace(toPlace(locations[0]));
      if (locations[1]) setDestinationPlace(toPlace(locations[1]));
    }
  }, [locations, form.origin]);

  // A chosen place resolves to the node the router will actually plan from: itself when it is
  // on the network, otherwise the nearest one.
  useEffect(() => {
    const id = originPlace?.location_id || originPlace?.planFrom?.location_id;
    if (id) setForm((f) => ({ ...f, origin: id }));
  }, [originPlace]);

  useEffect(() => {
    const id = destinationPlace?.location_id || destinationPlace?.planFrom?.location_id;
    if (id) setForm((f) => ({ ...f, destination: id }));
  }, [destinationPlace]);

  const submit = async (event) => {
    event.preventDefault();
    setPlanning(true);
    setError(null);
    setResult(null);
    setSaved(null);
    const payload = {
      origin: form.origin,
      destination: form.destination,
      cargo_type: form.cargo_type,
      urgency: form.urgency,
      weight_kg: Number(form.weight_kg) || 1000,
    };
    try {
      const plan = await api.planRoute({
        origin: form.origin,
        destination: form.destination,
        cargo_type: form.cargo_type,
        urgency: form.urgency,
        // Weight is not optional any more: it sizes the fleet and prices every option, so an
        // empty box would silently fall back to a default and mislead the operator.
        weight_kg: Number(form.weight_kg) || 1000,
      });
      setResult(plan);
      setHovered(plan.recommended_route);
      setSelectedMode(plan.recommended_transport || null);
      // Opportunistically refresh the offline copy whenever we are demonstrably online.
      primeOfflineCache(api);
    } catch (e) {
      // A failed request in NER usually means no signal, not a broken server. Fall back to
      // the network snapshot on the device rather than showing an error to someone who may
      // be standing at a blocked corridor with no way to get a second opinion.
      try {
        const offlinePlan = await planOffline(payload);
        setResult(offlinePlan);
        setHovered(offlinePlan.recommended_route);
        setSelectedMode(offlinePlan.recommended_transport || null);
        setError(null);
      } catch (offlineError) {
        setError(`${e.message}. ${offlineError.message}`);
      }
    } finally {
      setPlanning(false);
    }
  };

  const saveShipment = async () => {
    setSaving(true);
    setError(null);
    try {
      const created = await api.createShipment({
        origin_id: form.origin,
        destination_id: form.destination,
        cargo_type: form.cargo_type,
        urgency: form.urgency,
        weight_kg: Number(form.weight_kg) || 1000,
      });
      setSaved(created.shipment);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const selectedCargo = cargoTypes.find((c) => c.id === form.cargo_type);
  const selectedOption = (result?.transport_options || []).find(
    (o) => o.mode === selectedMode && o.feasible
  );
  // A selected mode wins over hover: the operator asked to see that vehicle class's route,
  // which for a heavy truck can be a completely different corridor from the pickup's.
  const activeRoute = selectedOption?.route || hovered || result?.recommended_route;
  const highlightIds = activeRoute?.segments?.map((s) => s.segment_id) || null;

  return (
    <div className="max-w-[1600px] mx-auto px-4 py-6 sm:py-8">
      <header className="mb-5">
        <h1>Shipment Planner</h1>
        <p className="text-ink-secondary mt-1 text-sm">
          Risk-aware routing across the North Eastern Region
        </p>
      </header>

      <div className="mb-4">
        <DemoDataNotice compact />
      </div>

      <Card as="form" onSubmit={submit} className="mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          <PlaceSearch
            id="origin"
            label="Origin"
            value={originPlace}
            onChange={setOriginPlace}
            placeholder="Where is it now?"
          />

          <PlaceSearch
            id="destination"
            label="Destination"
            value={destinationPlace}
            onChange={setDestinationPlace}
            placeholder="Where must it go?"
          />

          <label>
            <span className="field-label">Cargo type</span>
            <select
              id="cargo"
              className="field"
              value={form.cargo_type}
              onChange={(e) => setForm({ ...form, cargo_type: e.target.value })}
            >
              {cargoTypes.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span className="field-label">Urgency</span>
            <select
              id="urgency"
              className="field"
              value={form.urgency}
              onChange={(e) => setForm({ ...form, urgency: e.target.value })}
            >
              {URGENCIES.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span className="field-label">Weight (kg)</span>
            <input
              id="weight"
              type="number"
              min="1"
              max="500000"
              required
              className="field"
              value={form.weight_kg}
              onChange={(e) => setForm({ ...form, weight_kg: e.target.value })}
              aria-describedby="weight-hint"
            />
            <span id="weight-hint" className="sr-only">
              Consignment weight in kilograms. Determines fleet size, cost and which
              transport modes can carry the load.
            </span>
          </label>
        </div>

        <div className="flex items-center gap-2 mt-3 flex-wrap">
          <span className="text-xs text-ink-muted">Typical consignments:</span>
          {[
            ["250", "Medical 250 kg"],
            ["1000", "1 t"],
            ["9000", "Full truck 9 t"],
            ["9500", "9.5 t"],
            ["25000", "25 t"],
            ["40000", "Bulk 40 t"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setForm({ ...form, weight_kg: value })}
              aria-pressed={form.weight_kg === value}
              className="chip"
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex items-center justify-between gap-4 mt-4 flex-wrap">
          {selectedCargo ? (
            <p className="text-sm text-ink-muted flex-1 min-w-[240px]">
              <span className="text-ink-secondary">{selectedCargo.label}:</span>{" "}
              {selectedCargo.rationale}
            </p>
          ) : (
            <span />
          )}
          <button type="submit" disabled={planning} className="btn-primary">
            {planning ? <Spinner /> : null}
            {planning ? "Planning…" : "Plan route"}
          </button>
        </div>
      </Card>

      {error && (
        <div className="mb-4">
          <ErrorState message={error} />
        </div>
      )}

      {result && result.routes?.length === 0 && (
        <Card className="state-warning">
          <p style={{ color: 'var(--status-warning)' }} className="font-medium">No route available</p>
          <p className="text-sm state-warning-dim mt-1">{result.message}</p>
          {result.impassable_segments?.length ? (
            <p className="text-xs mt-2" style={{ color: 'rgba(250, 178, 25, 0.7)' }}>
              Impassable corridors excluded: {result.impassable_segments.join(", ")}
            </p>
          ) : null}
        </Card>
      )}

      {/* Before anything is planned the screen used to be a blank half-page. Showing the
          live network instead means the planner is informative on arrival: an operator can
          see which corridors are degraded and pick an origin knowing what they are up
          against, rather than staring at empty space. */}
      {!result && !planning && (
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 sm:gap-6">
          <Card className="xl:col-span-3 !p-3">
            <RouteMap
              segments={segmentsQuery.data?.segments || []}
              locations={locationsQuery.data?.locations || []}
              height={360}
              fitToHighlight={false}
            />
          </Card>
          <Card className="xl:col-span-2 flex flex-col justify-center">
            <h2 className="text-base font-semibold text-ink">Plan a consignment</h2>
            <p className="text-sm text-ink-secondary mt-2 leading-relaxed">
              Choose an origin and destination above, say what the load weighs, and the
              planner compares every way of moving it — road vehicle classes, rail, the
              Brahmaputra waterway, airlift and porters — over the corridors each one can
              actually use.
            </p>
            <ul className="mt-4 space-y-2 text-sm text-ink-secondary">
              <li className="flex gap-2">
                <span className="text-ink-muted" aria-hidden="true">·</span>
                Weight changes the answer: it sizes the fleet, and crossing a vehicle&apos;s
                capacity steps the cost up.
              </li>
              <li className="flex gap-2">
                <span className="text-ink-muted" aria-hidden="true">·</span>
                Heavier classes need better roads, so a truck and a pickup can be routed
                differently between the same two towns.
              </li>
              <li className="flex gap-2">
                <span className="text-ink-muted" aria-hidden="true">·</span>
                Cargo type and urgency reweight the trade-off between cost, time and risk.
              </li>
            </ul>
          </Card>
        </div>
      )}

      {result?.offline && (
        <Card className="mb-4 state-warning">
          <p style={{ color: 'var(--status-warning)' }} className="font-medium text-sm">
            Planned offline from data stored on this device
          </p>
          <p className="text-xs state-warning-dim mt-1">
            No connection was available, so this used the corridor network cached{" "}
            {result.cache_age}. Conditions may have changed since — confirm on the ground
            before committing a convoy, and re-plan once you are back in coverage.
          </p>
        </Card>
      )}

      {result?.routes?.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 sm:gap-6">
          <div className="xl:col-span-3 space-y-4">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <p className="text-xs text-ink-muted">
                {result.routes.length} route(s) · computed in {result.computation_seconds}s
              </p>
              <div className="flex items-center gap-2">
                {saved ? (
                  <button onClick={() => navigate("/shipments")} className="btn-ghost">
                    View shipment #{saved.id} →
                  </button>
                ) : (
                  <button onClick={saveShipment} disabled={saving} className="btn-ghost">
                    {saving ? <Spinner /> : null}
                    Save as shipment
                  </button>
                )}
              </div>
            </div>

            <TransportOptions
              result={result}
              selectedMode={selectedMode}
              onSelectMode={setSelectedMode}
            />

            <SectionHeading hint="Corridor alternatives for the recommended vehicle class">
              Road route alternatives
            </SectionHeading>

            {result.routes.map((route) => (
              <RouteCard
                key={route.rank}
                route={route}
                primary={route.rank === 1}
                onHover={setHovered}
                isActive={activeRoute?.rank === route.rank}
              />
            ))}
          </div>

          <div className="xl:col-span-2 space-y-4">
            <Card className="!p-3">
              <RouteMap
                segments={segmentsQuery.data?.segments || []}
                locations={locationsQuery.data?.locations || []}
                highlightSegmentIds={highlightIds}
                height={340}
                showLegend={false}
              />
              <p className="text-xs text-ink-muted mt-2 px-1">
                {selectedOption ? `${selectedOption.label}: ` : "Highlighted: "}
                {activeRoute?.path_names?.join(" → ") ||
                  selectedOption?.path_names?.join(" → ")}
              </p>
              {selectedOption && !selectedOption.route && (
                <p className="text-xs text-ink-muted px-1 mt-1">
                  This mode runs on the {selectedOption.category.toLowerCase()} network, so it
                  does not follow the road corridors drawn here.
                </p>
              )}
            </Card>

            {/* Pickup and drop-off, either end of the route. A plan is only actionable once
                somebody knows which counter to take the crate to. */}
            <Card>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <NearbyFacilities point={originPlace} title="Hand over near origin" />
                <NearbyFacilities point={destinationPlace} title="Collect near destination" />
              </div>
            </Card>

            <Card>
              <SectionHeading hint="How this cargo type weights each objective">
                Optimisation profile
              </SectionHeading>
              <WeightBars weights={result.objective_weights} />
            </Card>
          </div>
        </div>
      )}
    </div>
  );
};

export default ShipmentPlanner;
