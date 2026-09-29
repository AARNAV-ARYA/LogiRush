# src/terrain/scenarios.py
"""
SIMULATED disruption scenarios — for demonstration and controlled testing only.

A scenario replaces the weather inputs of the corridors it covers with the conditions of a
plausible extreme event (a cyclone landfall, a desert heatwave, a snowstorm on the passes) and
leaves every other corridor on its real or snapshot data. It exists for two reasons:

  * To show, on demand, that the terrain engine responds the way each region needs: the same
    request routes differently when the Odisha coast is under a cyclone or the Gangetic plain
    is under fog. Waiting for the real event is not a demo strategy.
  * To test routing under controlled disruption, which the project brief asks for explicitly.

Everything produced under a scenario is labelled `simulated: true` at the corridor and the
response level, and the web console shows a SIMULATION banner. A scenario must never be
presented as a live condition. Historical references are for scale only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Zone:
    """Which corridors a scenario touches, and what conditions it imposes on them.

    A corridor matches when every given filter matches. `states` matches if either endpoint is
    in one of the states; `bbox` (min_lat, min_lon, max_lat, max_lon) matches on the corridor
    midpoint; `terrains` matches the primary or secondary terrain.
    """

    conditions: dict
    states: tuple = ()
    bbox: tuple | None = None
    terrains: tuple = ()
    max_coast_km: float | None = None
    min_elevation_m: float | None = None


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    hazard: str
    description: str
    reference: str
    zones: tuple = field(default_factory=tuple)


SCENARIOS = {
    s.id: s for s in (
        Scenario(
            id="cyclone_odisha",
            label="Cyclone landfall — Odisha coast",
            hazard="wind",
            description="A very severe cyclonic storm crossing the Odisha coast near Puri: "
                        "~140 km/h sustained winds and extremely heavy rain on the coastal belt, "
                        "heavy rain inland.",
            reference="Comparable in scale to Cyclone Fani (2019).",
            zones=(
                Zone(bbox=(18.5, 83.5, 22.5, 88.0), max_coast_km=60,
                     conditions={"wind_kmh": 140, "gust_kmh": 185, "rain_24h": 240, "rain_48h": 180}),
                Zone(bbox=(18.0, 82.5, 23.0, 88.5), max_coast_km=300,
                     conditions={"wind_kmh": 65, "gust_kmh": 95, "rain_24h": 150, "rain_48h": 120}),
            ),
        ),
        Scenario(
            id="heatwave_northwest",
            label="Severe heatwave — Rajasthan and the north-west",
            hazard="heat",
            description="Severe heatwave over the Thar and the north-western plains: 47-48 C in "
                        "western Rajasthan, 45-46 C across Delhi, Haryana, Punjab and Gujarat.",
            reference="Churu recorded 50.8 C in June 2019.",
            zones=(
                Zone(states=("Rajasthan",), terrains=("arid",),
                     conditions={"tmax_c": 48.0, "gust_kmh": 75}),
                Zone(states=("Rajasthan", "Delhi", "Haryana", "Punjab", "Gujarat", "Uttar Pradesh"),
                     conditions={"tmax_c": 45.5}),
            ),
        ),
        Scenario(
            id="himalayan_snowstorm",
            label="Heavy snowfall — Kashmir, Ladakh and Lahaul",
            hazard="snow",
            description="A strong western disturbance dumps 40+ cm of snow on the high passes "
                        "(Zojila, Baralacha La, Tanglang La) with sub-zero temperatures.",
            reference="Typical of early-winter western disturbances.",
            zones=(
                Zone(states=("Jammu and Kashmir", "Ladakh", "Himachal Pradesh"), min_elevation_m=2500,
                     conditions={"snow_cm": 45, "tmin_c": -12, "tmax_c": -2, "gust_kmh": 70,
                                 "visibility_m": 300}),
            ),
        ),
        Scenario(
            id="bihar_floods",
            label="Monsoon floods — North Bihar (Kosi / Gandak)",
            hazard="flood",
            description="Days of very heavy rain over the Kosi, Gandak and Bagmati catchments; "
                        "embankments under pressure across north Bihar.",
            reference="Comparable to the 2008 Kosi breach season.",
            zones=(
                Zone(states=("Bihar",), terrains=("floodplain",),
                     conditions={"rain_24h": 180, "rain_48h": 260}),
            ),
        ),
        Scenario(
            id="igp_fog",
            label="Dense fog — Indo-Gangetic plain",
            hazard="fog",
            description="A December night of very dense fog from Punjab to Bihar: visibility "
                        "below 50 m on NH44, NH19 and the expressways.",
            reference="Recurring every winter.",
            zones=(
                Zone(states=("Punjab", "Haryana", "Delhi", "Uttar Pradesh", "Bihar", "Chandigarh"),
                     terrains=("plains", "floodplain"),
                     conditions={"visibility_m": 30, "tmax_c": 16, "tmin_c": 6}),
            ),
        ),
        Scenario(
            id="western_ghats_monsoon",
            label="Monsoon burst — Western Ghats and Konkan",
            hazard="landslide",
            description="An active monsoon surge: 240 mm in a day along the Konkan and Malabar "
                        "coasts and the ghat sections, with slope failures on the ghat roads.",
            reference="Comparable to the July 2021 Konkan rains (Taliye landslide).",
            zones=(
                Zone(states=("Maharashtra", "Goa", "Karnataka", "Kerala"), terrains=("hill", "coastal"),
                     conditions={"rain_24h": 240, "rain_48h": 320, "wind_kmh": 45, "gust_kmh": 70}),
            ),
        ),
        Scenario(
            id="ner_landslides",
            label="Extreme rain — North East hills",
            hazard="landslide",
            description="Extremely heavy rain over Meghalaya, Manipur, Mizoram and Nagaland; "
                        "widespread slides on the hill highways.",
            reference="Comparable to the June 2022 North East rains.",
            zones=(
                Zone(states=("Meghalaya", "Manipur", "Mizoram", "Nagaland", "Assam", "Tripura",
                             "Arunachal Pradesh", "Sikkim"), terrains=("hill",),
                     conditions={"rain_24h": 220, "rain_48h": 260}),
            ),
        ),
    )
}


def get_scenario(scenario_id: str | None) -> Scenario | None:
    """None for no scenario. Raises ValueError for an unknown id, so a typo is a 400."""
    if scenario_id in (None, "", "none", "live"):
        return None
    scenario = SCENARIOS.get(str(scenario_id).strip())
    if scenario is None:
        raise ValueError(f"Unknown scenario '{scenario_id}'. Known: {', '.join(SCENARIOS)}")
    return scenario


def _zone_matches(zone: Zone, corridor: dict) -> bool:
    if zone.states and not ({corridor.get("source_state"), corridor.get("destination_state")} & set(zone.states)):
        return False
    if zone.terrains and not ({corridor.get("terrain_class"), corridor.get("secondary_terrain")} & set(zone.terrains)):
        return False
    if zone.bbox is not None:
        lat, lon = corridor.get("midpoint") or (None, None)
        if lat is None:
            return False
        min_lat, min_lon, max_lat, max_lon = zone.bbox
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            return False
    if zone.max_coast_km is not None:
        coast = corridor.get("coast_distance_km")
        if coast is None or coast > zone.max_coast_km:
            return False
    if zone.min_elevation_m is not None:
        if (corridor.get("max_elevation_m") or 0) < zone.min_elevation_m:
            return False
    return True


def apply_scenario(scenario: Scenario | None, corridor: dict, conditions: dict) -> tuple:
    """Return (conditions, applied) for one corridor. The first matching zone wins."""
    if scenario is None:
        return conditions, False
    for zone in scenario.zones:
        if _zone_matches(zone, corridor):
            merged = dict(conditions)
            merged.update(zone.conditions)
            return merged, True
    return conditions, False


def list_scenarios() -> list:
    return [
        {
            "id": s.id,
            "label": s.label,
            "hazard": s.hazard,
            "description": s.description,
            "reference": s.reference,
            "simulated": True,
        }
        for s in SCENARIOS.values()
    ]
