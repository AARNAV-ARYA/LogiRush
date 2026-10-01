# src/data_processing/geometry.py
"""
Corridor geometry — real road shapes instead of straight chords between towns.

The corridor CSVs record only endpoints, so until now every corridor was drawn, matched to
incident reports and sampled for weather as a straight line. For a 360 km Himalayan road that
winds through two passes, the chord can sit 40 km from the actual road.

This module loads an optional GeoJSON of real road polylines
(`data/raw/india/corridor_geometry.geojson`, produced by `tools/fetch_corridor_geometry.py`
from OpenStreetMap routing) and provides the polyline geometry helpers used by the provider
and the accessibility service. When the file is absent, or a corridor is missing from it,
everything falls back to the straight chord and says so (`geometry_source: "straight_line"`).
"""

from __future__ import annotations

import json
import math
import os

GEOMETRY_FILE = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw", "india", "corridor_geometry.geojson"
))


def load_geometry(path: str | None = None) -> dict:
    """{segment_id: {"coords": [(lat, lon), ...], "source": str, "road_distance_km": float|None}}."""
    path = path or os.environ.get("LOGIRUSH_GEOMETRY_FILE") or GEOMETRY_FILE
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        segment_id = props.get("segment_id")
        coords = geom.get("coordinates") or []
        if not segment_id or geom.get("type") != "LineString" or len(coords) < 2:
            continue
        out[segment_id] = {
            # GeoJSON is (lon, lat); everything else in the platform is (lat, lon).
            "coords": [(round(float(c[1]), 5), round(float(c[0]), 5)) for c in coords],
            "source": props.get("source", "file"),
            "road_distance_km": props.get("road_distance_km"),
        }
    return out


def _local_xy(point, lat0):
    kx = 111.320 * math.cos(math.radians(lat0))
    return point[1] * kx, point[0] * 110.574


def point_to_chord_km(point, a, b) -> float:
    """Distance (km) from a point to the straight segment a-b (local equirectangular)."""
    lat0 = (a[0] + b[0]) / 2
    px, py = _local_xy(point, lat0)
    ax, ay = _local_xy(a, lat0)
    bx, by = _local_xy(b, lat0)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def point_to_polyline_km(point, coords) -> float:
    """Shortest distance (km) from a point to a polyline of (lat, lon) vertices."""
    if len(coords) < 2:
        return point_to_chord_km(point, coords[0], coords[0]) if coords else float("inf")
    return min(point_to_chord_km(point, a, b) for a, b in zip(coords, coords[1:]))


def _haversine_km(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def polyline_length_km(coords) -> float:
    return sum(_haversine_km(a, b) for a, b in zip(coords, coords[1:]))


def points_along(coords, fractions) -> list:
    """Points at the given fractions (0..1) of a polyline's length."""
    if not coords:
        return []
    if len(coords) < 2:
        return [tuple(coords[0])] * len(fractions)
    legs = [_haversine_km(a, b) for a, b in zip(coords, coords[1:])]
    total = sum(legs) or 1e-9
    out = []
    for f in fractions:
        target, walked, point = f * total, 0.0, None
        for (a, b), leg in zip(zip(coords, coords[1:]), legs):
            if walked + leg >= target:
                t = 0.0 if leg == 0 else max(0.0, min(1.0, (target - walked) / leg))
                point = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                break
            walked += leg
        point = point or coords[-1]  # rounding at f == 1.0
        out.append((round(point[0], 4), round(point[1], 4)))
    return out


def simplify(coords, tolerance_km: float = 0.5) -> list:
    """Douglas-Peucker simplification, tolerance in km. Keeps the endpoints."""
    if len(coords) <= 2:
        return list(coords)
    keep = [False] * len(coords)
    keep[0] = keep[-1] = True
    stack = [(0, len(coords) - 1)]
    while stack:
        i, j = stack.pop()
        best, index = 0.0, None
        for k in range(i + 1, j):
            d = point_to_chord_km(coords[k], coords[i], coords[j])
            if d > best:
                best, index = d, k
        if index is not None and best > tolerance_km:
            keep[index] = True
            stack.extend([(i, index), (index, j)])
    return [c for c, k in zip(coords, keep) if k]
