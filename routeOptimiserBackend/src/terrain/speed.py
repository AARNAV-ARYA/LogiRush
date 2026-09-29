# src/terrain/speed.py
"""
Terrain-aware travel time and schedule-aware ETA.

The NER prototype estimated time as distance / (30 km/h if the corridor name looked hilly,
else 50 km/h). Across India that is wrong in both directions: a laden truck averages far more
than 50 km/h on the Samruddhi expressway and far less than 30 km/h over Tanglang La. So travel
time is built from what actually governs it:

    base speed        by road class (expressway ... high-altitude pass), for a laden truck
                      including stops — not a posted limit
    gradient          steeper ruling gradient -> slower (gentle, documented curve)
    altitude          above 3,000 m naturally-aspirated diesels lose power
    terrain surface   profile speed_factor (forest tracks, floodplain diversions)
    urban approach    fixed allowance per metro / city endpoint for getting in and out
    live conditions   fog, heavy rain, snow and high wind slow traffic (hazards.weather_speed_factor)

`schedule_eta` then walks a route in order and applies routine movement restrictions — the
Bandipur-Mudumalai night ban, daylight-only convoys on Zojila and the Manali-Leh road — so the
ETA a dispatcher sees includes the night halt the route will actually force.

All constants are planning assumptions, stated here so they can be tuned in one place.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Average laden-truck speed in km/h, including routine stops, by road class.
ROAD_CLASS_SPEED_KMH = {
    "expressway": 60.0,
    "nh_4lane": 50.0,
    "nh_2lane": 40.0,
    "state_highway": 35.0,
    "hill_road": 25.0,
    "high_altitude_pass": 24.0,
}
DEFAULT_SPEED_KMH = 40.0

ROAD_CLASS_LABELS = {
    "expressway": "Expressway",
    "nh_4lane": "National Highway (4+ lane)",
    "nh_2lane": "National Highway (2 lane)",
    "state_highway": "State highway",
    "hill_road": "Hill / ghat road",
    "high_altitude_pass": "High-altitude pass",
}

# Gradient: speed / (1 + GRADIENT_K * max(0, g - GRADIENT_FREE_DEG)).
# The recorded gradient is the corridor's *ruling* (steepest sustained) gradient, which applies
# to part of its length, so the curve is gentle: 25 deg gives ~0.87x, taking a hill road from
# 25 to ~22 km/h — in line with how long NH10 Siliguri-Gangtok takes a laden truck.
GRADIENT_FREE_DEG = 6.0
GRADIENT_K = 0.008

# Altitude: 5 % per 1,000 m above 3,000 m, floored at 0.8.
ALTITUDE_FREE_M = 3000.0
ALTITUDE_LOSS_PER_KM = 0.05

# Hours added for getting through a city at either end of a segment.
URBAN_ALLOWANCE_HOURS = {"metro": 0.75, "city": 0.3, "town": 0.0}

# Default departure hour when a caller gives only a date.
DEFAULT_DEPARTURE_HOUR = 6

IST = timezone(timedelta(hours=5, minutes=30))


def nominal_speed_kmh(road_class: str | None, gradient_deg: float = 0.0,
                      max_elevation_m: float = 0.0, speed_factor: float = 1.0) -> float:
    """Free-flow planning speed for a laden truck on this corridor."""
    speed = ROAD_CLASS_SPEED_KMH.get((road_class or "").strip().lower(), DEFAULT_SPEED_KMH)
    speed /= 1.0 + GRADIENT_K * max(0.0, float(gradient_deg or 0.0) - GRADIENT_FREE_DEG)
    excess_km = max(0.0, float(max_elevation_m or 0.0) - ALTITUDE_FREE_M) / 1000.0
    speed *= max(0.8, 1.0 - ALTITUDE_LOSS_PER_KM * excess_km)
    speed *= float(speed_factor or 1.0)
    return round(speed, 2)


def travel_time_hours(distance_km: float, road_class: str | None, gradient_deg: float = 0.0,
                      max_elevation_m: float = 0.0, speed_factor: float = 1.0,
                      endpoint_classes: tuple = (), condition_factor: float = 1.0) -> float:
    """Hours to traverse the corridor under current conditions."""
    speed = nominal_speed_kmh(road_class, gradient_deg, max_elevation_m, speed_factor)
    speed *= max(0.05, float(condition_factor or 1.0))
    urban = sum(URBAN_ALLOWANCE_HOURS.get(c or "town", 0.0) for c in endpoint_classes)
    return round(float(distance_km) / speed + urban, 2)


# ---------------------------------------------------------------- schedule


def parse_window(window: str | None):
    """'06-18' -> (6, 18). None/'' -> None. Malformed -> None (never blocks a route)."""
    if not window:
        return None
    try:
        start, end = (int(part) for part in str(window).split("-", 1))
    except (TypeError, ValueError):
        return None
    if not (0 <= start < 24 and 0 < end <= 24) or end <= start:
        return None
    return start, end


def parse_departure(value) -> datetime:
    """Departure time as an IST-aware datetime.

    Accepts an ISO date ("2026-01-15" -> 06:00 IST that day), an ISO datetime (naive values
    are read as IST, since that is what an Indian dispatcher types), or None for now.
    """
    if value is None or value == "":
        return datetime.now(IST)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=IST)
    text = str(value).strip().replace("Z", "+00:00")
    if len(text) == 10:
        day = datetime.fromisoformat(text)
        return day.replace(hour=DEFAULT_DEPARTURE_HOUR, tzinfo=IST)
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)


def schedule_eta(legs: list, departure: datetime) -> dict:
    """Walk a route in order and apply routine movement windows.

    `legs` is a list of {"segment_id", "hours", "travel_window", "label"}. On a restricted leg
    a vehicle outside the window waits for it to open; a leg longer than one window's worth of
    driving is split across days with a halt in between (Keylong-Leh is two days for a truck,
    and pretending otherwise produces an ETA nobody can meet).

    Returns arrival time, total elapsed hours, pure driving hours and every halt with its
    reason, so the UI can show *why* the ETA is longer than the driving time.
    """
    now = departure.astimezone(IST)
    halts, driving = [], 0.0

    def wait_until(target: datetime, leg: dict, reason: str):
        nonlocal now
        hours = (target - now).total_seconds() / 3600.0
        if hours > 1e-6:
            halts.append({
                "segment_id": leg.get("segment_id"),
                "at": now.isoformat(),
                "hours": round(hours, 2),
                "reason": reason,
            })
            now = target

    for leg in legs:
        remaining = float(leg.get("hours") or 0.0)
        window = parse_window(leg.get("travel_window"))
        label = leg.get("label") or leg.get("segment_id")
        if window is None:
            now += timedelta(hours=remaining)
            driving += remaining
            continue

        start_h, end_h = window
        window_len = end_h - start_h
        # Safety loop bound: even the longest leg clears in a handful of days.
        for _ in range(30):
            if remaining <= 1e-9:
                break
            open_today = now.replace(hour=start_h, minute=0, second=0, microsecond=0)
            close_today = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                           + timedelta(hours=end_h))
            if now < open_today:
                wait_until(open_today, leg, f"{label}: movement permitted {start_h:02d}:00-{end_h:02d}:00 only")
                continue
            if now >= close_today:
                wait_until(open_today + timedelta(days=1), leg,
                           f"{label}: closed to traffic after {end_h:02d}:00; overnight halt")
                continue
            available = (close_today - now).total_seconds() / 3600.0
            # A leg that fits inside one window is not started unless it can be cleared before
            # closing — convoys are not let onto a pass they cannot get off before dark.
            if remaining <= window_len and remaining > available:
                wait_until(open_today + timedelta(days=1), leg,
                           f"{label}: cannot clear before {end_h:02d}:00; wait for next morning")
                continue
            step = min(remaining, available)
            now += timedelta(hours=step)
            driving += step
            remaining -= step

    elapsed = (now - departure.astimezone(IST)).total_seconds() / 3600.0
    return {
        "departure": departure.astimezone(IST).isoformat(),
        "arrival": now.isoformat(),
        "elapsed_hours": round(elapsed, 2),
        "driving_hours": round(driving, 2),
        "halt_hours": round(sum(h["hours"] for h in halts), 2),
        "halts": halts,
    }
