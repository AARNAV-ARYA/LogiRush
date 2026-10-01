# tests/test_geometry.py
"""Real road geometry: loaded when present, straight chords when not, and used for matching."""

import json
import os
import tempfile

import pytest

from src.data_processing import geometry as geo
from src.data_processing.india_data_provider import IndiaNetworkProvider
from src.services.accessibility_service import AccessibilityService

KEYLONG = (32.5714, 77.0325)
LEH = (34.1526, 77.5771)
BEND = (33.3, 77.9)  # a road that swings well east of the chord


@pytest.fixture
def geometry_file(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), "corridor_geometry.geojson")
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "properties": {"segment_id": "IN030", "source": "osrm", "road_distance_km": 470},
            "geometry": {"type": "LineString",
                         "coordinates": [[p[1], p[0]] for p in (KEYLONG, BEND, LEH)]},
        }]}, f)
    monkeypatch.setenv("LOGIRUSH_GEOMETRY_FILE", path)
    return path


def test_missing_file_means_straight_lines(monkeypatch):
    monkeypatch.setenv("LOGIRUSH_GEOMETRY_FILE", "/nonexistent/geometry.geojson")
    geometry = IndiaNetworkProvider().get_segment_geometry()
    assert all(g["source"] == "straight_line" and len(g["coords"]) == 2 for g in geometry.values())


def test_geometry_file_is_loaded_and_flipped_to_lat_lon(geometry_file):
    geometry = IndiaNetworkProvider().get_segment_geometry()
    assert geometry["IN030"]["source"] == "osrm"
    assert geometry["IN030"]["coords"][1] == BEND
    assert geometry["IN001"]["source"] == "straight_line"


def test_a_report_on_the_bend_is_matched_to_the_real_road(geometry_file):
    service = AccessibilityService(provider=IndiaNetworkProvider())
    segment_id, distance = service.nearest_segment(*BEND)
    assert segment_id == "IN030" and distance < 1.0
    # The same point is far from the straight chord.
    assert geo.point_to_chord_km(BEND, KEYLONG, LEH) > 25


def test_weather_is_sampled_on_the_road_not_the_chord(geometry_file):
    points = IndiaNetworkProvider().sample_points()["IN030"]
    assert min(geo.point_to_polyline_km(p, [KEYLONG, BEND, LEH]) for p in points) < 0.5
    assert max(geo.point_to_chord_km(p, KEYLONG, LEH) for p in points) > 10


def test_assessed_segments_carry_their_geometry(geometry_file):
    assessed = {s["id"]: s for s in AccessibilityService(provider=IndiaNetworkProvider()).assess_all_segments(month=7)}
    assert assessed["IN030"]["geometry_source"] == "osrm" and len(assessed["IN030"]["geometry"]) == 3
    assert assessed["IN001"]["geometry_source"] == "straight_line"


def test_simplify_keeps_endpoints_and_drops_collinear_points():
    line = [(20.0, 78.0 + i * 0.01) for i in range(50)]
    simple = geo.simplify(line, tolerance_km=0.1)
    assert simple[0] == line[0] and simple[-1] == line[-1] and len(simple) == 2


def test_points_along_hits_the_ends():
    pts = geo.points_along([KEYLONG, BEND, LEH], (0.0, 1.0))
    assert pts[0] == (round(KEYLONG[0], 4), round(KEYLONG[1], 4))
    assert pts[1] == (round(LEH[0], 4), round(LEH[1], 4))
