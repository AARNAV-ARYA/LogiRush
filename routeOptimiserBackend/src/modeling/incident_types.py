# src/modeling/incident_types.py
"""
The incident taxonomy — one definition, shared by the database model, the scoring service and
both clients (via GET /api/india/incident-types).

Kept free of SQLAlchemy so the accessibility service can import it without a database driver.

Pan-India additions cover the disruptions other terrains actually produce: snow and avalanches
on the passes, cyclone debris on the coast, waterlogging on the plains and in cities, fog and
heat damage. The original six are unchanged, and in the same order, so every stored report and
every existing client stays valid.
"""

INCIDENT_TYPES = [
    # original NER set
    "landslide", "flood", "road_block", "bridge_damage", "accident", "other",
    # Pan-India additions
    "waterlogging", "snow_blockage", "avalanche", "cyclone_damage", "dense_fog", "heat_damage",
]

INCIDENT_TYPE_LABELS = {
    "landslide": "Landslide",
    "flood": "Flood",
    "road_block": "Road block",
    "bridge_damage": "Bridge damage",
    "accident": "Accident",
    "other": "Other",
    "waterlogging": "Waterlogging",
    "snow_blockage": "Snow blockage",
    "avalanche": "Avalanche",
    "cyclone_damage": "Cyclone / storm debris",
    "dense_fog": "Dense fog",
    "heat_damage": "Heat damage (road surface / vehicles)",
}

# Which natural hazard each type evidences — lets the map colour a report by hazard.
INCIDENT_HAZARD = {
    "landslide": "landslide", "flood": "flood", "waterlogging": "flood",
    "snow_blockage": "snow", "avalanche": "snow", "cyclone_damage": "wind",
    "dense_fog": "fog", "heat_damage": "heat",
}

# A verified report of one of these types at BLOCKING_SEVERITY closes the corridor it was
# attributed to — so verifying one needs a second signature (the two-person rule). Fog and heat
# slow traffic but do not physically block a road; accidents clear within hours.
BLOCKING_INCIDENT_TYPES = frozenset({
    "landslide", "road_block", "bridge_damage", "flood",
    "waterlogging", "snow_blockage", "avalanche", "cyclone_damage",
})
BLOCKING_SEVERITY = 5


def describe_incident_types() -> list:
    return [
        {
            "id": t,
            "label": INCIDENT_TYPE_LABELS.get(t, t),
            "hazard": INCIDENT_HAZARD.get(t),
            "can_close_road": t in BLOCKING_INCIDENT_TYPES,
        }
        for t in INCIDENT_TYPES
    ]
