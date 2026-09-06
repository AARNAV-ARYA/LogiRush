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
from src.modeling.cargo_profiles import DEFAULT_URGENCY, get_weights
from src.modeling.transport_modes import DEFAULT_WEIGHT_KG
from src.optimization.ner_router import NERRouter, build_route_response
from src.services.accessibility_service import AccessibilityService
from src.services.transport_planner import plan_transport_options

logger = logging.getLogger("routing_service")

CACHE_TTL_SECONDS = 20


class RoutingService:
    def __init__(self, service: Optional[AccessibilityService] = None):
        self.accessibility = service or AccessibilityService()
        self._cache = {"assessed": None, "graph": None, "timestamp": 0.0}
        # The dashboard opens five requests at once. Without a lock, an expired cache means
        # all five rebuild the network in parallel — the slowest possible way to answer a
        # question they were all going to share the answer to. One rebuilds; the rest wait
        # a few milliseconds and read the result.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ cache

    def invalidate(self):
        """Drop cached conditions. Called after any write that changes the network."""
        self._cache = {"assessed": None, "graph": None, "timestamp": 0.0}

    def _fresh(self, force: bool) -> bool:
        return (
            not force
            and self._cache["assessed"] is not None
            and (time.time() - self._cache["timestamp"]) < CACHE_TTL_SECONDS
        )

    def get_conditions(self, force: bool = False):
        """Return (assessed_segments, graph), rebuilding if the cache has expired."""
        # Fast path, deliberately outside the lock: a warm cache is the overwhelmingly
        # common case and readers should never queue behind each other for it.
        if self._fresh(force):
            return self._cache["assessed"], self._cache["graph"]

        waiting_since = time.time()
        with self._lock:
            # Someone may have rebuilt while we queued. A rebuild that finished AFTER we
            # started waiting already reflects everything we know about, so it satisfies
            # even a forced refresh — which is what makes five simultaneous cache misses
            # cost one rebuild rather than five.
            rebuilt_while_waiting = (
                self._cache["assessed"] is not None
                and self._cache["timestamp"] >= waiting_since
            )
            if rebuilt_while_waiting or self._fresh(force):
                return self._cache["assessed"], self._cache["graph"]

            assessed = self.accessibility.assess_all_segments()
            graph = NERGraphBuilder(service=self.accessibility).build(assessed_segments=assessed)
            self._cache = {"assessed": assessed, "graph": graph, "timestamp": time.time()}
            return assessed, graph

    def get_assessed(self, force: bool = False):
        return self.get_conditions(force=force)[0]

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
    ) -> dict:
        """Plan a route. Raises ValueError for bad input so callers map it to HTTP 4xx.

        `weight_kg` is the consignment weight. It is not cosmetic: it sizes the fleet, prices
        every option and can change which transport mode — and therefore which route — is
        recommended, because vehicle classes differ in the corridors they can use.
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

        known = self.known_location_ids()
        if origin not in known:
            raise LookupError(f"Unknown origin location id '{origin}'")
        if destination not in known:
            raise LookupError(f"Unknown destination location id '{destination}'")

        started = time.time()
        assessed, graph = self.get_conditions()
        weights = get_weights(cargo_type, urgency)

        router = NERRouter(graph, weights=weights)
        raw_routes = router.find_routes(
            origin, destination, max_routes=max_routes, max_hours=max_hours
        )

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
            }

        routes = [
            build_route_response(r, graph, cargo_type, urgency, weight_kg=weight_kg)
            for r in raw_routes
        ]
        for rank, route in enumerate(routes, start=1):
            route["rank"] = rank

        # Every viable way of actually moving this consignment, each routed on the network
        # its vehicle class can use.
        locations = self.accessibility.provider.get_locations()
        coords_by_id = {l.id: (l.latitude, l.longitude) for l in locations}
        name_by_id = {l.id: getattr(l, "name", l.id) for l in locations}
        transport = plan_transport_options(
            graph, origin, destination, weight_kg, cargo_type, urgency, coords_by_id, name_by_id
        )

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
            "computation_seconds": round(time.time() - started, 3),
            "impassable_segments": [s["id"] for s in assessed if s["impassable"]],
        }


# Single shared instance; the cache is only useful if everyone shares it.
routing_service = RoutingService()
