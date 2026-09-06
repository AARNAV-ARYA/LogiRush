# src/modeling/transport_modes.py
"""
Multimodal Transport Intelligence (SIH Module 4b).

Why this module exists
----------------------
Before this module the platform priced every shipment as `distance_km * flat_rate`, which
meant 100 kg and 10 tonnes of relief material cost exactly the same to move. That is wrong
in an obvious and user-visible way, and it also hid the single most important operational
decision in North East India logistics: *what do you actually move the load on?*

A 500 kg medical consignment to Aizawl and a 20 tonne rice consignment to Aizawl are not the
same problem. The first fits in one pickup that can crawl over a landslide-damaged hill road;
the second needs three 9-tonne trucks that require a corridor those same hills may not offer,
or a rail leg to Silchar plus road for the last stretch.

So cost here is built from three things that all move with weight:

    1. Fleet sizing   - ceil(weight / vehicle capacity) vehicles. This is why cost *steps*:
                        9,000 kg is one truck, 9,010 kg is two, and the price jumps.
    2. Distance cost  - per-vehicle running cost per km (fuel, driver, wear), times fleet size.
    3. Tonnage cost   - per tonne-km haulage plus per-tonne handling at each end.

Every rate below is an indicative planning figure for NER road/rail/water/air freight, not a
quoted tariff. They are deterministic constants so the same input always produces the same
number and the tests can assert on them. Treat them as tunable policy, not measurement.

Feasibility
-----------
Each mode declares `min_accessibility`, the corridor quality it needs. This is what makes
different vehicle classes take *different routes*: a multi-axle truck cannot use a segment
scoring 30/100, so it is routed over a longer but better corridor, while a pickup takes the
direct damaged road. Air and porter modes ignore road accessibility entirely, which is what
makes them the answer for a cut-off village.

Rail, waterway and air additionally require infrastructure at both ends. Those endpoint sets
are curated from real NER infrastructure (NF Railway railheads, National Waterway 2 on the
Brahmaputra, and operating airports/helipads) and are listed explicitly below so a reviewer
can check them rather than trust them.
"""

from __future__ import annotations

import math

# --- Infrastructure endpoints (curated, real NER infrastructure) -----------------------

# NF Railway broad-gauge railheads reachable for freight.
RAILHEADS = {
    "LOC001",  # Siliguri (NJP)
    "LOC002",  # Guwahati
    "LOC004",  # Nagaon (Chaparmukh side)
    "LOC005",  # Jorhat (Mariani)
    "LOC006",  # Dibrugarh
    "LOC007",  # Silchar
    "LOC008",  # North Lakhimpur
    "LOC015",  # Dimapur - the railhead serving Nagaland and Manipur
    "LOC024",  # Agartala
    "LOC026",  # Dharmanagar
    "LOC027",  # Lumding - major junction
    "LOC003",  # Tezpur (Rangapara North)
}

# National Waterway 2: the Brahmaputra, Dhubri to Sadiya. Towns with working river terminals.
RIVER_TERMINALS = {
    "LOC002",  # Guwahati (Pandu)
    "LOC003",  # Tezpur (Silghat)
    "LOC005",  # Jorhat (Neamati)
    "LOC006",  # Dibrugarh (Bogibeel/Oriumghat)
    "LOC008",  # North Lakhimpur (Bhomoraguri bank)
    "LOC021",  # Pasighat (upper Brahmaputra)
}

# Airports and established helipads able to receive relief airlift.
AIRHEADS = {
    "LOC001", "LOC002", "LOC003", "LOC005", "LOC006", "LOC007", "LOC009",
    "LOC011", "LOC012", "LOC014", "LOC015", "LOC016", "LOC019", "LOC020",
    "LOC021", "LOC022", "LOC024",
}

# --- Mode definitions ------------------------------------------------------------------
#
# capacity_kg          payload one vehicle/wagon/sortie can carry
# fixed_inr            dispatch cost per vehicle (booking, positioning, driver mobilisation)
# per_km_inr           running cost per vehicle per km
# per_tonne_km_inr     haulage cost that scales with the load actually carried
# handling_inr_per_t   loading + unloading per tonne, charged once for the whole consignment
# speed_kmph           realistic door-to-door average including terrain, not top speed
# load_hours           fixed time to load, transfer and unload the consignment
# min_accessibility    lowest corridor accessibility score (0-100) the mode can operate on
# network              "road" | "rail" | "water" | "air"  - which distance basis applies
# endpoints            required infrastructure set, or None if it can serve anywhere
# co2_g_per_tonne_km   indicative emissions, for the sustainability readout

TRANSPORT_MODES = {
    "pickup": {
        "label": "Pickup / Tata Ace",
        "category": "Road",
        "capacity_kg": 1000,
        "fixed_inr": 1200.0,
        "per_km_inr": 18.0,
        "per_tonne_km_inr": 2.4,
        "handling_inr_per_t": 350.0,
        "speed_kmph": 38.0,
        "load_hours": 0.75,
        "min_accessibility": 15.0,
        "network": "road",
        "endpoints": None,
        "co2_g_per_tonne_km": 210.0,
        "note": "Smallest road unit. Narrow, steep and partly damaged hill roads stay usable "
                "for it long after larger vehicles are turned back, so it is often the only "
                "wheeled option into interior Mizoram, Manipur and Arunachal.",
    },
    "lcv": {
        "label": "Light commercial vehicle (Bolero / 407)",
        "category": "Road",
        "capacity_kg": 4000,
        "fixed_inr": 2600.0,
        "per_km_inr": 26.0,
        "per_tonne_km_inr": 2.0,
        "handling_inr_per_t": 300.0,
        "speed_kmph": 36.0,
        "load_hours": 1.25,
        "min_accessibility": 28.0,
        "network": "road",
        "endpoints": None,
        "co2_g_per_tonne_km": 155.0,
        "note": "The workhorse of NER district distribution. Good balance of payload and the "
                "ability to handle moderately degraded state highways.",
    },
    "truck": {
        "label": "9-tonne truck",
        "category": "Road",
        "capacity_kg": 9000,
        "fixed_inr": 5200.0,
        "per_km_inr": 41.0,
        "per_tonne_km_inr": 1.55,
        "handling_inr_per_t": 260.0,
        "speed_kmph": 32.0,
        "load_hours": 2.0,
        "min_accessibility": 42.0,
        "network": "road",
        "endpoints": None,
        "co2_g_per_tonne_km": 95.0,
        "note": "Standard bulk road freight. Needs a maintained corridor; it is the first "
                "vehicle class stopped by monsoon damage on secondary hill routes.",
    },
    "multi_axle": {
        "label": "Multi-axle truck (25 t)",
        "category": "Road",
        "capacity_kg": 25000,
        "fixed_inr": 9800.0,
        "per_km_inr": 58.0,
        "per_tonne_km_inr": 1.15,
        "handling_inr_per_t": 230.0,
        "speed_kmph": 28.0,
        "load_hours": 3.0,
        "min_accessibility": 58.0,
        "network": "road",
        "endpoints": None,
        "co2_g_per_tonne_km": 68.0,
        "note": "Cheapest per tonne on good national highway, but the access threshold is "
                "high: it is restricted to well-maintained NH corridors and will be routed "
                "the long way round rather than over a weak hill segment.",
    },
    "rail": {
        "label": "Rail freight (NF Railway)",
        "category": "Rail",
        "capacity_kg": 60000,
        "fixed_inr": 24000.0,
        "per_km_inr": 22.0,
        "per_tonne_km_inr": 0.85,
        "handling_inr_per_t": 620.0,
        "speed_kmph": 34.0,
        "load_hours": 9.0,
        "min_accessibility": 0.0,
        "network": "rail",
        "endpoints": RAILHEADS,
        "co2_g_per_tonne_km": 28.0,
        "note": "By far the cheapest and cleanest per tonne for bulk relief, and unaffected by "
                "road landslides. The catch is that it only runs railhead to railhead, and "
                "wagon placement plus terminal handling adds most of a day.",
    },
    "waterway": {
        "label": "Inland waterway barge (NW2 Brahmaputra)",
        "category": "Waterway",
        "capacity_kg": 120000,
        "fixed_inr": 31000.0,
        "per_km_inr": 15.0,
        "per_tonne_km_inr": 0.70,
        "handling_inr_per_t": 700.0,
        "speed_kmph": 14.0,
        "load_hours": 12.0,
        "min_accessibility": 0.0,
        "network": "water",
        "endpoints": RIVER_TERMINALS,
        "co2_g_per_tonne_km": 22.0,
        "note": "Cheapest heavy option along the Brahmaputra and completely independent of the "
                "road network, which matters when highways are cut. Slow, and river level "
                "and silting make the schedule less dependable than rail.",
    },
    "air_heli": {
        "label": "Helicopter airlift",
        "category": "Air",
        "capacity_kg": 2000,
        "fixed_inr": 185000.0,
        "per_km_inr": 420.0,
        "per_tonne_km_inr": 0.0,
        "handling_inr_per_t": 1500.0,
        "speed_kmph": 190.0,
        "load_hours": 1.0,
        "min_accessibility": 0.0,
        "network": "air",
        "endpoints": AIRHEADS,
        "co2_g_per_tonne_km": 1450.0,
        "note": "Ignores the road network entirely, so it is the only answer when a district "
                "is genuinely cut off. Costs one to two orders of magnitude more per tonne "
                "than road, so it is justified by urgency and isolation, not by economics.",
    },
    "porter": {
        "label": "Porter / mule train (last mile)",
        "category": "Human / animal",
        "capacity_kg": 200,
        "fixed_inr": 900.0,
        "per_km_inr": 46.0,
        "per_tonne_km_inr": 0.0,
        "handling_inr_per_t": 400.0,
        "speed_kmph": 4.0,
        "load_hours": 1.5,
        "min_accessibility": 0.0,
        "network": "road",
        "endpoints": None,
        "co2_g_per_tonne_km": 0.0,
        "note": "Moves where nothing with wheels can, including over a collapsed span or a "
                "blocked cutting. Viable only for small, urgent consignments over short "
                "distances - it is slow and the per-tonne cost climbs steeply with distance.",
    },
}

DEFAULT_MODE = "truck"
DEFAULT_WEIGHT_KG = 1000.0

# Straight-line distance is shorter than the distance actually travelled. These multipliers
# convert great-circle km into a realistic network distance for modes that do not use the
# road graph, so their cost and ETA are not flattering fiction.
NETWORK_DETOUR_FACTOR = {
    "rail": 1.35,   # NER rail alignment follows valleys and doubles back via Lumding
    "water": 1.55,  # the Brahmaputra meanders heavily
    "air": 1.0,     # direct
}


def haversine_km(a: tuple, b: tuple) -> float:
    """Great-circle distance in km between two (lat, lon) pairs."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def vehicles_required(weight_kg: float, mode_id: str) -> int:
    """How many vehicles/wagons/sorties this consignment needs. Never fewer than one."""
    capacity = TRANSPORT_MODES[mode_id]["capacity_kg"]
    return max(1, math.ceil(float(weight_kg) / capacity))


def cost_breakdown(weight_kg: float, distance_km: float, mode_id: str) -> dict:
    """Itemised cost so the UI can explain the number instead of just showing it.

    Total = fleet * (dispatch + running) + tonnage haulage + handling.

    The fleet multiplier is what makes cost step at capacity boundaries, and the tonnage
    and handling terms are what make it move continuously with weight in between. Both
    behaviours are intentional: an operator planning 8.9 t versus 9.1 t genuinely faces a
    different bill, and the platform should show that rather than hide it.
    """
    mode = TRANSPORT_MODES[mode_id]
    tonnes = float(weight_kg) / 1000.0
    fleet = vehicles_required(weight_kg, mode_id)

    dispatch = mode["fixed_inr"] * fleet
    running = mode["per_km_inr"] * float(distance_km) * fleet
    haulage = mode["per_tonne_km_inr"] * tonnes * float(distance_km)
    handling = mode["handling_inr_per_t"] * tonnes

    total = dispatch + running + haulage + handling
    return {
        "dispatch_inr": round(dispatch, 2),
        "running_inr": round(running, 2),
        "haulage_inr": round(haulage, 2),
        "handling_inr": round(handling, 2),
        "total_inr": round(total, 2),
        "vehicles": fleet,
        "cost_per_tonne_inr": round(total / tonnes, 2) if tonnes > 0 else None,
        "cost_per_kg_inr": round(total / float(weight_kg), 2) if weight_kg else None,
    }


def duration_hours(distance_km: float, mode_id: str, road_hours: float | None = None) -> float:
    """Door-to-door hours including loading and transfer.

    For road modes the routing engine already produced a terrain-aware travel time, so that
    is used and merely adjusted for how much slower a heavier vehicle class is. For rail,
    water and air there is no road route, so speed is applied to the mode's own distance.
    """
    mode = TRANSPORT_MODES[mode_id]
    if mode["network"] == "road" and road_hours is not None:
        # road_hours came from the graph at a nominal ~40 kmph reference profile
        scale = 40.0 / mode["speed_kmph"]
        travel = road_hours * scale
    else:
        travel = float(distance_km) / mode["speed_kmph"]
    return round(travel + mode["load_hours"], 2)


def mode_serves(origin_id: str, destination_id: str, mode_id: str) -> bool:
    """Does this mode physically connect these two places?"""
    endpoints = TRANSPORT_MODES[mode_id]["endpoints"]
    if endpoints is None:
        return True
    return origin_id in endpoints and destination_id in endpoints


def infrastructure_gap(origin_id: str, destination_id: str, mode_id: str, name_of) -> str | None:
    """Explain, in operator language, why a mode cannot serve this pair."""
    mode = TRANSPORT_MODES[mode_id]
    endpoints = mode["endpoints"]
    if endpoints is None:
        return None
    missing = [p for p in (origin_id, destination_id) if p not in endpoints]
    if not missing:
        return None
    kind = {"rail": "railhead", "water": "river terminal", "air": "airport or helipad"}[mode["network"]]
    names = " and ".join(name_of(m) for m in missing)
    return f"No {kind} at {names}."


def list_modes() -> list:
    """Rate card for the UI, ordered from lightest to heaviest capacity."""
    out = []
    for mode_id, m in sorted(TRANSPORT_MODES.items(), key=lambda kv: kv[1]["capacity_kg"]):
        out.append({
            "id": mode_id,
            "label": m["label"],
            "category": m["category"],
            "capacity_kg": m["capacity_kg"],
            "speed_kmph": m["speed_kmph"],
            "min_accessibility": m["min_accessibility"],
            "network": m["network"],
            "requires_infrastructure": m["endpoints"] is not None,
            "co2_g_per_tonne_km": m["co2_g_per_tonne_km"],
            "rate_card": {
                "dispatch_per_vehicle_inr": m["fixed_inr"],
                "per_km_per_vehicle_inr": m["per_km_inr"],
                "per_tonne_km_inr": m["per_tonne_km_inr"],
                "handling_per_tonne_inr": m["handling_inr_per_t"],
            },
            "note": m["note"],
        })
    return out


def next_capacity_threshold(weight_kg: float, mode_id: str) -> dict:
    """What happens to this mode's fleet at the next capacity boundary.

    Field planners consolidate loads to avoid paying for a half-empty extra vehicle, so the
    UI surfaces the headroom before the next vehicle is added.
    """
    capacity = TRANSPORT_MODES[mode_id]["capacity_kg"]
    fleet = vehicles_required(weight_kg, mode_id)
    ceiling = capacity * fleet
    return {
        "vehicles": fleet,
        "capacity_kg": ceiling,
        "headroom_kg": round(ceiling - float(weight_kg), 2),
        "next_vehicle_at_kg": ceiling + 1,
    }
