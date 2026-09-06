# src/data_processing/ner_data_provider.py
"""
NER (North Eastern Region) data provider — adapter layer.

IMPORTANT: `MockNERDataProvider` below is a MOCK / SAMPLE data source. It reads the
illustrative CSVs in data/raw/ner/ (see the header comments in those files for exactly
what is real vs. synthetic). It exists so the rest of the platform — the Accessibility
Intelligence Engine, Risk-Aware Routing, the dashboard/map APIs — can be built and tested
now, against the same interface a real integration would use later.

To integrate real data (IMD weather, GSI landslide susceptibility, CWC flood data, state
PWD road status feeds, etc.), implement a new class with the same public methods as
`NERDataProvider` (get_locations / get_road_segments / get_segment) and swap it in at the
call site — nothing in accessibility_engine.py or the API layer needs to change.

Do not present data returned by MockNERDataProvider as real government data anywhere in
the UI or docs — always label it as sample/demo data until a real provider is wired in.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field, replace
from typing import Optional


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    state: str
    latitude: float
    longitude: float
    district: str


@dataclass(frozen=True)
class RoadSegment:
    id: str
    source: str
    destination: str
    distance_km: float
    highway_corridor: str
    road_status: str
    weather_risk: float
    landslide_risk: float
    flood_risk: float
    incident_risk: float
    delay_factor: float
    # travel_time_hours is derived (see NERDataProvider._estimate_travel_time), not stored raw.
    travel_time_hours: float = field(default=0.0)


class NERDataProvider:
    """Abstract-ish base: defines the interface real providers should implement."""

    def get_locations(self) -> list[Location]:
        raise NotImplementedError

    def get_road_segments(self) -> list[RoadSegment]:
        raise NotImplementedError

    def get_segment(self, segment_id: str) -> Optional[RoadSegment]:
        raise NotImplementedError

    def get_segment_features(self) -> dict:
        """Terrain/weather/history features per segment, keyed by segment id.

        Feeds the Disaster Prediction Engine (Module 2). A real implementation would source
        rainfall from a live weather API, slope/elevation from a DEM, and event history from
        official disaster records.
        """
        raise NotImplementedError


class MockNERDataProvider(NERDataProvider):
    """Loads the sample NER CSVs shipped in data/raw/ner/. See module docstring."""

    # Hill-vs-plains speed assumption used only to derive a plausible travel_time from
    # distance for this sample dataset — a real provider would source travel time from
    # actual traffic/road data instead of estimating it.
    _HILL_CORRIDOR_HINTS = ("NH10", "NH29", "NH40", "NH306", "NH54", "NH302", "SH")
    _HILL_SPEED_KMH = 30
    _PLAINS_SPEED_KMH = 50

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw", "ner"
            )
        self.data_dir = os.path.abspath(data_dir)
        self._locations: Optional[list[Location]] = None
        self._segments: Optional[list[RoadSegment]] = None
        self._segment_features: Optional[dict] = None

    @staticmethod
    def _read_csv_rows(path: str) -> list[dict]:
        with open(path, newline="", encoding="utf-8") as f:
            # Skip leading '#' comment/documentation lines before the header row.
            lines = [line for line in f if not line.lstrip().startswith("#")]
        return list(csv.DictReader(lines))

    def _estimate_travel_time(self, distance_km: float, highway_corridor: str) -> float:
        is_hill = any(hint in highway_corridor for hint in self._HILL_CORRIDOR_HINTS)
        speed = self._HILL_SPEED_KMH if is_hill else self._PLAINS_SPEED_KMH
        return round(distance_km / speed, 2)

    def get_locations(self) -> list[Location]:
        if self._locations is None:
            rows = self._read_csv_rows(os.path.join(self.data_dir, "ner_locations.csv"))
            self._locations = [
                Location(
                    id=row["id"],
                    name=row["name"],
                    state=row["state"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    district=row["district"],
                )
                for row in rows
            ]
        return self._locations

    def get_road_segments(self) -> list[RoadSegment]:
        if self._segments is None:
            rows = self._read_csv_rows(os.path.join(self.data_dir, "ner_road_segments.csv"))
            segments = []
            for row in rows:
                distance_km = float(row["distance_km"])
                highway_corridor = row["highway_corridor"]
                segments.append(
                    RoadSegment(
                        id=row["id"],
                        source=row["source"],
                        destination=row["destination"],
                        distance_km=distance_km,
                        highway_corridor=highway_corridor,
                        road_status=row["road_status"],
                        weather_risk=float(row["weather_risk"]),
                        landslide_risk=float(row["landslide_risk"]),
                        flood_risk=float(row["flood_risk"]),
                        incident_risk=float(row["incident_risk"]),
                        delay_factor=float(row["delay_factor"]),
                        travel_time_hours=self._estimate_travel_time(distance_km, highway_corridor),
                    )
                )
            self._segments = segments
        return self._segments

    def get_segment_features(self) -> dict:
        """Load ner_segment_features.csv into {segment_id: {feature: float}}.

        Returns an empty dict if the file is absent, so the platform still runs (the
        prediction engine falls back to neutral defaults) rather than failing hard.
        """
        if self._segment_features is None:
            path = os.path.join(self.data_dir, "ner_segment_features.csv")
            if not os.path.exists(path):
                self._segment_features = {}
                return self._segment_features
            rows = self._read_csv_rows(path)
            features = {}
            for row in rows:
                segment_id = row.pop("segment_id")
                features[segment_id] = {k: float(v) for k, v in row.items() if v != ""}
            self._segment_features = features
        return self._segment_features

    def get_segment(self, segment_id: str) -> Optional[RoadSegment]:
        return next((s for s in self.get_road_segments() if s.id == segment_id), None)

    def get_location(self, location_id: str) -> Optional[Location]:
        return next((l for l in self.get_locations() if l.id == location_id), None)


class LiveWeatherNERDataProvider(MockNERDataProvider):
    """The sample network, with its rainfall and weather risk replaced by live readings.

    This is the seam the original module docstring promised: "implement a new class with the
    same public methods and swap it in at the call site — nothing in accessibility_engine.py
    or the API layer needs to change." It turned out to be true, which is the useful thing to
    record. Nothing below this class knows the weather became real.

    What changes, and what does not:

        rainfall_mm_24h            live      summed precipitation over the last 24 h
        forecast_rainfall_mm_48h   live      summed precipitation over the next 48 h
        weather_risk               live      deterministic IMD-band ladder over the two above
        landslide/flood/incident   sample    unchanged; these need GSI, CWC and a PWD feed
        terrain, history           sample    unchanged
        corridors, distances       sample    unchanged

    So this makes a quarter of the accessibility score and the model's two strongest features
    real. It does not make the platform's risk data real, and the provenance manifest keeps
    saying so for everything still on the CSV — moving one input to live is only worth doing
    if the others stay honestly labelled.

    A corridor is read at its **midpoint**, not its endpoints: a segment is up to 600 km long,
    and the rain that closes it is the rain falling on it rather than in the city it ends at.

    Every override degrades to the parent's CSV values when the network is unavailable, so
    the platform is never worse off than before this class existed.
    """

    def __init__(self, data_dir: Optional[str] = None, provider=None):
        super().__init__(data_dir)
        if provider is None:
            from src.data_processing.weather_provider import weather_provider as provider
        self._weather = provider

    # ------------------------------------------------------------------ geometry

    def _segment_midpoints(self) -> dict:
        """{segment_id: (lat, lon)} at the middle of each corridor.

        A straight-line midpoint, deliberately: the corridor geometry here is a pair of
        endpoints, so pretending to more precision than that would be invented. It is far
        closer to the affected stretch than either endpoint, which is the point.
        """
        locations = {loc.id: loc for loc in self.get_locations()}
        midpoints = {}
        for segment in super().get_road_segments():
            source, destination = locations.get(segment.source), locations.get(segment.destination)
            if not source or not destination:
                continue
            midpoints[segment.id] = (
                (source.latitude + destination.latitude) / 2,
                (source.longitude + destination.longitude) / 2,
            )
        return midpoints

    def _live_rainfall(self) -> dict:
        """{segment_id: {"rain_24h": mm, "rain_48h": mm}} — empty when unavailable."""
        from src.data_processing.weather_provider import LIVE_ENABLED, _key

        if not LIVE_ENABLED:
            return {}

        midpoints = self._segment_midpoints()
        if not midpoints:
            return {}

        ordered = list(midpoints.items())
        snapshot = self._weather.get([coords for _, coords in ordered])
        if not snapshot.readings:
            return {}

        return {
            segment_id: snapshot.readings[_key(*coords)]
            for segment_id, coords in ordered
            if _key(*coords) in snapshot.readings
        }

    # ------------------------------------------------------------------ overrides

    def get_segment_features(self) -> dict:
        """Sample terrain and history, with real rainfall substituted in."""
        features = {k: dict(v) for k, v in super().get_segment_features().items()}
        for segment_id, rain in self._live_rainfall().items():
            if segment_id in features:
                features[segment_id]["rainfall_mm_24h"] = rain["rain_24h"]
                features[segment_id]["forecast_rainfall_mm_48h"] = rain["rain_48h"]
        return features

    def get_road_segments(self) -> list[RoadSegment]:
        """Sample corridors, with weather_risk recomputed from the live rainfall.

        Without this the map would keep colouring corridors by a hand-typed weather number
        while the model underneath used real rain — the two halves of the same screen
        disagreeing about the weather, which is worse than either alone.
        """
        from src.data_processing.weather_provider import rainfall_to_weather_risk

        segments = super().get_road_segments()
        rainfall = self._live_rainfall()
        if not rainfall:
            return segments

        updated = []
        for segment in segments:
            rain = rainfall.get(segment.id)
            if rain is None:
                updated.append(segment)
                continue
            updated.append(replace(
                segment,
                weather_risk=rainfall_to_weather_risk(rain["rain_24h"], rain["rain_48h"]),
            ))
        return updated

    def weather_status(self) -> dict:
        from src.data_processing.weather_provider import weather_provider

        return weather_provider.status()
