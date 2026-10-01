# src/services/routing_service.py
"""
Route planning composition service.

Sits between the API layer and the routing internals so that route planning has exactly one
implementation. Both the ad-hoc planner (`POST /api/ner/plan-route`) and shipment
creation/replanning go through `plan()` — otherwise the two would drift and a shipment's
"replan" could silently use different rules from the planner that created it.

Also owns the short-lived assessment cache. Assessing every segment runs one model inference
per segment, and the spec asks for accessibility refresh under 30 seconds and route
calculation under 3 seconds; caching the assessment for a few seconds satisfies both without
serving stale data after a write (writes call `invalidate()`).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from src.data_processing.ner_graph_builder import NERGraphBuilder
from src.modeling.cargo_profiles import DEFAULT_URGENCY, get_hazard_sensitivity, get_weights
from src.modeling.transport_modes import DEFAULT_WEIGHT_KG
from src.optimization.ner_router import NERRouter, build_route_response
from src.services.accessibility_service import AccessibilityService
from src.services.transport_planner import plan_transport_options

logger = logging.getLogger("routing_service")

CACHE_TTL_SECONDS = 20


class RoutingService:
    def __init__(self, service: Optional[AccessibilityService] = None):
        self.accessibility = service or AccessibilityService()
        # One cached (assessed, graph) per condition set. On the Pan-India network the
        # conditions depend on which SIMULATED scenario (if any) is applied and on the month
        # (seasonal closures), so "the network right now" and "the network in January under a
        # Himalayan snowstorm" are different cache entries. Live requests use key (None, None).
        self._caches: dict = {}
        # The dashboard opens five requests at once. Without a lock, an expired cache means
        # all five rebuild the network in parallel — the slowest possible way to answer a
        # question they were all going to share the answer to. One rebuilds; the rest wait
        # a few milliseconds and read the result.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ cache

    @property
    def _cache(self) -> dict:
        """The live-conditions cache entry (backward-compatible view)."""
        return self._caches.get((None, None), {"assessed": None, "graph": None, "timestamp": 0.0})

    def invalidate(self):
        """Drop cached conditions. Called after any write that changes the network."""
        self._caches = {}

    def _key(self, scenario=None, month=None) -> tuple:
        from src.terrain.scenarios import get_scenario
        from src.terrain.seasonal import resolve_month

        scenario_obj = get_scenario(scenario)  # raises ValueError on an unknown id
        if not self.accessibility.terrain_aware:
            return (None, None)
        scenario_id = scenario_obj.id if scenario_obj else None
        explicit_month = None if month in (None, "") else resolve_month(month)
        # The current month is the live case; naming it explicitly shares that cache.
        from datetime import date

        if explicit_month == date.today().month:
            explicit_month = None
        return (scenario_id, explicit_month)

    def _fresh(self, key, force: bool) -> bool:
        entry = self._caches.get(key)
        return (
            not force
            and entry is not None
            and entry["assessed"] is not None
            and (time.time() - entry["timestamp"]) < CACHE_TTL_SECONDS
        )

    def get_conditions(self, force: bool = False, scenario=None, month=None):
        """Return (assessed_segments, graph), rebuilding if the cache has expired."""
        key = self._key(scenario, month)
        # Fast path, deliberately outside the lock: a warm cache is the overwhelmingly
        # common case and readers should never queue behind each other for it.
        if self._fresh(key, force):
            entry = self._caches[key]
            return entry["assessed"], entry["graph"]

        waiting_since = time.time()
        with self._lock:
            # Someone may have rebuilt while we queued. A rebuild that finished AFTER we
            # started waiting already reflects everything we know about, so it satisfies
            # even a forced refresh — which is what makes five simultaneous cache misses
            # cost one rebuild rather than five.
            entry = self._caches.get(key)
            rebuilt_while_waiting = (
                entry is not None
                and entry["assessed"] is not None
                and entry["timestamp"] >= waiting_since
            )
            if rebuilt_while_waiting or self._fresh(key, force):
                return entry["assessed"], entry["graph"]

            if self.accessibility.terrain_aware:
                assessed = self.accessibility.assess_all_segments(scenario=key[0], month=key[1])
            else:
                assessed = self.accessibility.assess_all_segments()
            graph = NERGraphBuilder(service=self.accessibility).build(assessed_segments=assessed)
            self._caches[key] = {"assessed": assessed, "graph": graph, "timestamp": time.time()}
            return assessed, graph

    def get_assessed(self, force: bool = False, scenario=None, month=None):
        return self.get_conditions(force=force, scenario=scenario, month=month)[0]

    # ------------------------------------------------------------------ planning

    def known_location_ids(self) -> set:
        return {loc.id for loc in self.accessibility.provider.get_locations()}

    def plan(
        self,
        origin: str,
        destination: str,
        cargo_type: str = "general",
        urgency: str = DEFAULT_URGENCY,
        max_routes: int = 3,
        max_hours: float = 1e9,
        weight_kg: float = DEFAULT_WEIGHT_KG,
        scenario: Optional[str] = None,
        travel_date=None,
    ) -> dict:
        """Plan a route. Raises ValueError for bad input so callers map it to HTTP 4xx.

        `weight_kg` is the consignment weight. It is not cosmetic: it sizes the fleet, prices
        every option and can change which transport mode — and therefore which route — is
        recommended, because vehicle classes differ in the corridors they can use.

        Pan-India additions:
          `travel_date`  ISO date or datetime of departure (IST). Decides which seasonal
                         closures apply and anchors the restriction-aware schedule.
          `scenario`     id of a SIMULATED disruption (terrain/scenarios.py). The response is
                         then labelled simulated throughout.
        """
        if not origin or not destination:
            raise ValueError("'origin' and 'destination' location ids are required")
        if origin == destination:
            raise ValueError("'origin' and 'destination' must be different")
        try:
            weight_kg = float(weight_kg)
        except (TypeError, ValueError):
            raise ValueError("'weight_kg' must be a number")
        if weight_kg <= 0:
            raise ValueError("'weight_kg' must be greater than zero")
        if weight_kg > 500000:
            raise ValueError("'weight_kg' above 500000 exceeds a single consignment; split the load")

        departure = None
        month = None
        if travel_date not in (None, ""):
            from src.terrain.speed import parse_departure

            try:
                departure = parse_departure(travel_date)
            except (TypeError, ValueError):
                raise ValueError("'travel_date' must be an ISO date (YYYY-MM-DD) or datetime")
            month = departure.month

        known = self.known_location_ids()
        if origin not in known:
            raise LookupError(f"Unknown origin location id '{origin}'")
        if destination not in known:
            raise LookupError(f"Unknown destination location id '{destination}'")

        started = time.time()
        assessed, graph = self.get_conditions(scenario=scenario, month=month)
        weights = get_weights(cargo_type, urgency)
        sensitivity = get_hazard_sensitivity(cargo_type) if self.accessibility.terrain_aware else {}

        router = NERRouter(graph, weights=weights, hazard_sensitivity=sensitivity)
        raw_routes = router.find_routes(
            origin, destination, max_routes=max_routes, max_hours=max_hours
        )

        context = self._planning_context(assessed, scenario, month, departure, sensitivity)

        locations = self.accessibility.provider.get_locations()
        coords_by_id = {l.id: (l.latitude, l.longitude) for l in locations}
        name_by_id = {l.id: getattr(l, "name", l.id) for l in locations}

        if not raw_routes and self.accessibility.terrain_aware:
            # No open road — but that is exactly when rail, a waterway or an airlift matter
            # (Leh in January is reached by air). Offer them instead of an empty answer, and
            # say which kinds of closure cut the road network.
            transport = plan_transport_options(
                graph, origin, destination, weight_kg, cargo_type, urgency, coords_by_id, name_by_id,
                departure=departure,
            )
            counts = {k: len(v) for k, v in context.get("closures", {}).items()}
            described = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items()) or "none"
            return {
                "origin": origin,
                "destination": destination,
                "cargo_type": cargo_type,
                "urgency": urgency,
                "objective_weights": weights,
                **transport,
                "routes": [],
                "recommended_route": None,
                "alternative_routes": [],
                "baseline_comparison": None,
                "computation_seconds": round(time.time() - started, 3),
                "message": (
                    "No open road route between these locations under these conditions. "
                    f"Closed corridors on the network: {described}. Non-road options, where "
                    "the infrastructure exists, are listed under transport options."
                ),
                "impassable_segments": [s["id"] for s in assessed if s["impassable"]],
                **context,
            }

        if not raw_routes:
            return {
                "origin": origin,
                "destination": destination,
                "cargo_type": cargo_type,
                "urgency": urgency,
                "weight_kg": weight_kg,
                "objective_weights": weights,
                "transport_options": [],
                "recommended_transport": None,
                "feasible_count": 0,
                "weight_sensitivity": {},
                "routes": [],
                "recommended_route": None,
                "alternative_routes": [],
                "computation_seconds": round(time.time() - started, 3),
                "message": (
                    "No route currently available between these locations. Impassable "
                    "segments were excluded from the network."
                ),
                "impassable_segments": [s["id"] for s in assessed if s["impassable"]],
                **context,
            }

        routes = [
            build_route_response(r, graph, cargo_type, urgency, weight_kg=weight_kg,
                                 departure=departure, hazard_sensitivity=sensitivity or None)
            for r in raw_routes
        ]
        for rank, route in enumerate(routes, start=1):
            route["rank"] = rank

        # Every viable way of actually moving this consignment, each routed on the network
        # its vehicle class can use.
        transport = plan_transport_options(
            graph, origin, destination, weight_kg, cargo_type, urgency, coords_by_id, name_by_id,
            departure=departure,
        )

        baseline = None
        if self.accessibility.terrain_aware:
            baseline = _baseline_comparison(graph, origin, destination, routes[0], cargo_type, urgency,
                                            weight_kg, departure)

        return {
            "origin": origin,
            "destination": destination,
            "cargo_type": cargo_type,
            "urgency": urgency,
            "objective_weights": weights,
            **transport,
            "routes": routes,
            "recommended_route": routes[0],
            "alternative_routes": routes[1:],
            "baseline_comparison": baseline,
            "computation_seconds": round(time.time() - started, 3),
            "impassable_segments": [s["id"] for s in assessed if s["impassable"]],
            **context,
        }

    def _planning_context(self, assessed, scenario, month, departure, sensitivity) -> dict:
        """What the plan was computed under — closures by type, scenario, season, weather source."""
        if not self.accessibility.terrain_aware:
            return {}
        from src.terrain.scenarios import get_scenario
        from src.terrain.seasonal import resolve_month, season_of

        scenario_obj = get_scenario(scenario)
        closures = {}
        for s in assessed:
            closure = s.get("closure")
            if closure:
                closures.setdefault(closure["type"], []).append({
                    "segment_id": s["id"],
                    "label": f"{s['source_name']} → {s['destination_name']}",
                    "reason": closure["reason"],
                })
        month_used = resolve_month(month)
        return {
            "network": "india",
            "simulated": scenario_obj is not None,
            "scenario": None if scenario_obj is None else {
                "id": scenario_obj.id, "label": scenario_obj.label,
                "description": scenario_obj.description, "simulated": True,
            },
            "travel_date": departure.isoformat() if departure else None,
            "month": month_used,
            "season": season_of(month_used),
            "closures": closures,
            "hazard_sensitivity": sensitivity,
            "conditions": self.accessibility.provider.conditions_status(),
        }


def _baseline_comparison(graph, origin, destination, recommended, cargo_type, urgency, weight_kg, departure):
    """What a terrain-blind planner would have picked, and what choosing differently buys.

    The baseline is the shortest-distance path over the same open network — what a generic
    navigation app does. It still respects closures (a baseline that drives over a closed
    pass is a straw man), but ignores hazards, accessibility and reliability. Showing both
    side by side is the evidence that the terrain engine changes decisions, and by how much.
    """
    import networkx as nx

    try:
        simple = nx.DiGraph()
        for u, v, data in graph.edges(data=True):
            if not simple.has_edge(u, v) or data["distance"] < simple[u][v]["distance"]:
                simple.add_edge(u, v, **data)
        path = nx.shortest_path(simple, origin, destination, weight="distance")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None

    edges = [dict(simple[u][v]) for u, v in zip(path, path[1:])]
    router = NERRouter(graph, weights=get_weights(cargo_type, urgency))
    raw = {"path": path, "edges": edges, "total_hours": round(sum(e["time"] for e in edges), 2),
           "costs": {}, "score": 0.0}
    raw["score"] = round(sum(w * c for w, c in zip(router._weight_vector(), router._true_costs(raw))), 3)
    baseline = build_route_response(raw, graph, cargo_type, urgency, weight_kg=weight_kg, departure=departure)

    same = baseline["path"] == recommended["path"]

    def peak(route):
        return route.get("peak_segment_risk_percent") or 0.0

    def arrival_hours(route):
        schedule = route.get("schedule")
        return schedule["elapsed_hours"] if schedule else route["eta_hours"]

    return {
        "method": "Shortest distance over open corridors (ignores hazards, accessibility, reliability)",
        "same_as_recommended": same,
        "baseline": {
            "path_names": baseline["path_names"],
            "total_distance_km": baseline["total_distance_km"],
            "eta_hours": baseline["eta_hours"],
            "elapsed_hours": arrival_hours(baseline),
            "worst_segment_accessibility": baseline["worst_segment_accessibility"],
            "peak_segment_risk_percent": peak(baseline),
            "route_score": baseline["route_score"],
        },
        "difference": {
            "extra_distance_km": round(recommended["total_distance_km"] - baseline["total_distance_km"], 1),
            "extra_elapsed_hours": round(arrival_hours(recommended) - arrival_hours(baseline), 2),
            "peak_risk_reduction": round(peak(baseline) - peak(recommended), 1),
            "worst_accessibility_gain": round(
                (recommended["worst_segment_accessibility"] or 0) - (baseline["worst_segment_accessibility"] or 0), 1
            ),
        },
    }


# Single shared instance; the cache is only useful if everyone shares it.
routing_service = RoutingService()
