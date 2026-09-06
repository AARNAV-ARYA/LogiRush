# src/services/accessibility_service.py
"""
Composition layer: turns raw segment data + ML predictions + live community incidents into
the accessibility picture the rest of the platform consumes.

This is where the modules meet, and it is deliberately the ONLY place they meet:

    ner_data_provider  (raw sample/real data)
    disaster_prediction (Module 2, ML — future probabilities)
    incidents in DB     (Module 5, community reports)
                |
                v
    accessibility_service  <-- blends inputs, applies deterministic business rules
                |
                v
    accessibility_engine (Module 1, pure deterministic formula)

accessibility_engine never imports the ML model, and the ML model never sees an accessibility
score. Business rules (road closures, impassability) are deterministic and live here, per the
AI Usage Policy.

Every blend below is an explicit, documented rule so a judge can follow exactly how a
probability became a score. None of it is learned.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.data_processing.ner_data_provider import LiveWeatherNERDataProvider, MockNERDataProvider
from src.modeling.accessibility_engine import assess_segment
from src.modeling.disaster_prediction import get_default_predictor

logger = logging.getLogger("accessibility_service")

# How recent a community report must be to still influence risk.
INCIDENT_WINDOW_DAYS = 7
# How close (km) an incident must be to a segment for its proximity to raise that segment's
# risk. Deliberately tight: a report near a junction should not light up every road around it.
INCIDENT_ATTRIBUTION_RADIUS_KM = 12.0

# How close (km) the NEAREST corridor must be for a report to be filed against it at all.
#
# Corridors are modelled as straight chords between towns, but the roads they stand for wind
# through hills, so a genuine roadside report can sit well off the chord — hence a radius
# wider than the risk radius above. Beyond it there is no corridor to speak of, and the
# report is recorded at its own coordinates with no segment attached.
#
# Without this cap `nearest segment` means *nearest on the whole planet*: a report filed from
# Mumbai lands on a corridor in Assam 1,700 km away, shows up as that corridor's problem on
# the map, and — because an explicitly attributed report bypasses the risk radius below —
# could close a highway nobody involved has ever driven.
INCIDENT_SNAP_RADIUS_KM = 30.0

# Deterministic delay penalties added on top of a segment's baseline delay_factor.
ROAD_STATUS_DELAY_PENALTY = {
    "open": 0,
    "partially blocked": 20,
    "under repair": 15,
    "closed": 100,
}

# Road statuses that make a segment impassable for routing purposes (business rule, not ML).
IMPASSABLE_STATUSES = {"closed"}

# A verified incident of one of these types at this severity or above closes the segment.
BLOCKING_INCIDENT_TYPES = {"landslide", "road_block", "bridge_damage", "flood"}
BLOCKING_SEVERITY = 5


def _haversine_km(a: tuple, b: tuple) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _point_to_segment_km(point: tuple, seg_start: tuple, seg_end: tuple) -> float:
    """Approximate distance from a point to a road segment (treated as a straight line).

    Uses a local equirectangular projection, which is accurate enough at NER segment scale
    (tens to a few hundred km) and far cheaper than a geodesic solve. Real road geometry is a
    polyline, not a straight line, so this is an approximation — with real GIS road geometry
    this function is where you'd swap in a proper nearest-point-on-polyline query.
    """
    lat0 = math.radians((seg_start[0] + seg_end[0]) / 2)
    kx = 111.320 * math.cos(lat0)  # km per degree longitude at this latitude
    ky = 110.574  # km per degree latitude

    px, py = point[1] * kx, point[0] * ky
    ax, ay = seg_start[1] * kx, seg_start[0] * ky
    bx, by = seg_end[1] * kx, seg_end[0] * ky

    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)

    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def default_provider():
    """The data provider the platform runs on.

    Live rainfall when it is available, the shipped snapshot otherwise — and the choice is
    made here, once, rather than by each caller. `LiveWeatherNERDataProvider` already falls
    back to the CSV on any network failure, so this is safe to default on; a demonstration
    that quietly ran on snapshot data because nobody exported a variable is the failure worth
    designing against.

    Tests pin the snapshot explicitly (NER_LIVE_WEATHER=0), because a suite whose numbers
    depend on this afternoon's weather in Meghalaya is not a suite.
    """
    from src.data_processing.weather_provider import LIVE_ENABLED

    return LiveWeatherNERDataProvider() if LIVE_ENABLED else MockNERDataProvider()


class AccessibilityService:
    def __init__(self, provider=None, predictor=None):
        self.provider = provider or default_provider()
        # Predictor is lazy: constructing it may train models, which we don't want to pay
        # for on import or on requests that never need a prediction.
        self._predictor = predictor
        self._predictor_initialised = predictor is not None

    @property
    def predictor(self):
        if not self._predictor_initialised:
            self._predictor = get_default_predictor()
            self._predictor_initialised = True
        return self._predictor

    # ------------------------------------------------------------------ incidents

    def _load_recent_incidents(self) -> list:
        """Fetch recent incidents from the DB. Returns [] if the DB isn't reachable.

        Graceful degradation is deliberate (spec: "Reliability: graceful degradation during
        data outages") — a database problem must not take accessibility scoring offline.
        """
        try:
            from src.db.models import Incident
            from src.db.session import get_session

            cutoff = datetime.now(timezone.utc) - timedelta(days=INCIDENT_WINDOW_DAYS)
            session = get_session()
            try:
                # Only statuses that still bear on the road. Filtering by an explicit
                # "these count" set rather than "everything except rejected" is what lets a
                # resolved landslide reopen its corridor the moment it is cleared, instead
                # of waiting out the seven-day window — and it means a new terminal status
                # added later is inert by default rather than silently affecting routing.
                from src.db.models import ACTIVE_STATUSES

                rows = (
                    session.query(Incident)
                    .filter(Incident.verification_status.in_(tuple(ACTIVE_STATUSES)))
                    .all()
                )
                recent = []
                for r in rows:
                    reported = r.reported_at
                    if reported is None:
                        continue
                    if reported.tzinfo is None:
                        reported = reported.replace(tzinfo=timezone.utc)
                    if reported >= cutoff:
                        recent.append(r)
                return recent
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"Could not load incidents ({e}); continuing with zero incident pressure.")
            return []

    def _incident_pressure(self, segment, locations_by_id, incidents) -> dict:
        """Attribute nearby incidents to a segment and convert them into a 0-100 risk figure.

        Rule: each attributed incident contributes severity x 6 points (so a severity-5 report
        contributes 30), capped at 100. Verified reports count fully; unverified ones count at
        60%, so unconfirmed crowd reports still register but can't single-handedly close a
        corridor before a human verifies them.

        Closure is deliberately NARROWER than risk attribution. A nearby incident raises risk
        on every road within the attribution radius, but only closes the ONE segment it was
        actually attributed to at ingest (incident.segment_id). Without that distinction a
        single landslide reported near a junction would close every road within 12 km, which
        is both wrong and dangerous — it would strand a region the moment one report lands.
        """
        source = locations_by_id.get(segment.source)
        dest = locations_by_id.get(segment.destination)
        if not source or not dest:
            return {"incident_risk": 0.0, "count": 0, "blocking": False, "incidents": []}

        seg_start = (source.latitude, source.longitude)
        seg_end = (dest.latitude, dest.longitude)

        attributed, score, blocking = [], 0.0, False
        for inc in incidents:
            distance_km = _point_to_segment_km((inc.latitude, inc.longitude), seg_start, seg_end)
            # An explicit attribution reaches further than plain proximity — that is the
            # point of it — but not without limit. Rows written before the snap radius
            # existed can carry an attribution from anywhere, and one of those must not be
            # able to close a corridor now.
            explicit_match = (
                inc.segment_id == segment.id and distance_km <= INCIDENT_SNAP_RADIUS_KM
            )
            if not explicit_match and distance_km > INCIDENT_ATTRIBUTION_RADIUS_KM:
                continue

            weight = 1.0 if inc.verification_status == "verified" else 0.6
            score += inc.severity * 6 * weight
            attributed.append({
                "id": inc.id,
                "type": inc.incident_type,
                "severity": inc.severity,
                "verification_status": inc.verification_status,
                "distance_km": round(distance_km, 2),
            })
            if (
                explicit_match  # only the segment this incident was attributed to can close
                and inc.verification_status == "verified"
                and inc.severity >= BLOCKING_SEVERITY
                and inc.incident_type in BLOCKING_INCIDENT_TYPES
            ):
                blocking = True

        return {
            "incident_risk": round(min(100.0, score), 2),
            "count": len(attributed),
            "blocking": blocking,
            "incidents": attributed,
        }

    # ------------------------------------------------------------------ blending

    @staticmethod
    def _effective_weather_risk(baseline: float, features: dict) -> float:
        """Blend the segment's baseline weather risk with current rainfall conditions.

        Rule: rainfall component = forecast 48h rainfall scaled so 260mm (the top of the
        plausible range) maps to 100. Take the higher of baseline and rainfall component, so
        an unusually wet forecast can raise risk on a normally-calm corridor but a calm
        forecast never masks a corridor's known baseline exposure.

        Note on live rainfall. When the live provider is active, `baseline` is itself derived
        from the same measurement, through IMD's published rainfall bands (see
        weather_provider.rainfall_to_weather_risk). So this max() is then between two
        mappings of one number rather than between a static value and a live one — not a
        double count, and the stricter of the two wins. In practice the IMD ladder dominates,
        which is the intended outcome: published bands are a better-defended mapping than
        "260 mm is 100". The scaling here stays as the floor for the snapshot case, where
        `baseline` really is a hand-authored constant.
        """
        rain_component = min(100.0, (features.get("forecast_rainfall_mm_48h", 0) / 260.0) * 100.0)
        return round(max(baseline, rain_component), 2)

    @staticmethod
    def _blend_predicted(baseline: float, probability: float) -> float:
        """Blend static susceptibility with the model's forecast probability, 50/50.

        Baseline captures "this corridor is historically fragile"; the prediction captures
        "conditions right now are dangerous". Both matter, neither should dominate, so an
        even split is the honest default — and it's a single constant to tune later against
        real outcome data.
        """
        return round(0.5 * baseline + 0.5 * (probability * 100.0), 2)

    def _segment_features(self, segment, feature_rows: dict, incident_count: int) -> dict:
        raw = feature_rows.get(segment.id, {})
        return {
            "rainfall_mm_24h": raw.get("rainfall_mm_24h", 0.0),
            "forecast_rainfall_mm_48h": raw.get("forecast_rainfall_mm_48h", 0.0),
            "slope_gradient_deg": raw.get("slope_gradient_deg", 5.0),
            "elevation_m": raw.get("elevation_m", 100.0),
            "historical_landslides_5y": raw.get("historical_landslides_5y", 0.0),
            "historical_floods_5y": raw.get("historical_floods_5y", 0.0),
            "road_vulnerability_index": raw.get("road_vulnerability_index", 40.0),
            "recent_incident_count": float(incident_count),
        }

    # ------------------------------------------------------------------ public API

    def assess_all_segments(self, include_prediction: bool = True) -> list:
        """Return every segment enriched with accessibility, risk and traversability.

        This is the single source of truth used by the dashboard, the map and the router,
        so all three always agree on what the network currently looks like.
        """
        segments = self.provider.get_road_segments()
        locations_by_id = {loc.id: loc for loc in self.provider.get_locations()}
        feature_rows = self.provider.get_segment_features()
        incidents = self._load_recent_incidents()

        # Pressure and features first for the whole network, then ONE model call for all of
        # it. Predicting segment by segment paid scikit-learn's fixed per-call cost 32 times
        # over and made the map, the dashboard and every route plan wait about a second on
        # arithmetic that takes milliseconds.
        pressures = [
            self._incident_pressure(segment, locations_by_id, incidents) for segment in segments
        ]
        feature_sets = [
            self._segment_features(segment, feature_rows, pressure["count"])
            for segment, pressure in zip(segments, pressures)
        ]
        predictions = (
            self.predictor.predict_many(feature_sets)
            if include_prediction and feature_sets
            else [None] * len(segments)
        )

        results = []
        for segment, pressure, features, prediction in zip(
            segments, pressures, feature_sets, predictions
        ):
            landslide_risk = segment.landslide_risk
            flood_risk = segment.flood_risk
            if prediction is not None:
                landslide_risk = self._blend_predicted(
                    segment.landslide_risk, prediction.landslide_probability
                )
                flood_risk = self._blend_predicted(segment.flood_risk, prediction.flood_probability)

            weather_risk = self._effective_weather_risk(segment.weather_risk, features)

            status_key = segment.road_status.strip().lower()
            delay_risk = min(100.0, segment.delay_factor + ROAD_STATUS_DELAY_PENALTY.get(status_key, 0))

            incident_risk = max(segment.incident_risk, pressure["incident_risk"])

            assessment = assess_segment(
                weather_risk=weather_risk,
                landslide_risk=landslide_risk,
                flood_risk=flood_risk,
                incident_risk=incident_risk,
                delay_risk=delay_risk,
            )

            impassable = status_key in IMPASSABLE_STATUSES or pressure["blocking"]
            score = 0.0 if impassable else assessment.score

            source = locations_by_id.get(segment.source)
            destination = locations_by_id.get(segment.destination)

            results.append({
                "id": segment.id,
                "source": segment.source,
                "destination": segment.destination,
                "source_name": source.name if source else None,
                "destination_name": destination.name if destination else None,
                "source_state": source.state if source else None,
                "source_coords": [source.latitude, source.longitude] if source else None,
                "destination_coords": [destination.latitude, destination.longitude] if destination else None,
                "distance_km": segment.distance_km,
                "travel_time_hours": segment.travel_time_hours,
                "highway_corridor": segment.highway_corridor,
                "road_status": segment.road_status,
                "impassable": impassable,
                "accessibility_score": score,
                "accessibility_category": "Critical" if impassable else assessment.category,
                "risk_inputs": {
                    "weather_risk": weather_risk,
                    "landslide_risk": landslide_risk,
                    "flood_risk": flood_risk,
                    "incident_risk": incident_risk,
                    "delay_risk": delay_risk,
                },
                "prediction": {
                    "flood_probability": prediction.flood_probability,
                    "landslide_probability": prediction.landslide_probability,
                    "combined_disruption_probability": prediction.combined_disruption_probability,
                    "model_type": prediction.model_type,
                    "top_drivers": prediction.top_drivers,
                } if prediction else None,
                "active_incidents": pressure["incidents"],
                "active_incident_count": pressure["count"],
            })

        return results

    def get_segment_assessment(self, segment_id: str) -> Optional[dict]:
        return next((s for s in self.assess_all_segments() if s["id"] == segment_id), None)

    def nearest_segment(self, latitude: float, longitude: float):
        """Which corridor a point belongs to, and how far off it is.

        Returns `(segment_id, distance_km)`, or `(None, distance_km)` when the nearest
        corridor is beyond `INCIDENT_SNAP_RADIUS_KM` — a point in the middle of the Bay of
        Bengal has a nearest NER corridor in the same sense that it has a nearest bus stop,
        and saying so would be worse than saying nothing.

        Deterministic geometry, no ML, per the AI Usage Policy.
        """
        locations = {loc.id: loc for loc in self.provider.get_locations()}
        best_id, best_distance = None, float("inf")
        for segment in self.provider.get_road_segments():
            source = locations.get(segment.source)
            destination = locations.get(segment.destination)
            if not source or not destination:
                continue
            distance = _point_to_segment_km(
                (latitude, longitude),
                (source.latitude, source.longitude),
                (destination.latitude, destination.longitude),
            )
            if distance < best_distance:
                best_id, best_distance = segment.id, distance

        if best_id is None:
            return None, None
        distance_km = round(best_distance, 2)
        if best_distance > INCIDENT_SNAP_RADIUS_KM:
            return None, distance_km
        return best_id, distance_km
