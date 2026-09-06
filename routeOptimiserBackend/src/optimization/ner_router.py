# src/optimization/ner_router.py
"""
Risk-Aware Routing (SIH Module 3).

EXTENDS the existing multi-objective A* rather than replacing it: NERRouter subclasses
MOAStar and overrides only the objective vector, the per-edge cost accumulation and the
heuristic. The search itself — the Pareto frontier pruning, the open/closed set handling,
the f = g + h expansion — is the original implementation, unchanged.

Objectives (all normalised 0-100, lower is better, see ner_graph_builder.py):
    time, cost, accessibility, risk, reliability

Alternative routes are produced by penalising the edges of already-found routes and
re-searching, which yields genuinely different corridors instead of near-identical paths
differing by one node.

Every route comes back with a plain-language explanation. Per the spec, results are framed
as recommendations and predictions, never guarantees.
"""

from __future__ import annotations

import logging
import math
from heapq import heappop, heappush

from src.modeling.cargo_profiles import OBJECTIVES, get_weights, describe_priority_order
from src.modeling.transport_modes import (
    DEFAULT_WEIGHT_KG,
    TRANSPORT_MODES,
    cost_breakdown,
)
from src.optimization.moa_star import MOAStar

logger = logging.getLogger("ner_router")

# Straight-line speed assumption used only by the A* heuristic. Must be optimistic (faster
# than any real road) so the heuristic stays admissible and A* keeps its optimality property.
HEURISTIC_SPEED_KMH = 60.0


class NERRouter(MOAStar):
    OBJECTIVE_KEYS = ("time", "cost", "accessibility", "risk", "reliability")

    def __init__(self, G, weights: dict | None = None):
        # MOAStar.__init__ constructs GeocodingUtils; we reuse it for node coordinates.
        super().__init__(G)
        self.weights = weights or {obj: 0.2 for obj in OBJECTIVES}
        self._edge_penalties: dict = {}

    # ------------------------------------------------------------------ overrides

    def _edge_costs(self, current, neighbor, edge_data, costs, weight_kg):
        """Accumulate the five normalised objectives across one road segment.

        Time and cost are ADDITIVE — they genuinely accumulate with every extra kilometre.

        Accessibility, risk and reliability are BOTTLENECK objectives (running maximum), not
        sums. This matters: if they were summed, they would grow with the number of segments,
        so the shortest path would automatically win on every objective simultaneously and
        the cargo profile weights would have no visible effect at all. Conceptually the
        bottleneck is also the correct model — a convoy is stopped by its single worst
        landslide-prone stretch, not by the arithmetic total of its segments' risk. A route
        through five safe segments is safer than one through a single blocked pass, and only
        max-semantics express that.

        `weight_kg` is accepted for interface compatibility with the parent class but is not
        used: all five objectives are already normalised per-segment scores, and cargo mass is
        expressed through the cargo profile's weight vector instead.

        The alternative-route penalty is applied to the additive time objective only. Adding
        it inside the max() terms would corrupt a route's reported bottleneck values.
        """
        penalty = self._edge_penalties.get(edge_data.get("segment_id"), 0.0)
        return (
            costs[0] + edge_data["obj_time"] + penalty,
            costs[1] + edge_data["obj_cost"],
            max(costs[2], edge_data["obj_accessibility"]),
            max(costs[3], edge_data["obj_risk"]),
            max(costs[4], edge_data["obj_reliability"]),
        )

    def heuristic(self, node, goal, weights):
        """Admissible straight-line-distance heuristic in normalised time units.

        Only the time objective gets a non-zero estimate. Accessibility, risk and reliability
        cannot be lower-bounded from geometry (a short hop can be catastrophic), so estimating
        them would risk breaking admissibility and returning worse routes.
        """
        node_data = self.G.nodes.get(node, {})
        goal_data = self.G.nodes.get(goal, {})
        if "latitude" not in node_data or "latitude" not in goal_data:
            return 0

        from src.data_processing.ner_graph_builder import TIME_REFERENCE_HOURS

        distance_km = self._haversine(
            (node_data["latitude"], node_data["longitude"]),
            (goal_data["latitude"], goal_data["longitude"]),
        )
        best_case_hours = distance_km / HEURISTIC_SPEED_KMH
        normalised_time = min(100.0, (best_case_hours / TIME_REFERENCE_HOURS) * 100.0)
        return self._weight_vector()[0] * normalised_time

    @staticmethod
    def _haversine(a, b):
        lat1, lon1 = map(math.radians, a)
        lat2, lon2 = map(math.radians, b)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6371 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))

    def _weight_vector(self):
        return [self.weights.get(key, 0.0) for key in self.OBJECTIVE_KEYS]

    # ------------------------------------------------------------------ search

    def find_route(self, start, goal, max_hours: float = 1e9):
        """Single best route under the current weight vector.

        Reimplements the outer loop rather than calling MOAStar.moa_star() because the parent
        applies a max_days constraint against raw hours in costs[0]; here costs[0] is a
        *normalised* time score, so the duration limit has to be checked against real hours
        accumulated separately.
        """
        if start not in self.G or goal not in self.G:
            logger.warning(f"Start {start} or goal {goal} not in NER graph.")
            return None

        weights = self._weight_vector()
        zero = tuple(0 for _ in self.OBJECTIVE_KEYS)
        # (f_score, counter, node, path, costs, real_hours, edges)
        counter = 0
        open_set = [(0.0, counter, start, [start], zero, 0.0, [])]
        closed_set = set()
        pareto_frontier: dict = {}

        while open_set:
            f_score, _, current, path, costs, real_hours, edges = heappop(open_set)

            if current == goal:
                return {
                    "path": path,
                    "edges": edges,
                    "costs": self._metrics_dict(costs),
                    "total_hours": round(real_hours, 2),
                    "score": round(sum(w * c for w, c in zip(weights, costs)), 3),
                }

            if current in closed_set:
                continue
            closed_set.add(current)

            for neighbor, edge_dict in self.G[current].items():
                if neighbor in closed_set:
                    continue
                for _, edge_data in edge_dict.items():
                    new_hours = real_hours + edge_data["time"]
                    if new_hours > max_hours:
                        continue

                    new_costs = self._edge_costs(current, neighbor, edge_data, costs, 0)

                    # Pareto pruning — identical strategy to the parent implementation.
                    if neighbor in pareto_frontier:
                        if any(self.dominates(existing, new_costs) for existing in pareto_frontier[neighbor]):
                            continue
                        pareto_frontier[neighbor] = [
                            c for c in pareto_frontier[neighbor] if not self.dominates(new_costs, c)
                        ]
                        pareto_frontier[neighbor].append(new_costs)
                    else:
                        pareto_frontier[neighbor] = [new_costs]

                    g_score = sum(w * c for w, c in zip(weights, new_costs))
                    h_score = self.heuristic(neighbor, goal, weights)
                    counter += 1
                    heappush(
                        open_set,
                        (
                            g_score + h_score,
                            counter,
                            neighbor,
                            path + [neighbor],
                            new_costs,
                            new_hours,
                            edges + [dict(edge_data)],
                        ),
                    )

        logger.info(f"No route found from {start} to {goal} within {max_hours} hours.")
        return None

    def _true_costs(self, route: dict) -> tuple:
        """Recompute a route's objective vector with no search penalties applied.

        Mirrors _edge_costs exactly: sum for time/cost, running maximum (bottleneck) for
        accessibility, risk and reliability.
        """
        totals = [0.0] * len(self.OBJECTIVE_KEYS)
        for edge in route["edges"]:
            totals[0] += edge["obj_time"]
            totals[1] += edge["obj_cost"]
            totals[2] = max(totals[2], edge["obj_accessibility"])
            totals[3] = max(totals[3], edge["obj_risk"])
            totals[4] = max(totals[4], edge["obj_reliability"])
        return tuple(round(v, 3) for v in totals)

    def find_routes(self, start, goal, max_routes: int = 3, max_hours: float = 1e9):
        """Best route plus alternatives, ranked by true score.

        Alternatives are found by adding a penalty to every segment already used, then
        re-searching — so each successive route is pushed onto genuinely different corridors.

        Those penalties distort the scores of the routes they produce, so every route is
        re-scored on the unpenalised graph before ranking. Without this the "alternatives"
        would be ordered by discovery sequence rather than by how good they actually are,
        and a better alternative could be presented below a worse one.
        """
        routes = []
        self._edge_penalties = {}
        try:
            for _ in range(max_routes):
                route = self.find_route(start, goal, max_hours=max_hours)
                if route is None:
                    break
                if any(r["path"] == route["path"] for r in routes):
                    break
                routes.append(route)
                for edge in route["edges"]:
                    segment_id = edge.get("segment_id")
                    if segment_id:
                        self._edge_penalties[segment_id] = self._edge_penalties.get(segment_id, 0.0) + 60.0
        finally:
            self._edge_penalties = {}

        weights = self._weight_vector()
        for route in routes:
            true_costs = self._true_costs(route)
            route["costs"] = self._metrics_dict(true_costs)
            route["score"] = round(sum(w * c for w, c in zip(weights, true_costs)), 3)

        routes.sort(key=lambda r: r["score"])
        return routes


def cheapest_road_mode(weight_kg: float, worst_accessibility: float | None) -> str:
    """The road vehicle class this consignment should actually travel on.

    Picked by real cost for this weight, restricted to classes the weakest segment on the
    route can carry. This is what makes the headline price move with weight instead of
    being a flat per-kilometre figure: a 400 kg load is priced as one pickup, a 12 t load as
    two 9-tonne trucks, and the corridor's condition can rule the big vehicle out entirely.
    """
    floor = 0.0 if worst_accessibility is None else worst_accessibility
    candidates = [
        mid for mid, m in TRANSPORT_MODES.items()
        if m["network"] == "road" and m["min_accessibility"] <= floor
    ]
    if not candidates:
        candidates = ["porter"]
    return min(candidates, key=lambda mid: cost_breakdown(weight_kg, 100.0, mid)["total_inr"])


def build_route_response(
    route: dict, G, cargo_type: str, urgency: str, weight_kg: float = DEFAULT_WEIGHT_KG
) -> dict:
    """Turn a raw route into the API payload, including its explanation."""
    segments = []
    total_distance = 0.0
    total_cost = 0.0
    accessibility_scores = []
    risk_scores = []

    for edge in route["edges"]:
        total_distance += edge["distance"]
        total_cost += edge["monetary_cost_inr"]
        accessibility_scores.append(edge["accessibility_score"])
        risk_scores.append(edge["obj_risk"])
        segments.append({
            "segment_id": edge["segment_id"],
            "highway_corridor": edge["highway_corridor"],
            "road_status": edge["road_status"],
            "distance_km": edge["distance"],
            "travel_time_hours": edge["time"],
            "accessibility_score": edge["accessibility_score"],
            "disruption_risk_percent": edge["obj_risk"],
        })

    node_names = [G.nodes[n].get("name", n) for n in route["path"]]
    worst_accessibility = min(accessibility_scores) if accessibility_scores else None
    avg_accessibility = round(sum(accessibility_scores) / len(accessibility_scores), 2) if accessibility_scores else None
    peak_risk = max(risk_scores) if risk_scores else None
    avg_risk = round(sum(risk_scores) / len(risk_scores), 2) if risk_scores else None

    # Price the consignment properly: fleet-sized, weight-scaled, on a vehicle class the
    # weakest segment of this route can actually carry.
    chosen_mode = cheapest_road_mode(weight_kg, worst_accessibility)
    priced = cost_breakdown(weight_kg, total_distance, chosen_mode)

    return {
        "path": route["path"],
        "path_names": node_names,
        "segments": segments,
        "total_distance_km": round(total_distance, 2),
        "estimated_cost_inr": priced["total_inr"],
        "weight_kg": round(float(weight_kg), 2),
        "priced_mode": chosen_mode,
        "priced_mode_label": TRANSPORT_MODES[chosen_mode]["label"],
        "vehicles_required": priced["vehicles"],
        "cost_breakdown": priced,
        "cost_per_tonne_inr": priced["cost_per_tonne_inr"],
        # Retained so the corridor's raw freight baseline stays visible and comparable
        # across shipments of different sizes.
        "corridor_freight_baseline_inr": round(total_cost, 2),
        "eta_hours": route["total_hours"],
        "eta_days": round(route["total_hours"] / 24, 2),
        "route_score": route["score"],
        "accessibility_score": avg_accessibility,
        "worst_segment_accessibility": worst_accessibility,
        "risk_score": avg_risk,
        "peak_segment_risk_percent": peak_risk,
        "explanation": _explain(
            node_names, segments, cargo_type, urgency, avg_accessibility, worst_accessibility, peak_risk
        ),
    }


def _explain(node_names, segments, cargo_type, urgency, avg_accessibility, worst_accessibility, peak_risk) -> dict:
    """Plain-language reasoning for why this route was recommended.

    Framed as a recommendation with stated caveats — never a guarantee of safe passage.
    """
    priority_order = describe_priority_order(cargo_type, urgency)
    weakest = min(segments, key=lambda s: s["accessibility_score"]) if segments else None
    riskiest = max(segments, key=lambda s: s["disruption_risk_percent"]) if segments else None

    reasons = [
        f"Optimised for '{cargo_type}' cargo at '{urgency}' urgency, which prioritises "
        f"{', then '.join(priority_order[:3])}.",
        f"Route runs {' -> '.join(node_names)} across {len(segments)} road segment(s).",
    ]
    if avg_accessibility is not None:
        reasons.append(f"Average accessibility along the route is {avg_accessibility}/100.")
    if weakest:
        reasons.append(
            f"Weakest link is {weakest['highway_corridor']} (segment {weakest['segment_id']}) at "
            f"{weakest['accessibility_score']}/100 accessibility, status '{weakest['road_status']}'."
        )
    if riskiest and peak_risk is not None:
        reasons.append(
            f"Highest predicted disruption probability on any segment is {peak_risk}% "
            f"({riskiest['highway_corridor']})."
        )

    return {
        "summary": reasons[0],
        "reasons": reasons,
        "priority_order": priority_order,
        "caveat": "This is a model-based recommendation, not a guarantee. Predicted disruption "
                  "probabilities come from a model trained on synthetic data and must be "
                  "confirmed against live ground conditions before operational use.",
    }
