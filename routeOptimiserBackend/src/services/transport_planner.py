# src/services/transport_planner.py
"""
Multimodal option planning (SIH Module 4b).

Given an origin, a destination, a consignment weight and a cargo profile, this produces the
set of *ways you could actually move it* — not one route, but one option per transport mode,
each with its own route, its own price and its own reason for being viable or not.

Two design decisions matter here.

**Each vehicle class gets its own route.** A multi-axle truck cannot use a corridor scoring
30/100 on accessibility; a pickup can. So instead of pricing one shared path differently per
mode, the planner prunes the network to the segments each mode can actually operate on and
re-routes. That is why a heavy truck may be sent the long way round while a pickup takes the
direct damaged road — which is exactly how despatchers reason in the field.

**Weight decides the answer, not just the number.** Fleet size steps at capacity boundaries,
so the cheapest mode changes as the consignment grows: one pickup beats a truck at 400 kg,
and the truck wins long before you would need nine pickups. Rail and waterway only become
competitive once there are enough tonnes to absorb their terminal handling.

Ranking uses the cargo profile's own objective weights, so a medicine consignment and a
general consignment can legitimately pick different modes for the same route and weight.
"""

from __future__ import annotations

import logging

from src.modeling.cargo_profiles import get_weights
from src.modeling.transport_modes import (
    NETWORK_DETOUR_FACTOR,
    TRANSPORT_MODES,
    cost_breakdown,
    duration_hours,
    haversine_km,
    infrastructure_gap,
    mode_serves,
    next_capacity_threshold,
    vehicles_required,
)
from src.optimization.ner_router import NERRouter, build_route_response

logger = logging.getLogger("transport_planner")

# How exposed each mode is to conditions, on the same 0-100 "lower is better" scale the
# router uses. Road modes inherit the risk of the corridor they were routed over; the others
# carry their own characteristic exposure, which is the point of using them at all.
MODE_BASE_RISK = {"rail": 12.0, "water": 24.0, "air": 16.0}

# Dependability penalty per mode (0-100, lower is better): schedule adherence, breakdown
# exposure and how badly a disruption strands the consignment mid-journey.
MODE_RELIABILITY_PENALTY = {
    "pickup": 26.0,
    "lcv": 22.0,
    "truck": 19.0,
    "multi_axle": 17.0,
    "rail": 11.0,
    "waterway": 30.0,
    "air_heli": 21.0,
    "porter": 38.0,
}


def _prune_graph(graph, min_accessibility: float):
    """The sub-network a vehicle class can actually operate on.

    Segments below the mode's accessibility floor are removed outright rather than penalised,
    because a road that cannot carry a 25-tonne truck is not an expensive option for that
    truck — it is not an option at all.
    """
    if min_accessibility <= 0:
        return graph
    # The network is a MultiDiGraph (parallel corridors between the same pair are real), so
    # edges must be identified by key as well as endpoints.
    if graph.is_multigraph():
        keep = [
            (u, v, k)
            for u, v, k, d in graph.edges(keys=True, data=True)
            if d.get("accessibility_score", 0.0) >= min_accessibility
        ]
    else:
        keep = [
            (u, v)
            for u, v, d in graph.edges(data=True)
            if d.get("accessibility_score", 0.0) >= min_accessibility
        ]
    if not keep:
        return None
    return graph.edge_subgraph(keep).copy()


def _road_option(graph, origin, destination, mode_id, cargo_type, urgency, weights):
    """Route this vehicle class over the network it can use. Returns (route, reason_if_none)."""
    mode = TRANSPORT_MODES[mode_id]
    pruned = _prune_graph(graph, mode["min_accessibility"])
    if pruned is None or origin not in pruned or destination not in pruned:
        return None, (
            f"No corridor between these locations meets the "
            f"{mode['min_accessibility']:.0f}/100 accessibility this vehicle class needs."
        )
    router = NERRouter(pruned, weights=weights)
    raw = router.find_routes(origin, destination, max_routes=1)
    if not raw:
        return None, (
            f"Every remaining path is blocked for this vehicle class once segments below "
            f"{mode['min_accessibility']:.0f}/100 accessibility are excluded."
        )
    return build_route_response(raw[0], pruned, cargo_type, urgency), None


def _minmax(values):
    """Normalise to 0-100, lower still meaning better. Flat sets collapse to 0."""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.0 for _ in values]
    return [100.0 * (v - lo) / (hi - lo) for v in values]


def plan_transport_options(
    graph,
    origin: str,
    destination: str,
    weight_kg: float,
    cargo_type: str,
    urgency: str,
    coords_by_id: dict,
    name_by_id: dict,
) -> dict:
    """Build the full option set for this consignment.

    Returns the options (feasible first, best ranked first), the recommended mode, and the
    weight-sensitivity readout the UI uses to explain how the answer would change if the
    consignment grew.
    """
    weights = get_weights(cargo_type, urgency)
    options = []

    def name_of(loc_id):
        return name_by_id.get(loc_id, loc_id)

    for mode_id, mode in TRANSPORT_MODES.items():
        fleet = vehicles_required(weight_kg, mode_id)
        base = {
            "mode": mode_id,
            "label": mode["label"],
            "category": mode["category"],
            "network": mode["network"],
            "capacity_kg": mode["capacity_kg"],
            "vehicles": fleet,
            "note": mode["note"],
        }

        # 1. Does the infrastructure exist at both ends?
        gap = infrastructure_gap(origin, destination, mode_id, name_of)
        if gap:
            options.append({**base, "feasible": False, "reason": gap, "blocker": "infrastructure"})
            continue

        # 2. Route it on the network this mode can use.
        if mode["network"] == "road":
            route, reason = _road_option(
                graph, origin, destination, mode_id, cargo_type, urgency, weights
            )
            if route is None:
                options.append({**base, "feasible": False, "reason": reason, "blocker": "access"})
                continue
            distance_km = route["total_distance_km"]
            hours = duration_hours(distance_km, mode_id, road_hours=route["eta_hours"])
            risk = route["peak_segment_risk_percent"] or 0.0
            access_penalty = 100.0 - (route["worst_segment_accessibility"] or 100.0)
            reliability = MODE_RELIABILITY_PENALTY[mode_id] + access_penalty * 0.3
            path_names = route["path_names"]
        else:
            if origin not in coords_by_id or destination not in coords_by_id:
                options.append({
                    **base, "feasible": False,
                    "reason": "Coordinates unavailable for one of the endpoints.",
                    "blocker": "data",
                })
                continue
            straight = haversine_km(coords_by_id[origin], coords_by_id[destination])
            distance_km = round(straight * NETWORK_DETOUR_FACTOR[mode["network"]], 2)
            route = None
            hours = duration_hours(distance_km, mode_id)
            risk = MODE_BASE_RISK[mode["network"]]
            access_penalty = 10.0
            reliability = MODE_RELIABILITY_PENALTY[mode_id]
            path_names = [name_of(origin), name_of(destination)]

        # 3. Price it for this actual consignment.
        cost = cost_breakdown(weight_kg, distance_km, mode_id)
        tonnes = float(weight_kg) / 1000.0

        options.append({
            **base,
            "feasible": True,
            "route": route,
            "path_names": path_names,
            "distance_km": round(distance_km, 2),
            "eta_hours": hours,
            "eta_days": round(hours / 24.0, 2),
            "cost_inr": cost["total_inr"],
            "cost_breakdown": cost,
            "risk_percent": round(risk, 2),
            "accessibility_penalty": round(access_penalty, 2),
            "reliability_penalty": round(reliability, 2),
            "co2_kg": round(mode["co2_g_per_tonne_km"] * tonnes * distance_km / 1000.0, 1),
            "capacity_note": next_capacity_threshold(weight_kg, mode_id),
        })

    feasible = [o for o in options if o["feasible"]]
    infeasible = [o for o in options if not o["feasible"]]

    # 4. Rank the feasible options using the cargo profile's own priorities.
    if feasible:
        norm = {
            "time": _minmax([o["eta_hours"] for o in feasible]),
            "cost": _minmax([o["cost_inr"] for o in feasible]),
            "risk": _minmax([o["risk_percent"] for o in feasible]),
            "accessibility": _minmax([o["accessibility_penalty"] for o in feasible]),
            "reliability": _minmax([o["reliability_penalty"] for o in feasible]),
        }
        for i, opt in enumerate(feasible):
            opt["fit_score"] = round(
                sum(weights.get(k, 0.0) * norm[k][i] for k in norm), 2
            )
            opt["score_components"] = {k: round(norm[k][i], 1) for k in norm}
        # Guard against a profile's non-cost priorities recommending something absurd.
        # Helicopter scores beautifully on risk and speed, but recommending a Rs 12 lakh
        # airlift for a consignment a Rs 75,000 truck can carry is not advice anyone can
        # act on. Premium modes stay in the list, ranked and priced, but they only take the
        # top slot when urgency justifies them or nothing cheaper is feasible.
        cheapest_cost = min(o["cost_inr"] for o in feasible)
        premium_ceiling = _premium_ceiling(cargo_type, urgency)
        for o in feasible:
            ratio = o["cost_inr"] / cheapest_cost if cheapest_cost else 1.0
            o["cost_ratio_vs_cheapest"] = round(ratio, 2)
            o["disproportionate_cost"] = ratio > premium_ceiling
            if o["disproportionate_cost"]:
                o["cost_caveat"] = (
                    f"Costs {ratio:.1f}x the cheapest feasible option, beyond the "
                    f"{premium_ceiling:.0f}x ceiling for '{cargo_type}' cargo at '{urgency}' "
                    f"urgency. Still shown because isolation or a deadline can justify it, "
                    f"but it is not the default recommendation."
                )
        feasible.sort(key=lambda o: (o["disproportionate_cost"], o["fit_score"], o["cost_inr"]))
        for rank, opt in enumerate(feasible, start=1):
            opt["rank"] = rank
            opt["why"] = _why(opt, feasible, cargo_type, weight_kg)

    ordered = feasible + infeasible
    recommended = feasible[0] if feasible else None

    return {
        "weight_kg": round(float(weight_kg), 2),
        "transport_options": ordered,
        "recommended_transport": recommended["mode"] if recommended else None,
        "feasible_count": len(feasible),
        "weight_sensitivity": _weight_sensitivity(feasible, weight_kg),
    }


def _premium_ceiling(cargo_type: str, urgency: str) -> float:
    """How much more than the cheapest option a recommendation may cost.

    Emergencies genuinely do justify paying many times over the odds — an airlift into a
    cut-off district is the right call even at twenty times the road price. Routine
    despatches do not. The ceiling therefore widens with urgency and with how
    time-critical the cargo is, rather than being a single fixed number.
    """
    by_urgency = {"low": 1.6, "normal": 2.5, "high": 5.0, "critical": 25.0}
    by_cargo = {"medicine": 3.0, "relief": 2.0, "perishable": 1.8, "food": 1.3, "general": 1.0}
    return by_urgency.get(urgency, 2.5) * by_cargo.get(cargo_type, 1.0)


def _why(opt, feasible, cargo_type, weight_kg) -> list:
    """Plain-language reasons this option landed where it did in the ranking."""
    reasons = []
    cheapest = min(feasible, key=lambda o: o["cost_inr"])
    fastest = min(feasible, key=lambda o: o["eta_hours"])
    tonnes = float(weight_kg) / 1000.0

    if opt["mode"] == cheapest["mode"]:
        reasons.append("Cheapest feasible option for this consignment.")
    else:
        delta = opt["cost_inr"] - cheapest["cost_inr"]
        reasons.append(
            f"Costs \u20b9{delta:,.0f} more than the cheapest option "
            f"({cheapest['label']})."
        )
    if opt["mode"] == fastest["mode"]:
        reasons.append("Fastest feasible option.")
    else:
        delta_h = opt["eta_hours"] - fastest["eta_hours"]
        reasons.append(f"Arrives {delta_h:.1f} h later than the fastest option ({fastest['label']}).")

    fleet = opt["vehicles"]
    if fleet > 1:
        reasons.append(
            f"{tonnes:.2f} t needs {fleet} units at {opt['capacity_kg']:,} kg each, "
            f"which is what drives the dispatch and running cost."
        )
    else:
        head = opt["capacity_note"]["headroom_kg"]
        reasons.append(
            f"One unit carries the whole {tonnes:.2f} t with {head:,.0f} kg spare capacity."
        )

    if opt.get("cost_caveat"):
        reasons.append(opt["cost_caveat"])

    if opt["network"] == "road":
        reasons.append(
            f"Routed over {opt['distance_km']:,.0f} km via {' -> '.join(opt['path_names'])}, "
            f"restricted to segments scoring at least "
            f"{TRANSPORT_MODES[opt['mode']]['min_accessibility']:.0f}/100 accessibility."
        )
    else:
        reasons.append(
            f"Runs {opt['distance_km']:,.0f} km on the {opt['category'].lower()} network, "
            f"independent of road conditions."
        )
    return reasons


def _weight_sensitivity(feasible, weight_kg) -> dict:
    """How the recommendation and the price move as the consignment grows.

    Field planners consolidate loads to avoid paying for a half-empty extra vehicle, so the
    most useful thing the platform can show is where the next cliff is and what it costs.
    """
    if not feasible:
        return {}
    best = feasible[0]
    cap = best["capacity_note"]
    curve = []
    for opt in feasible[:4]:
        points = []
        for w in _curve_points(weight_kg, opt["capacity_kg"]):
            c = cost_breakdown(w, opt["distance_km"], opt["mode"])
            points.append({"weight_kg": w, "cost_inr": c["total_inr"], "vehicles": c["vehicles"]})
        curve.append({"mode": opt["mode"], "label": opt["label"], "points": points})

    next_w = cap["next_vehicle_at_kg"]
    at_next = cost_breakdown(next_w, best["distance_km"], best["mode"])
    return {
        "current_vehicles": cap["vehicles"],
        "headroom_kg": cap["headroom_kg"],
        "next_vehicle_at_kg": next_w,
        "cost_now_inr": best["cost_inr"],
        "cost_after_next_vehicle_inr": at_next["total_inr"],
        "step_increase_inr": round(at_next["total_inr"] - best["cost_inr"], 2),
        "summary": (
            f"{cap['headroom_kg']:,.0f} kg of spare capacity remains on the "
            f"{cap['vehicles']} unit(s) already priced. Crossing "
            f"{next_w:,.0f} kg adds another {best['label']} and steps the cost up by "
            f"\u20b9{at_next['total_inr'] - best['cost_inr']:,.0f}."
        ),
        "cost_curves": curve,
    }


def _curve_points(weight_kg, capacity_kg):
    """A weight ladder that deliberately straddles capacity boundaries so the steps show."""
    w = float(weight_kg)
    candidates = {
        max(50.0, round(w * 0.25)), max(100.0, round(w * 0.5)), round(w),
        round(w * 1.5), round(w * 2.0),
        float(capacity_kg), float(capacity_kg) + 1, float(capacity_kg) * 2,
    }
    return sorted(x for x in candidates if x > 0)[:8]
