"""Fetch real road geometry for every corridor from an OSRM routing server.

Run this on a machine with internet access (it could not be run where the Pan-India upgrade
was built). It writes data/raw/india/corridor_geometry.geojson, which the backend picks up
automatically on the next start; delete the file to go back to straight lines.

    cd routeOptimiserBackend
    python tools/fetch_corridor_geometry.py                    # public OSRM demo server
    python tools/fetch_corridor_geometry.py --osrm http://localhost:5000   # your own OSRM
    python tools/fetch_corridor_geometry.py --only IN030,IN033 # a few corridors

Notes
  * The public demo server (router.project-osrm.org) is for light use: this script sends
    one request per second, ~180 requests in total. Please do not run it in a loop; for
    anything regular, run OSRM yourself on the India extract from Geofabrik.
  * OSRM returns the fastest road path between the two town centres. That is usually the
    named highway, but not always — the report lists every corridor whose OSRM distance
    differs from the CSV by more than 25 %, so you can check it (a wrong coordinate, a
    different highway, or a CSV distance worth correcting).
  * Route data (c) OpenStreetMap contributors, ODbL. Keep the attribution.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data_processing.geometry import GEOMETRY_FILE, polyline_length_km, simplify  # noqa: E402
from src.data_processing.india_data_provider import IndiaNetworkProvider  # noqa: E402

USER_AGENT = "LogiRush-India/2.0 (SIH demonstration; corridor geometry, 1 req/s)"


def fetch(osrm: str, a, b, timeout: float = 20.0):
    url = (f"{osrm.rstrip('/')}/route/v1/driving/{a[1]:.5f},{a[0]:.5f};{b[1]:.5f},{b[0]:.5f}"
           "?overview=full&geometries=geojson")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise RuntimeError(payload.get("message") or payload.get("code"))
    route = payload["routes"][0]
    coords = [(c[1], c[0]) for c in route["geometry"]["coordinates"]]
    return coords, route["distance"] / 1000.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--osrm", default="https://router.project-osrm.org")
    parser.add_argument("--only", help="comma-separated segment ids")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--tolerance-km", type=float, default=0.5, help="simplification tolerance")
    parser.add_argument("--out", default=GEOMETRY_FILE)
    args = parser.parse_args()

    provider = IndiaNetworkProvider()
    locations = {l.id: l for l in provider.get_locations()}
    wanted = set(args.only.split(",")) if args.only else None

    features, mismatches, failures = [], [], []
    for segment in provider.get_road_segments():
        if wanted and segment.id not in wanted:
            continue
        a, b = locations[segment.source], locations[segment.destination]
        try:
            coords, km = fetch(args.osrm, (a.latitude, a.longitude), (b.latitude, b.longitude))
        except Exception as e:  # keep going; a missing corridor just stays a straight line
            failures.append((segment.id, str(e)))
            print(f"  {segment.id} FAILED: {e}")
            time.sleep(args.delay)
            continue
        simple = simplify(coords, args.tolerance_km)
        ratio = km / segment.distance_km if segment.distance_km else 1.0
        if abs(ratio - 1.0) > 0.25:
            mismatches.append((segment.id, a.name, b.name, segment.distance_km, round(km, 1)))
        features.append({
            "type": "Feature",
            "properties": {
                "segment_id": segment.id,
                "source": "osrm",
                "road_distance_km": round(km, 1),
                "csv_distance_km": segment.distance_km,
                "vertices": len(simple),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
            "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in simple]},
        })
        print(f"  {segment.id} {a.name} -> {b.name}: {km:.0f} km (CSV {segment.distance_km:.0f}), "
              f"{len(simple)} vertices, polyline {polyline_length_km(simple):.0f} km")
        time.sleep(args.delay)

    collection = {
        "type": "FeatureCollection",
        "attribution": "Route geometry (c) OpenStreetMap contributors, ODbL; routed with OSRM.",
        "features": features,
    }
    if wanted and os.path.exists(args.out):  # merge into the existing file
        with open(args.out, encoding="utf-8") as f:
            existing = json.load(f)
        keep = [f for f in existing.get("features", []) if f["properties"]["segment_id"] not in wanted]
        collection["features"] = keep + features
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(collection, f)

    print(f"\nWrote {len(collection['features'])} corridors to {args.out}")
    if mismatches:
        print("\nCheck these (OSRM distance differs from the CSV by more than 25 %):")
        for m in mismatches:
            print(f"  {m[0]} {m[1]} -> {m[2]}: CSV {m[3]} km, OSRM {m[4]} km")
    if failures:
        print(f"\n{len(failures)} corridor(s) failed and remain straight lines.")


if __name__ == "__main__":
    main()
