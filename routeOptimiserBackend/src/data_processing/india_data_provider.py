# src/data_processing/india_data_provider.py
"""
Pan-India network provider — the North Eastern network plus the national backbone.

Same public interface as `NERDataProvider` (get_locations / get_road_segments /
get_segment_features / get_segment), so the accessibility service, the graph builder, the
router and the API keep working unchanged. It adds three things the terrain layer needs:

    get_segment_terrain()     terrain class, road class, gradient, elevation, river and coast
                              distance, seasonal closure window, travel window — per corridor
    get_segment_conditions()  the weather inputs every hazard reads: rain, temperature, wind,
                              gusts, snow, visibility
    conditions_status()       where those conditions came from (live / snapshot)

Data layout
-----------
    data/raw/ner/    the original 27 NER nodes and 32 corridors — risk columns unchanged
    data/raw/india/  india_locations.csv       99 backbone nodes (state capitals, freight hubs)
                     india_road_segments.csv   national corridors with terrain attributes
                     ner_segment_terrain.csv   terrain attributes for the 32 NER corridors

What is derived, and how honestly
---------------------------------
The NER corridors keep their hand-authored sample risk values. The national corridors do NOT
get hand-typed risk numbers — typing 146 rows of invented landslide percentages would be worse
than useless. Instead their baseline susceptibilities are *derived* from their recorded
terrain attributes by the documented functions below (steeper -> more landslide-prone, closer
to a river on a floodplain -> more flood-prone). Those attributes are themselves sample values,
so everything here is labelled sample/derived in the provenance manifest, never observed.

The Random Forest's "historical event count" features have no real source for these corridors
either. They are filled with susceptibility PROXIES (see `_model_features`), and the manifest
says so. The model's output on them is a demonstration of the pipeline, not a forecast.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Optional

from src.data_processing.ner_data_provider import Location, MockNERDataProvider, RoadSegment
from src.terrain.profiles import effective_profile
from src.terrain.speed import travel_time_hours

_HERE = os.path.dirname(os.path.abspath(__file__))
INDIA_DATA_DIR = os.path.abspath(os.path.join(_HERE, "..", "..", "data", "raw", "india"))

FAR_KM = 999.0

# Illustrative "ordinary day" conditions per primary terrain, used only when live weather is
# off or unreachable. SYNTHETIC — a neutral backdrop so the offline demo is not all-zero, never
# presented as observed weather. The NER corridors keep their own rainfall snapshot.
TERRAIN_SNAPSHOT = {
    "mountain":      {"rain_24h": 5,  "rain_48h": 10, "tmax_c": 14, "tmin_c": 0,  "wind_kmh": 15, "gust_kmh": 35, "snow_cm": 0, "visibility_m": 10000},
    "hill":          {"rain_24h": 20, "rain_48h": 35, "tmax_c": 24, "tmin_c": 14, "wind_kmh": 12, "gust_kmh": 25, "snow_cm": 0, "visibility_m": 8000},
    "floodplain":    {"rain_24h": 15, "rain_48h": 25, "tmax_c": 33, "tmin_c": 25, "wind_kmh": 10, "gust_kmh": 20, "snow_cm": 0, "visibility_m": 6000},
    "coastal":       {"rain_24h": 12, "rain_48h": 25, "tmax_c": 32, "tmin_c": 26, "wind_kmh": 18, "gust_kmh": 35, "snow_cm": 0, "visibility_m": 9000},
    "arid":          {"rain_24h": 0,  "rain_48h": 2,  "tmax_c": 37, "tmin_c": 24, "wind_kmh": 15, "gust_kmh": 35, "snow_cm": 0, "visibility_m": 10000},
    "plains":        {"rain_24h": 5,  "rain_48h": 10, "tmax_c": 34, "tmin_c": 24, "wind_kmh": 10, "gust_kmh": 20, "snow_cm": 0, "visibility_m": 5000},
    "plateau":       {"rain_24h": 5,  "rain_48h": 12, "tmax_c": 33, "tmin_c": 22, "wind_kmh": 12, "gust_kmh": 25, "snow_cm": 0, "visibility_m": 9000},
    "forest_remote": {"rain_24h": 12, "rain_48h": 25, "tmax_c": 31, "tmin_c": 22, "wind_kmh": 8,  "gust_kmh": 18, "snow_cm": 0, "visibility_m": 8000},
}

# Baseline incident exposure and delay by road class (0-100). Two-lane and hill roads carry
# more crashes, breakdowns and single-lane blockages than divided highways.
ROAD_CLASS_INCIDENT = {"expressway": 5, "nh_4lane": 8, "nh_2lane": 12, "state_highway": 15,
                       "hill_road": 18, "high_altitude_pass": 20}
ROAD_CLASS_DELAY = {"expressway": 8, "nh_4lane": 12, "nh_2lane": 20, "state_highway": 25,
                    "hill_road": 35, "high_altitude_pass": 45}
ROAD_CLASS_VULNERABILITY = {"expressway": 20, "nh_4lane": 30, "nh_2lane": 45, "state_highway": 50,
                            "hill_road": 70, "high_altitude_pass": 80}
URBAN_DELAY = {"metro": 10, "city": 4, "town": 0}

FLOOD_TERRAIN_BASE = {"floodplain": 50, "coastal": 35, "forest_remote": 25, "plains": 20,
                      "plateau": 15, "hill": 15, "arid": 12, "mountain": 8}

# Points sampled along longer corridors for live weather: a 400 km corridor can be dry at one
# end and under a cloudburst at the other, and reading only its midpoint would miss that.
LONG_CORRIDOR_KM = 150.0
SAMPLE_FRACTIONS_LONG = (0.25, 0.5, 0.75)
SAMPLE_FRACTIONS_SHORT = (0.5,)


def _float(value, default=None):
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _flag(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def landslide_susceptibility(attrs: dict) -> float:
    """0-100 static landslide susceptibility from slope and terrain.

    3.2 points per degree of ruling gradient above 5 deg, plus 10 for hill/mountain terrain
    (weathered, fractured slopes above the road as well as below it). A 25 deg hill road lands
    at ~74, near the 80 the NER data assigns NH10.
    """
    gradient = float(attrs.get("ruling_gradient_deg") or 0.0)
    hilly = attrs.get("terrain_class") in ("hill", "mountain")
    value = 3.2 * max(0.0, gradient - 5.0) + (10.0 if hilly else 0.0)
    return round(max(0.0, min(95.0, value)), 1)


def flood_susceptibility(attrs: dict) -> float:
    """0-100 static flood susceptibility from terrain, river proximity and coastal exposure."""
    primary = attrs.get("terrain_class") or "plains"
    secondary = attrs.get("secondary_terrain")
    base = FLOOD_TERRAIN_BASE.get(primary, 20)
    if secondary in FLOOD_TERRAIN_BASE:
        base = 0.7 * base + 0.3 * FLOOD_TERRAIN_BASE[secondary]

    river = attrs.get("river_proximity_km")
    if river is not None:
        if river <= 1:
            base += 20
        elif river <= 3:
            base += 12
        elif river <= 10:
            base += 5

    coast = attrs.get("coast_distance_km")
    if coast is not None and coast <= 2 and (attrs.get("max_elevation_m") or 0) < 30:
        base += 15
    return round(max(0.0, min(95.0, base)), 1)


class IndiaNetworkProvider(MockNERDataProvider):
    """North East + national backbone, with terrain attributes for every corridor."""

    def __init__(self, data_dir: Optional[str] = None, india_dir: Optional[str] = None):
        super().__init__(data_dir)
        self.india_dir = os.path.abspath(india_dir or INDIA_DATA_DIR)
        self._india_locations = None
        self._all_segments = None
        self._terrain = None
        self._all_features = None
        self._snapshot_conditions = None
        self._geometry = None

    # ------------------------------------------------------------------ locations

    def get_locations(self) -> list:
        if self._india_locations is None:
            from src.modeling.transport_modes import (
                AIRHEADS_NER, RAILHEADS_NER, RIVER_TERMINALS_NER, register_infrastructure,
            )

            ner = [
                replace(
                    loc,
                    region="North East",
                    urban_class="city" if loc.id == "LOC002" else "town",
                    railhead=loc.id in RAILHEADS_NER,
                    airport=loc.id in AIRHEADS_NER,
                    river_terminal=loc.id in RIVER_TERMINALS_NER,
                    river_system="NW2" if loc.id in RIVER_TERMINALS_NER else None,
                )
                for loc in super().get_locations()
            ]
            rows = self._read_csv_rows(os.path.join(self.india_dir, "india_locations.csv"))
            india = [
                Location(
                    id=row["id"],
                    name=row["name"],
                    state=row["state"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    district=row["district"],
                    region=row.get("region") or "India",
                    elevation_m=_float(row.get("elevation_m")),
                    urban_class=(row.get("urban_class") or "town").strip().lower(),
                    railhead=_flag(row.get("railhead")),
                    airport=_flag(row.get("airport")),
                    river_terminal=_flag(row.get("river_terminal")),
                    river_system=(row.get("river_system") or "").strip() or None,
                    seaport=_flag(row.get("seaport")),
                )
                for row in rows
            ]
            self._india_locations = ner + india
            # Rail, waterway and air modes now serve the national nodes too.
            register_infrastructure(self._india_locations)
        return self._india_locations

    # ------------------------------------------------------------------ terrain

    def _parse_terrain(self, row: dict) -> dict:
        def far(value):
            number = _float(value)
            return None if number is None or number >= FAR_KM else number

        return {
            "road_class": (row.get("road_class") or "nh_2lane").strip().lower(),
            "terrain_class": (row.get("terrain_class") or "plains").strip().lower(),
            "secondary_terrain": (row.get("secondary_terrain") or "").strip().lower() or None,
            "ruling_gradient_deg": _float(row.get("ruling_gradient_deg"), 0.0),
            "max_elevation_m": _float(row.get("max_elevation_m"), 0.0),
            "river_proximity_km": far(row.get("river_proximity_km")),
            "coast_distance_km": far(row.get("coast_distance_km")),
            "seasonal_closure_months": (row.get("seasonal_closure_months") or "").strip() or None,
            "travel_window": (row.get("travel_window") or "").strip() or None,
            "notes": (row.get("notes") or "").strip() or None,
        }

    def get_segment_terrain(self) -> dict:
        """{segment_id: terrain attributes} for every corridor, plus derived geography."""
        if self._terrain is None:
            terrain = {}
            for row in self._read_csv_rows(os.path.join(self.india_dir, "ner_segment_terrain.csv")):
                terrain[row["segment_id"]] = self._parse_terrain(row)
            for row in self._read_csv_rows(os.path.join(self.india_dir, "india_road_segments.csv")):
                terrain[row["id"]] = self._parse_terrain(row)

            locations = {loc.id: loc for loc in self.get_locations()}
            for segment in self._raw_segments():
                attrs = terrain.setdefault(segment["id"], self._parse_terrain({}))
                source, dest = locations.get(segment["source"]), locations.get(segment["destination"])
                if source and dest:
                    attrs["source_state"] = source.state
                    attrs["destination_state"] = dest.state
                    attrs["region"] = source.region if source.region == dest.region else f"{source.region} / {dest.region}"
                    attrs["midpoint"] = (
                        round((source.latitude + dest.latitude) / 2, 4),
                        round((source.longitude + dest.longitude) / 2, 4),
                    )
                    attrs["endpoint_urban_classes"] = (source.urban_class, dest.urban_class)
            self._terrain = terrain
        return self._terrain

    # ------------------------------------------------------------------ segments

    def _raw_segments(self) -> list:
        """NER rows (as dicts, from the parent's parsed segments) + national rows."""
        rows = [
            {"id": s.id, "source": s.source, "destination": s.destination, "distance_km": s.distance_km,
             "highway_corridor": s.highway_corridor, "road_status": s.road_status,
             "weather_risk": s.weather_risk, "landslide_risk": s.landslide_risk,
             "flood_risk": s.flood_risk, "incident_risk": s.incident_risk,
             "delay_factor": s.delay_factor, "_ner": True}
            for s in MockNERDataProvider.get_road_segments(self)
        ]
        for row in self._read_csv_rows(os.path.join(self.india_dir, "india_road_segments.csv")):
            rows.append({
                "id": row["id"], "source": row["source"], "destination": row["destination"],
                "distance_km": float(row["distance_km"]), "highway_corridor": row["highway_corridor"],
                "road_status": row.get("road_status") or "Open", "_ner": False,
            })
        return rows

    def get_road_segments(self) -> list:
        if self._all_segments is None:
            from src.data_processing.weather_provider import rainfall_to_weather_risk

            terrain = self.get_segment_terrain()
            conditions = self._terrain_snapshot_conditions()
            segments = []
            for row in self._raw_segments():
                attrs = terrain[row["id"]]
                profile = effective_profile(attrs["terrain_class"], attrs["secondary_terrain"])
                hours = travel_time_hours(
                    row["distance_km"], attrs["road_class"], attrs["ruling_gradient_deg"],
                    attrs["max_elevation_m"], profile.speed_factor,
                    attrs.get("endpoint_urban_classes", ()),
                )
                if row["_ner"]:
                    values = {k: row[k] for k in ("weather_risk", "landslide_risk", "flood_risk",
                                                  "incident_risk", "delay_factor")}
                else:
                    cond = conditions[row["id"]]
                    urban = max((URBAN_DELAY.get(c, 0) for c in attrs.get("endpoint_urban_classes", ())), default=0)
                    values = {
                        "weather_risk": rainfall_to_weather_risk(cond["rain_24h"], cond["rain_48h"]),
                        "landslide_risk": landslide_susceptibility(attrs),
                        "flood_risk": flood_susceptibility(attrs),
                        "incident_risk": float(ROAD_CLASS_INCIDENT.get(attrs["road_class"], 12)),
                        "delay_factor": float(min(100, ROAD_CLASS_DELAY.get(attrs["road_class"], 20) + urban)),
                    }
                segments.append(RoadSegment(
                    id=row["id"], source=row["source"], destination=row["destination"],
                    distance_km=row["distance_km"], highway_corridor=row["highway_corridor"],
                    road_status=row["road_status"], travel_time_hours=hours, **values,
                ))
            self._all_segments = segments
        return self._all_segments

    # ------------------------------------------------------------------ conditions & features

    def _terrain_snapshot_conditions(self) -> dict:
        """Snapshot conditions for every corridor (see TERRAIN_SNAPSHOT — synthetic)."""
        if self._snapshot_conditions is None:
            ner_features = MockNERDataProvider.get_segment_features(self)
            out = {}
            for segment_id, attrs in self.get_segment_terrain().items():
                cond = dict(TERRAIN_SNAPSHOT.get(attrs["terrain_class"], TERRAIN_SNAPSHOT["plains"]))
                if segment_id in ner_features:
                    cond["rain_24h"] = ner_features[segment_id].get("rainfall_mm_24h", cond["rain_24h"])
                    cond["rain_48h"] = ner_features[segment_id].get("forecast_rainfall_mm_48h", cond["rain_48h"])
                out[segment_id] = cond
            self._snapshot_conditions = out
        return self._snapshot_conditions

    def get_segment_conditions(self) -> dict:
        """{segment_id: conditions dict}. Copies, so callers may modify them freely."""
        return {k: dict(v) for k, v in self._terrain_snapshot_conditions().items()}

    def conditions_status(self) -> dict:
        return {
            "source": "snapshot",
            "live": False,
            "note": "Illustrative per-terrain snapshot (synthetic). Not observed weather.",
        }

    def _model_features(self, segment_id: str, attrs: dict, cond: dict) -> dict:
        """Random Forest inputs for a national corridor.

        slope, elevation and rainfall are the corridor's own values. The two "historical event"
        features and the vulnerability index have no real source for these corridors, so they
        are PROXIES derived from susceptibility: a corridor derived as 70/100 landslide-prone
        is given 14 "past landslides" on the model's 0-20 scale. This keeps the model's inputs
        coherent with the corridor's terrain; it does not make them historical records.
        """
        return {
            "rainfall_mm_24h": float(cond["rain_24h"]),
            "forecast_rainfall_mm_48h": float(cond["rain_48h"]),
            "slope_gradient_deg": float(attrs["ruling_gradient_deg"]),
            "elevation_m": float(attrs["max_elevation_m"]),
            "historical_landslides_5y": round(landslide_susceptibility(attrs) / 5.0, 1),
            "historical_floods_5y": round(flood_susceptibility(attrs) / 7.0, 1),
            "road_vulnerability_index": float(
                ROAD_CLASS_VULNERABILITY.get(attrs["road_class"], 45)
                + (10 if attrs["terrain_class"] == "forest_remote" else 0)
            ),
        }

    def get_segment_features(self) -> dict:
        if self._all_features is None:
            features = {k: dict(v) for k, v in MockNERDataProvider.get_segment_features(self).items()}
            conditions = self._terrain_snapshot_conditions()
            for segment_id, attrs in self.get_segment_terrain().items():
                if segment_id not in features:
                    features[segment_id] = self._model_features(segment_id, attrs, conditions[segment_id])
            self._all_features = features
        return {k: dict(v) for k, v in self._all_features.items()}

    def get_segment(self, segment_id: str):
        return next((s for s in self.get_road_segments() if s.id == segment_id), None)

    # ------------------------------------------------------------------ geometry

    def get_segment_geometry(self) -> dict:
        """{segment_id: {"coords": [(lat, lon), ...], "source": "osrm" | "straight_line"}}.

        Real road polylines where corridor_geometry.geojson provides them (see
        tools/fetch_corridor_geometry.py), the straight chord between the towns otherwise.
        """
        if self._geometry is None:
            from src.data_processing.geometry import load_geometry

            loaded = load_geometry()
            locations = {loc.id: loc for loc in self.get_locations()}
            geometry = {}
            for segment in IndiaNetworkProvider.get_road_segments(self):
                if segment.id in loaded:
                    geometry[segment.id] = {"coords": loaded[segment.id]["coords"],
                                            "source": loaded[segment.id]["source"]}
                    continue
                a, b = locations.get(segment.source), locations.get(segment.destination)
                if a and b:
                    geometry[segment.id] = {"coords": [(a.latitude, a.longitude), (b.latitude, b.longitude)],
                                            "source": "straight_line"}
            self._geometry = geometry
        return self._geometry

    # ------------------------------------------------------------------ sampling

    def sample_points(self) -> dict:
        """{segment_id: [(lat, lon), ...]} — where live weather is read for each corridor."""
        if getattr(self, "_sample_points", None) is not None:
            return self._sample_points
        from src.data_processing.geometry import points_along

        geometry = self.get_segment_geometry()
        points = {}
        # The base class's segments on purpose: geometry never depends on the weather, and
        # calling the live override from here would recurse into the weather fetch.
        for segment in IndiaNetworkProvider.get_road_segments(self):
            if segment.id not in geometry:
                continue
            fractions = SAMPLE_FRACTIONS_LONG if segment.distance_km > LONG_CORRIDOR_KM else SAMPLE_FRACTIONS_SHORT
            # Along the real road when its geometry is known — the midpoint of a winding
            # Himalayan road's chord can be tens of km from the road itself.
            points[segment.id] = points_along(geometry[segment.id]["coords"], fractions)
        self._sample_points = points
        return points


def _aggregate(readings: list) -> dict:
    """Worst case across a corridor's sample points, variable by variable."""
    out = {}
    rules = {
        "rain_24h": max, "rain_48h": max, "tmax_c": max, "tmin_c": min, "wind_kmh": max,
        "gust_kmh": max, "snow_cm": max, "visibility_m": min,
    }
    for key, pick in rules.items():
        values = [r[key] for r in readings if r.get(key) is not None]
        if values:
            out[key] = pick(values)
    return out


class LiveWeatherIndiaProvider(IndiaNetworkProvider):
    """The Pan-India network with live Open-Meteo conditions substituted in.

    Mirrors LiveWeatherNERDataProvider: same fallback guarantees (any failure leaves the
    snapshot in place), same single-fetch-per-cache-window behaviour, but reads every variable
    the hazard engine needs and samples long corridors at three points instead of one.
    """

    def __init__(self, data_dir: Optional[str] = None, india_dir: Optional[str] = None, provider=None):
        super().__init__(data_dir, india_dir)
        if provider is None:
            from src.data_processing.weather_provider import weather_provider as provider
        self._weather = provider
        self._last_live_count = 0
        self._live_cache = (None, {})

    def _live_by_segment(self) -> dict:
        from src.data_processing.weather_provider import LIVE_ENABLED, _key

        if not LIVE_ENABLED:
            return {}
        points = self.sample_points()
        ordered = sorted({p for pts in points.values() for p in pts})
        if not ordered:
            return {}
        snapshot = self._weather.get(ordered)
        if not snapshot.readings:
            return {}
        # One aggregation per fetched snapshot: conditions, features and segments all ask.
        if self._live_cache[0] is snapshot:
            return self._live_cache[1]
        out = {}
        for segment_id, pts in points.items():
            readings = [snapshot.readings[_key(*p)] for p in pts if _key(*p) in snapshot.readings]
            if readings:
                out[segment_id] = _aggregate(readings)
        self._last_live_count = len(out)
        self._live_cache = (snapshot, out)
        return out

    def get_segment_conditions(self) -> dict:
        conditions = super().get_segment_conditions()
        for segment_id, live in self._live_by_segment().items():
            if segment_id in conditions:
                conditions[segment_id].update(live)
                conditions[segment_id]["_live"] = True
        return conditions

    def get_segment_features(self) -> dict:
        features = super().get_segment_features()
        for segment_id, live in self._live_by_segment().items():
            if segment_id in features and "rain_24h" in live:
                features[segment_id]["rainfall_mm_24h"] = live["rain_24h"]
                features[segment_id]["forecast_rainfall_mm_48h"] = live.get("rain_48h", 0.0)
        return features

    def get_road_segments(self) -> list:
        from src.data_processing.weather_provider import rainfall_to_weather_risk

        segments = super().get_road_segments()
        live = self._live_by_segment()
        if not live:
            return segments
        return [
            replace(s, weather_risk=rainfall_to_weather_risk(live[s.id].get("rain_24h", 0.0),
                                                             live[s.id].get("rain_48h", 0.0)))
            if s.id in live and "rain_24h" in live[s.id] else s
            for s in segments
        ]

    def conditions_status(self) -> dict:
        from src.data_processing.weather_provider import weather_provider

        status = weather_provider.status()
        live = status.get("state") == "live"
        return {
            "source": "live" if live else "snapshot",
            "live": live,
            "corridors_live": self._last_live_count,
            "weather": status,
            "note": ("Live Open-Meteo model data (NOT an IMD product) for rain, temperature, "
                     "wind, snow and visibility." if live else
                     "Live weather unavailable — illustrative per-terrain snapshot (synthetic)."),
        }

    def weather_status(self) -> dict:
        from src.data_processing.weather_provider import weather_provider

        return weather_provider.status()
