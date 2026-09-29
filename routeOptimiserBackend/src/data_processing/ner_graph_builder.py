# src/data_processing/ner_graph_builder.py
"""
Builds the NER road network graph used by risk-aware routing (SIH Module 3).

Deliberately SEPARATE from GraphBuilder (the global seaport/airport cross-border graph).
The two model different things — one is intercontinental multi-modal freight, the other is
domestic road accessibility during disasters — and the existing cross-border graph is left
completely untouched.

Every edge carries five normalised, "lower is better" objective costs on a 0-100 scale so
the router's weight vector is meaningful. Normalisation constants are documented below;
without normalisation a cost in rupees (tens of thousands) would swamp an accessibility
penalty (0-100) no matter what weights were chosen.

Impassable segments (closed roads, verified severe blocking incidents) are simply not added
as edges — the router then physically cannot route through them, which is stronger and more
honest than assigning them a large penalty and hoping.
"""

from __future__ import annotations

import logging

import networkx as nx

from src.services.accessibility_service import AccessibilityService

logger = logging.getLogger("ner_graph_builder")

# ---- Normalisation references (documented, tunable, deterministic) ----
# A segment taking this long is scored 100 on the time objective.
TIME_REFERENCE_HOURS = 12.0
# A segment costing this much (INR) is scored 100 on the cost objective.
COST_REFERENCE_INR = 30000.0
# Indicative road freight rate used to derive segment cost from distance.
FREIGHT_RATE_INR_PER_KM = 45.0


class NERGraphBuilder:
    def __init__(self, service: AccessibilityService | None = None):
        self.service = service or AccessibilityService()

    @staticmethod
    def _normalise(value: float, reference: float) -> float:
        return round(min(100.0, max(0.0, (value / reference) * 100.0)), 2)

    @staticmethod
    def _normalise_additive(value: float, reference: float) -> float:
        """Like _normalise but without the 100 ceiling, for additive objectives on the
        Pan-India network. A 20-hour Himalayan leg is not "the same" as a 12-hour one; capping
        it would let the router treat Keylong-Leh as no slower than Delhi-Jaipur-and-back."""
        return round(max(0.0, (value / reference) * 100.0), 2)

    @staticmethod
    def _reliability_penalty(segment: dict) -> float:
        """0-100 penalty capturing how much this road can be *depended on*.

        Distinct from risk (which is about future disruption probability) and from
        accessibility (current condition). Reliability is about consistency: a road under
        repair or with a history of incidents may be passable today but is a poor bet for a
        shipment that must arrive.
        """
        status_penalty = {
            "open": 0,
            "partially blocked": 35,
            "under repair": 30,
            "closed": 100,
        }.get(segment["road_status"].strip().lower(), 20)

        delay_component = segment["risk_inputs"]["delay_risk"] * 0.5
        incident_component = min(40.0, segment["active_incident_count"] * 12.0)
        # Terrain's own dependability penalty (sparse alternates, long service gaps) on the
        # Pan-India network; absent -> 0 on the original NER network.
        terrain_component = float(segment.get("reliability_extra") or 0.0)
        return round(min(100.0, status_penalty + delay_component + incident_component + terrain_component), 2)

    def build(self, assessed_segments: list | None = None) -> nx.MultiDiGraph:
        if assessed_segments is None:
            assessed_segments = self.service.assess_all_segments()

        G = nx.MultiDiGraph()

        for location in self.service.provider.get_locations():
            G.add_node(
                location.id,
                name=location.name,
                state=location.state,
                district=location.district,
                latitude=location.latitude,
                longitude=location.longitude,
            )

        skipped = 0
        for seg in assessed_segments:
            if seg["impassable"]:
                skipped += 1
                logger.info(f"Segment {seg['id']} excluded from graph: impassable ({seg['road_status']}).")
                continue

            travel_time = seg["travel_time_hours"]
            monetary_cost = seg["distance_km"] * FREIGHT_RATE_INR_PER_KM
            terrain_aware = "hazards" in seg
            if terrain_aware:
                # Pan-India: the multi-hazard index for the corridor's own terrain.
                disruption_pct = float(seg["multi_hazard_index"])
            else:
                disruption_pct = (
                    seg["prediction"]["combined_disruption_probability"] * 100.0
                    if seg.get("prediction") else 0.0
                )
            normalise_time = self._normalise_additive if terrain_aware else self._normalise

            attrs = {
                "segment_id": seg["id"],
                "mode": "road",
                "highway_corridor": seg["highway_corridor"],
                "road_status": seg["road_status"],
                "distance": seg["distance_km"],
                "time": travel_time,
                "monetary_cost_inr": round(monetary_cost, 2),
                "accessibility_score": seg["accessibility_score"],
                # --- normalised objective costs, all 0-100, lower is better ---
                "obj_time": normalise_time(travel_time, TIME_REFERENCE_HOURS),
                "obj_cost": normalise_time(monetary_cost, COST_REFERENCE_INR),
                "obj_accessibility": round(100.0 - seg["accessibility_score"], 2),
                "obj_risk": round(disruption_pct, 2),
                "obj_reliability": self._reliability_penalty(seg),
            }
            if terrain_aware:
                terrain = seg.get("terrain") or {}
                attrs.update({
                    "terrain_class": terrain.get("class"),
                    "secondary_terrain": terrain.get("secondary"),
                    "road_class": terrain.get("road_class"),
                    "travel_window": terrain.get("travel_window"),
                    "max_elevation_m": terrain.get("max_elevation_m"),
                    "source_name": seg.get("source_name"),
                    "destination_name": seg.get("destination_name"),
                    # Per-hazard risks and relevance let the router recompute the risk
                    # objective with a cargo's own sensitivities (perishables and heat).
                    "hazard_risks": {h: v["risk"] for h, v in seg["hazards"].items() if v["risk"] is not None},
                    "hazard_relevance": dict(seg.get("hazard_relevance") or {}),
                    "dominant_hazard": seg.get("dominant_hazard"),
                    "simulated": seg.get("simulated", False),
                    "condition_slowdowns": seg.get("condition_slowdowns") or [],
                })

            # Roads are bidirectional; add both directions with identical attributes.
            G.add_edge(seg["source"], seg["destination"], **attrs)
            G.add_edge(seg["destination"], seg["source"], **attrs)

        logger.info(
            f"NER graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges "
            f"({skipped} segments excluded as impassable)."
        )
        return G
