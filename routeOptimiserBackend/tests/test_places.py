# tests/test_places.py
"""Place search, including the OpenStreetMap parsing.

The remote services cannot be reached from CI or from a sandbox, so the parsing is exercised
against recorded response shapes instead. That is the part most likely to be silently wrong:
a mis-read field does not raise, it just returns nothing, and "no results" looks identical to
"nothing nearby".
"""

import pytest

from src.services import places_service
from src.services.places_service import OSMPlaceProvider, PlacesService


class _Loc:
    def __init__(self, id, name, state, district, lat, lon):
        self.id, self.name, self.state, self.district = id, name, state, district
        self.latitude, self.longitude = lat, lon


class _Provider:
    def get_locations(self):
        return [
            _Loc("LOC002", "Guwahati", "Assam", "Kamrup Metropolitan", 26.1445, 91.7362),
            _Loc("LOC007", "Silchar", "Assam", "Cachar", 24.8333, 92.7789),
            _Loc("LOC001", "Siliguri", "West Bengal", "Darjeeling", 26.7271, 88.3953),
        ]


# Shapes copied from the documented Photon (GeoJSON) and Overpass (JSON) formats.
PHOTON = {
    "type": "FeatureCollection",
    "features": [
        {
            "geometry": {"type": "Point", "coordinates": [91.7500, 26.1800]},
            "properties": {
                "osm_id": 12345, "osm_type": "N", "name": "Paltan Bazaar",
                "city": "Guwahati", "district": "Kamrup Metropolitan",
                "state": "Assam", "country": "India",
            },
        },
        # no name at all — must be skipped, not emitted as a blank suggestion
        {
            "geometry": {"type": "Point", "coordinates": [92.0, 26.0]},
            "properties": {"osm_id": 999, "osm_type": "N", "state": "Assam"},
        },
    ],
}

OVERPASS = {
    "version": 0.6,
    "elements": [
        {
            "type": "node", "id": 1, "lat": 26.1800, "lon": 91.7500,
            "tags": {
                "amenity": "post_office", "name": "Guwahati Head Post Office",
                "phone": "+91 361 254 0021", "addr:street": "Panbazar",
                "addr:city": "Guwahati", "opening_hours": "Mo-Sa 10:00-17:00",
            },
        },
        {
            # a way, so coordinates arrive under "center" rather than lat/lon
            "type": "way", "id": 2, "center": {"lat": 26.1500, "lon": 91.7300},
            "tags": {"amenity": "bus_station", "name": "ISBT Guwahati", "operator": "ASTC"},
        },
        {  # unnamed — skipped
            "type": "node", "id": 3, "lat": 26.16, "lon": 91.74,
            "tags": {"amenity": "fuel"},
        },
    ],
}


def test_local_search_ranks_prefix_matches_first():
    service = PlacesService(_Provider())
    results = service.local.search("sil")
    names = [r["name"] for r in results]
    assert names[:2] == ["Silchar", "Siliguri"], names
    assert all(r["routable"] for r in results)


def test_local_search_matches_district_and_state():
    service = PlacesService(_Provider())
    assert any(r["name"] == "Silchar" for r in service.local.search("cachar"))


def test_photon_parsing(monkeypatch):
    monkeypatch.setattr(places_service, "_get_json", lambda *a, **k: PHOTON)
    places_service._cache = places_service._TTLCache()

    results = OSMPlaceProvider().search("paltan")
    assert len(results) == 1, "the unnamed feature must be dropped"
    hit = results[0]
    assert hit["name"] == "Paltan Bazaar"
    assert (hit["latitude"], hit["longitude"]) == (26.18, 91.75), "GeoJSON is lon,lat — not lat,lon"
    assert hit["routable"] is False, "an OSM place is not a corridor node"
    assert "Guwahati" in hit["label"]


def test_overpass_parsing_and_absent_phone(monkeypatch):
    monkeypatch.setattr(places_service, "_get_json", lambda *a, **k: OVERPASS)
    places_service._cache = places_service._TTLCache()

    facilities = OSMPlaceProvider().nearby_facilities(26.1445, 91.7362, radius_km=6)
    names = [f["name"] for f in facilities]
    assert "Guwahati Head Post Office" in names
    assert "ISBT Guwahati" in names, "a 'way' element carries coordinates under center"
    assert len(facilities) == 2, "the unnamed fuel station must be dropped"

    post = next(f for f in facilities if f["name"].startswith("Guwahati Head"))
    assert post["phone"] == "+91 361 254 0021", "phone is passed through verbatim"
    assert post["kind"] == "Post office"
    assert post["address"] == "Panbazar, Guwahati"

    # The rule that matters: no contact detail is ever synthesised.
    isbt = next(f for f in facilities if f["name"] == "ISBT Guwahati")
    assert isbt["phone"] is None, "a facility with no OSM phone tag must report None"

    assert facilities == sorted(facilities, key=lambda f: f["distance_km"])


def test_search_degrades_to_local_when_osm_is_down(monkeypatch):
    """A geocoder having a bad day must never stop someone planning a convoy."""
    def boom(*a, **k):
        raise TimeoutError("photon unreachable")

    monkeypatch.setattr(places_service, "_get_json", boom)
    places_service._cache = places_service._TTLCache()

    payload = PlacesService(_Provider()).search("sil")
    assert payload["degraded"] is True
    assert [r["name"] for r in payload["results"]][:2] == ["Silchar", "Siliguri"]


def test_remote_results_never_shadow_a_routable_node(monkeypatch):
    duplicate = {
        "type": "FeatureCollection",
        "features": [{
            "geometry": {"type": "Point", "coordinates": [91.7362, 26.1445]},
            "properties": {"osm_id": 5, "osm_type": "N", "name": "Guwahati", "state": "Assam"},
        }],
    }
    monkeypatch.setattr(places_service, "_get_json", lambda *a, **k: duplicate)
    places_service._cache = places_service._TTLCache()

    results = PlacesService(_Provider()).search("guwahati")["results"]
    guwahatis = [r for r in results if r["name"] == "Guwahati"]
    assert len(guwahatis) == 1
    assert guwahatis[0]["routable"] is True, "the routable node must win the duplicate"


def test_off_network_point_snaps_to_nearest_node():
    """A place OSM knows but the graph does not still has to be usable as an origin."""
    resolved = PlacesService(_Provider()).resolve(26.30, 91.50)
    assert resolved["origin"]["name"] == "Guwahati"
    assert resolved["origin"]["distance_km"] > 0


def test_cache_prevents_a_request_per_keystroke(monkeypatch):
    calls = {"n": 0}

    def counted(*a, **k):
        calls["n"] += 1
        return PHOTON

    monkeypatch.setattr(places_service, "_get_json", counted)
    places_service._cache = places_service._TTLCache()

    provider = OSMPlaceProvider()
    provider.search("paltan")
    provider.search("paltan")
    assert calls["n"] == 1, "a repeated query must be served from cache, not re-requested"
