// src/utils/offlinePlanner.js
//
// Route planning with no connectivity.
//
// When the network is unreachable the platform still has, in IndexedDB, the last corridor
// assessment it downloaded and the transport rate cards. That is enough to answer the
// question a stranded despatcher actually has: given what we last knew about the roads, how
// do I get this load from A to B and what will it cost?
//
// This deliberately mirrors the server's scoring rather than inventing a simpler one:
//   * the same five normalised objectives (time, cost, accessibility, risk, reliability)
//   * the same normalisation references
//   * the same cargo weight vectors, which are cached from the API
//   * the same per-mode accessibility floors and rate cards, also cached from the API
//
// so an offline answer and an online answer for the same inputs agree. Where it differs is
// honesty about provenance: every offline result is stamped `offline: true` with the age of
// the data it used, because a three-day-old view of a monsoon-hit corridor is a starting
// point, not a fact.

import { readReference, describeCacheAge } from "./offlineStore";

// Must match ner_graph_builder.py — if the server retunes these, the cached copy of
// /transport-modes will not save us, so they are named and kept together.
const TIME_REFERENCE_HOURS = 12.0;
const COST_REFERENCE_INR = 30000.0;
const FREIGHT_RATE_INR_PER_KM = 45.0;

const STATUS_PENALTY = {
  open: 0,
  "partially blocked": 35,
  "under repair": 30,
  closed: 100,
};

const normalise = (value, reference) =>
  Math.round(Math.min(100, Math.max(0, (value / reference) * 100)) * 100) / 100;

function reliabilityPenalty(segment) {
  const status = (segment.road_status || "").trim().toLowerCase();
  const base = STATUS_PENALTY[status] ?? 20;
  const incidents = segment.active_incident_count || 0;
  return Math.min(100, base + Math.min(30, incidents * 10));
}

/** Turn cached segments into an adjacency list, dropping what cannot be driven. */
function buildGraph(segments, minAccessibility = 0) {
  const adjacency = new Map();
  const add = (from, to, edge) => {
    if (!adjacency.has(from)) adjacency.set(from, []);
    adjacency.get(from).push({ ...edge, to });
  };

  for (const seg of segments) {
    if (seg.impassable) continue;
    if ((seg.accessibility_score ?? 0) < minAccessibility) continue;

    const disruption = (seg.prediction?.combined_disruption_probability ?? 0) * 100;
    const cost = seg.distance_km * FREIGHT_RATE_INR_PER_KM;
    const edge = {
      segment_id: seg.id,
      highway_corridor: seg.highway_corridor,
      road_status: seg.road_status,
      distance_km: seg.distance_km,
      travel_time_hours: seg.travel_time_hours,
      accessibility_score: seg.accessibility_score,
      disruption_risk_percent: Math.round(disruption * 100) / 100,
      obj: {
        time: normalise(seg.travel_time_hours, TIME_REFERENCE_HOURS),
        cost: normalise(cost, COST_REFERENCE_INR),
        accessibility: Math.round((100 - seg.accessibility_score) * 100) / 100,
        risk: Math.round(disruption * 100) / 100,
        reliability: reliabilityPenalty(seg),
      },
    };
    // Roads are bidirectional.
    add(seg.source, seg.destination, edge);
    add(seg.destination, seg.source, edge);
  }
  return adjacency;
}

/**
 * Weighted least-cost search over the five objectives.
 *
 * Time and cost accumulate; accessibility, risk and reliability take the running maximum,
 * because a route is only as passable as its worst segment — averaging them would let a
 * long stretch of good road hide one washed-out bridge, which is the exact failure this
 * platform exists to prevent.
 */
function search(adjacency, origin, destination, weights) {
  const combine = (costs) =>
    weights.time * costs.time +
    weights.cost * costs.cost +
    weights.accessibility * costs.accessibility +
    weights.risk * costs.risk +
    weights.reliability * costs.reliability;

  const start = {
    node: origin,
    path: [origin],
    edges: [],
    costs: { time: 0, cost: 0, accessibility: 0, risk: 0, reliability: 0 },
    hours: 0,
  };
  const best = new Map([[origin, 0]]);
  const queue = [start];

  let found = null;
  while (queue.length) {
    // Small network (tens of nodes): a linear scan is clearer than a heap and fast enough.
    let bestIndex = 0;
    for (let i = 1; i < queue.length; i += 1) {
      if (combine(queue[i].costs) < combine(queue[bestIndex].costs)) bestIndex = i;
    }
    const current = queue.splice(bestIndex, 1)[0];

    if (current.node === destination) {
      found = current;
      break;
    }

    for (const edge of adjacency.get(current.node) || []) {
      if (current.path.includes(edge.to)) continue; // no cycles
      const costs = {
        time: current.costs.time + edge.obj.time,
        cost: current.costs.cost + edge.obj.cost,
        accessibility: Math.max(current.costs.accessibility, edge.obj.accessibility),
        risk: Math.max(current.costs.risk, edge.obj.risk),
        reliability: Math.max(current.costs.reliability, edge.obj.reliability),
      };
      const score = combine(costs);
      if (best.has(edge.to) && best.get(edge.to) <= score) continue;
      best.set(edge.to, score);
      queue.push({
        node: edge.to,
        path: [...current.path, edge.to],
        edges: [...current.edges, edge],
        costs,
        hours: current.hours + edge.travel_time_hours,
      });
    }
  }
  return found;
}

/** Fleet sizing and pricing, using the rate card cached from the server. */
function priceOption(mode, weightKg, distanceKm) {
  const rate = mode.rate_card;
  const tonnes = weightKg / 1000;
  const vehicles = Math.max(1, Math.ceil(weightKg / mode.capacity_kg));
  const dispatch = rate.dispatch_per_vehicle_inr * vehicles;
  const running = rate.per_km_per_vehicle_inr * distanceKm * vehicles;
  const haulage = rate.per_tonne_km_inr * tonnes * distanceKm;
  const handling = rate.handling_per_tonne_inr * tonnes;
  const total = dispatch + running + haulage + handling;
  return {
    dispatch_inr: Math.round(dispatch * 100) / 100,
    running_inr: Math.round(running * 100) / 100,
    haulage_inr: Math.round(haulage * 100) / 100,
    handling_inr: Math.round(handling * 100) / 100,
    total_inr: Math.round(total * 100) / 100,
    vehicles,
    cost_per_tonne_inr: tonnes ? Math.round((total / tonnes) * 100) / 100 : null,
    cost_per_kg_inr: weightKg ? Math.round((total / weightKg) * 100) / 100 : null,
  };
}

function buildRoute(found, nameById, weightKg, modeLabel, modeId, vehicles, cost) {
  const segments = found.edges.map((e) => ({
    segment_id: e.segment_id,
    highway_corridor: e.highway_corridor,
    road_status: e.road_status,
    distance_km: e.distance_km,
    travel_time_hours: e.travel_time_hours,
    accessibility_score: e.accessibility_score,
    disruption_risk_percent: e.disruption_risk_percent,
  }));
  const accessScores = segments.map((s) => s.accessibility_score);
  const risks = segments.map((s) => s.disruption_risk_percent);
  const distance = segments.reduce((sum, s) => sum + s.distance_km, 0);

  return {
    path: found.path,
    path_names: found.path.map((id) => nameById[id] || id),
    segments,
    total_distance_km: Math.round(distance * 100) / 100,
    estimated_cost_inr: cost.total_inr,
    weight_kg: weightKg,
    priced_mode: modeId,
    priced_mode_label: modeLabel,
    vehicles_required: vehicles,
    cost_breakdown: cost,
    eta_hours: Math.round(found.hours * 100) / 100,
    eta_days: Math.round((found.hours / 24) * 100) / 100,
    accessibility_score: accessScores.length
      ? Math.round((accessScores.reduce((a, b) => a + b, 0) / accessScores.length) * 100) / 100
      : null,
    worst_segment_accessibility: accessScores.length ? Math.min(...accessScores) : null,
    risk_score: risks.length
      ? Math.round((risks.reduce((a, b) => a + b, 0) / risks.length) * 100) / 100
      : null,
    peak_segment_risk_percent: risks.length ? Math.max(...risks) : null,
    rank: 1,
  };
}

/**
 * Plan entirely from cached data.
 *
 * Returns the same shape the API returns so the planner screen renders it without knowing
 * whether it came from the server or the device — plus `offline: true` and a data-age note.
 */
export async function planOffline({ origin, destination, cargo_type, urgency, weight_kg }) {
  const [segmentsEntry, locationsEntry, cargoEntry, modesEntry] = await Promise.all([
    readReference("segments"),
    readReference("locations"),
    readReference("cargo-types"),
    readReference("transport-modes"),
  ]);

  if (!segmentsEntry || !locationsEntry || !modesEntry) {
    throw new Error(
      "No offline copy of the road network is stored on this device yet. Connect once while " +
        "in coverage to download it, then offline planning will work anywhere."
    );
  }

  const segments = segmentsEntry.value.segments || [];
  const locations = locationsEntry.value.locations || [];
  const modes = modesEntry.value.modes || [];
  const nameById = Object.fromEntries(locations.map((l) => [l.id, l.name]));

  const cargo = (cargoEntry?.value?.cargo_types || []).find((c) => c.id === cargo_type);
  const weights = cargo?.weights || {
    time: 0.2, cost: 0.2, accessibility: 0.2, risk: 0.2, reliability: 0.2,
  };

  const weightKg = Number(weight_kg) || 1000;
  const options = [];

  for (const mode of modes) {
    const vehicles = Math.max(1, Math.ceil(weightKg / mode.capacity_kg));
    const base = {
      mode: mode.id,
      label: mode.label,
      category: mode.category,
      network: mode.network,
      capacity_kg: mode.capacity_kg,
      vehicles,
      note: mode.note,
    };

    // Offline we can only reason about the road network we cached. Rail, waterway and air
    // depend on infrastructure and schedules the device has no offline copy of, so they are
    // listed as needing a connection rather than guessed at.
    if (mode.network !== "road") {
      options.push({
        ...base,
        feasible: false,
        blocker: "offline",
        reason: `${mode.category} options need a connection to confirm terminal and schedule availability.`,
      });
      continue;
    }

    const adjacency = buildGraph(segments, mode.min_accessibility);
    const found = search(adjacency, origin, destination, weights);
    if (!found) {
      options.push({
        ...base,
        feasible: false,
        blocker: "access",
        reason: `No cached corridor meets the ${mode.min_accessibility}/100 accessibility this vehicle class needs.`,
      });
      continue;
    }

    const distance = found.edges.reduce((sum, e) => sum + e.distance_km, 0);
    const cost = priceOption(mode, weightKg, distance);
    const hours = Math.round((found.hours * (40 / mode.speed_kmph) + 1) * 100) / 100;
    const worstAccess = Math.min(...found.edges.map((e) => e.accessibility_score));
    const peakRisk = Math.max(...found.edges.map((e) => e.disruption_risk_percent));

    options.push({
      ...base,
      feasible: true,
      route: buildRoute(found, nameById, weightKg, mode.label, mode.id, cost.vehicles, cost),
      path_names: found.path.map((id) => nameById[id] || id),
      distance_km: Math.round(distance * 100) / 100,
      eta_hours: hours,
      eta_days: Math.round((hours / 24) * 100) / 100,
      cost_inr: cost.total_inr,
      cost_breakdown: cost,
      risk_percent: peakRisk,
      accessibility_penalty: Math.round((100 - worstAccess) * 100) / 100,
      reliability_penalty: null,
      co2_kg: Math.round((mode.co2_g_per_tonne_km * (weightKg / 1000) * distance) / 100) / 10,
      capacity_note: {
        vehicles: cost.vehicles,
        capacity_kg: mode.capacity_kg * cost.vehicles,
        headroom_kg: mode.capacity_kg * cost.vehicles - weightKg,
        next_vehicle_at_kg: mode.capacity_kg * cost.vehicles + 1,
      },
      why: [
        `Planned on this device from the road network cached ${describeCacheAge(segmentsEntry)}.`,
        `${(weightKg / 1000).toFixed(2)} t needs ${cost.vehicles} unit(s) at ${mode.capacity_kg.toLocaleString("en-IN")} kg each.`,
        `Restricted to cached segments scoring at least ${mode.min_accessibility}/100 accessibility.`,
      ],
    });
  }

  const feasible = options.filter((o) => o.feasible).sort((a, b) => a.cost_inr - b.cost_inr);
  feasible.forEach((o, i) => {
    o.rank = i + 1;
  });
  const ordered = [...feasible, ...options.filter((o) => !o.feasible)];
  const recommended = feasible[0] || null;

  return {
    status: "success",
    offline: true,
    data_source: "device-cache",
    cache_age: describeCacheAge(segmentsEntry),
    cached_at: segmentsEntry.cached_at,
    origin,
    destination,
    cargo_type,
    urgency,
    weight_kg: weightKg,
    objective_weights: weights,
    routes: recommended?.route ? [recommended.route] : [],
    recommended_route: recommended?.route || null,
    alternative_routes: [],
    transport_options: ordered,
    recommended_transport: recommended?.mode || null,
    feasible_count: feasible.length,
    weight_sensitivity: {},
    computation_seconds: 0,
    message: recommended
      ? null
      : "No route found in the cached network between these locations.",
  };
}
