"""Place search: autocomplete, and the logistics facilities near a place.

Why this exists
---------------
Until now a consignment could only start and end at one of 28 named corridor nodes. A trader
in Nagaon does not think in corridor nodes — they think "I'm in Nagaon, near the bus stand,
and I need this in Aizawl". This module closes that gap: free-text search over real places,
and the actual facilities near them from which goods can be handed over, with a phone number
where one is publicly recorded.

Design
------
Two providers behind one interface, queried in that order:

  LocalPlaceProvider   the 28 corridor nodes shipped with the project. Instant, offline,
                       always available, and the only results that are directly routable.
  OSMPlaceProvider     Photon for geocoding and Overpass for nearby facilities. Real places,
                       real contact details, no API key.

Local always answers first and never waits on the network. That ordering is not a performance
nicety — this is a disaster-logistics tool, and a third-party geocoder having a bad day must
never be able to stop someone planning a relief convoy. Every remote call is time-boxed,
cached, and failure-tolerant: on error the caller still gets the local results with a flag
saying enrichment was unavailable.

On phone numbers
----------------
Contact details come from OpenStreetMap's `phone`/`contact:phone` tags and are passed through
verbatim. Where OSM records none, the field is null and the interface says "not listed". No
contact detail is ever synthesised — a fabricated number attached to a real-sounding cargo
operator is worse than an absent one, because someone will dial it.

OSM data is ODbL-licensed and requires attribution; every response carries the attribution
string, and the UI displays it.
"""

import json
import logging
import math
import os
import threading
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

PHOTON_URL = os.environ.get("PHOTON_URL", "https://photon.komoot.io/api")
OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

# Photon and Overpass are volunteer-run. A courteous client identifies itself, caches hard and
# gives up quickly; the alternative is getting the whole project's IP range blocked mid-demo.
USER_AGENT = os.environ.get(
    "OSM_USER_AGENT",
    "NER-Smart-Logistics/1.0 (SIH demonstration project; contact via repository)",
)
REMOTE_TIMEOUT_S = float(os.environ.get("PLACES_TIMEOUT_S", "4.0"))
CACHE_TTL_S = int(os.environ.get("PLACES_CACHE_TTL_S", "900"))

OSM_ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"

# The eight NER states plus the Siliguri corridor, as a bounding box. Photon is global, and a
# trader searching "Jorhat" does not want Jorhat, Iran — constraining the box is what makes
# the suggestions feel local rather than merely correct.
NER_BBOX = {"min_lon": 87.5, "min_lat": 21.5, "max_lon": 97.5, "max_lat": 29.6}
NER_CENTER = (25.8, 92.5)

# What counts as somewhere you can hand over cargo. Deliberately broad: in much of the region
# the practical parcel point is a bus stand counter or a fuel station on the highway, not a
# purpose-built freight terminal.
FACILITY_QUERIES = [
    ('amenity', 'post_office',        'Post office'),
    ('office', 'logistics',           'Logistics office'),
    ('shop', 'courier',               'Courier'),
    ('amenity', 'parcel_locker',      'Parcel point'),
    ('landuse', 'depot',              'Depot'),
    ('amenity', 'bus_station',        'Bus station'),
    ('railway', 'station',            'Railway station'),
    ('aeroway', 'aerodrome',          'Airport'),
    ('amenity', 'fuel',               'Fuel station'),
    ('industrial', 'warehouse',       'Warehouse'),
]


def _haversine_km(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


class _TTLCache:
    """Small thread-safe TTL cache.

    Third-party geocoders are rate-limited and a type-ahead box is the single most effective
    way to exhaust a quota: eight keystrokes is eight requests unless something remembers.
    """

    def __init__(self, ttl=CACHE_TTL_S, cap=512):
        self._data = {}
        self._ttl = ttl
        self._cap = cap
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._data.get(key)
            if not hit:
                return None
            value, stored_at = hit
            if time.time() - stored_at > self._ttl:
                self._data.pop(key, None)
                return None
            return value

    def put(self, key, value):
        with self._lock:
            if len(self._data) >= self._cap:
                oldest = min(self._data.items(), key=lambda kv: kv[1][1])[0]
                self._data.pop(oldest, None)
            self._data[key] = (value, time.time())


_cache = _TTLCache()


def _get_json(url, timeout=REMOTE_TIMEOUT_S, data=None):
    request = urllib.request.Request(
        url,
        data=data.encode() if isinstance(data, str) else data,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


# ------------------------------------------------------------------ local provider

class LocalPlaceProvider:
    """The corridor network itself. Always available, and the only directly routable results."""

    def __init__(self, provider):
        self._provider = provider

    def _locations(self):
        try:
            return self._provider.get_locations()
        except Exception as e:
            logger.warning(f"Could not read locations: {e}")
            return []

    def search(self, query, limit=8):
        q = (query or "").strip().lower()
        if not q:
            return []
        scored = []
        for loc in self._locations():
            name = loc.name.lower()
            # Prefix beats substring beats district/state match, so typing "sil" puts Silchar
            # and Siliguri above "Sonitpur district" rather than sorting them alphabetically.
            if name.startswith(q):
                rank = 0
            elif q in name:
                rank = 1
            elif q in (loc.district or "").lower() or q in (loc.state or "").lower():
                rank = 2
            else:
                continue
            scored.append((rank, len(loc.name), loc))

        scored.sort(key=lambda t: (t[0], t[1]))
        return [self._to_dict(loc) for _, _, loc in scored[:limit]]

    def _to_dict(self, loc):
        return {
            "id": loc.id,
            "source": "network",
            "name": loc.name,
            "label": f"{loc.name}, {loc.state}",
            "context": f"{loc.district} district · {loc.state}",
            "state": loc.state,
            "district": loc.district,
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            # The distinction the planner cares about: this one can be an origin as-is.
            "routable": True,
            "location_id": loc.id,
        }

    def nearest(self, lat, lon, limit=3):
        """Nearest corridor node to an arbitrary point.

        This is what lets a place OSM knows about but the network does not still be used: the
        consignment is planned from the nearest node and the interface states the gap, rather
        than refusing an address it cannot route from.
        """
        ranked = sorted(
            ((_haversine_km((lat, lon), (l.latitude, l.longitude)), l) for l in self._locations()),
            key=lambda t: t[0],
        )
        out = []
        for distance, loc in ranked[:limit]:
            entry = self._to_dict(loc)
            entry["distance_km"] = round(distance, 1)
            out.append(entry)
        return out


# ------------------------------------------------------------------ OSM provider

class OSMPlaceProvider:
    """Photon for geocoding, Overpass for facilities. No API key; be a good citizen."""

    def search(self, query, limit=8):
        q = (query or "").strip()
        if len(q) < 2:
            return []

        key = f"photon:{q.lower()}:{limit}"
        cached = _cache.get(key)
        if cached is not None:
            return cached

        params = urllib.parse.urlencode({
            "q": q,
            "limit": limit,
            "lang": "en",
            "lat": NER_CENTER[0],
            "lon": NER_CENTER[1],
            "bbox": f"{NER_BBOX['min_lon']},{NER_BBOX['min_lat']},{NER_BBOX['max_lon']},{NER_BBOX['max_lat']}",
        })
        try:
            payload = _get_json(f"{PHOTON_URL}?{params}")
        except Exception as e:
            logger.info(f"Photon unavailable ({e}); local results only.")
            return None  # None, not [] — the caller must be able to tell "off" from "no matches"

        results = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            name = props.get("name") or props.get("street") or props.get("city")
            if not name:
                continue
            context = ", ".join(
                p for p in [props.get("district"), props.get("city"), props.get("county"),
                            props.get("state")]
                if p and p != name
            )
            results.append({
                "id": f"osm:{props.get('osm_type','')}{props.get('osm_id','')}",
                "source": "osm",
                "name": name,
                "label": f"{name}{', ' + context if context else ''}",
                "context": context or props.get("country", ""),
                "state": props.get("state"),
                "district": props.get("district") or props.get("county"),
                "latitude": coords[1],
                "longitude": coords[0],
                # Not a node on the corridor graph — the caller snaps it to the nearest one.
                "routable": False,
                "location_id": None,
            })

        _cache.put(key, results)
        return results

    def nearby_facilities(self, lat, lon, radius_km=5.0, limit=20):
        key = f"overpass:{round(lat,3)}:{round(lon,3)}:{radius_km}"
        cached = _cache.get(key)
        if cached is not None:
            return cached

        radius_m = int(min(radius_km, 25) * 1000)
        clauses = "".join(
            f'node["{k}"="{v}"](around:{radius_m},{lat},{lon});'
            f'way["{k}"="{v}"](around:{radius_m},{lat},{lon});'
            for k, v, _ in FACILITY_QUERIES
        )
        query = f"[out:json][timeout:20];({clauses});out center tags {limit * 3};"

        try:
            payload = _get_json(OVERPASS_URL, timeout=max(REMOTE_TIMEOUT_S, 12.0),
                                data=urllib.parse.urlencode({"data": query}))
        except Exception as e:
            logger.info(f"Overpass unavailable ({e}).")
            return None

        label_for = {(k, v): label for k, v, label in FACILITY_QUERIES}
        seen = set()
        out = []
        for element in payload.get("elements", []):
            tags = element.get("tags", {})
            name = tags.get("name")
            if not name or name in seen:
                continue
            seen.add(name)

            point_lat = element.get("lat") or (element.get("center") or {}).get("lat")
            point_lon = element.get("lon") or (element.get("center") or {}).get("lon")
            if point_lat is None or point_lon is None:
                continue

            kind = next(
                (label for (k, v), label in label_for.items() if tags.get(k) == v),
                "Facility",
            )

            # Passed through exactly as OSM records it, or null. Never invented.
            phone = tags.get("phone") or tags.get("contact:phone") or None
            address = ", ".join(
                p for p in [
                    tags.get("addr:housenumber"), tags.get("addr:street"),
                    tags.get("addr:suburb"), tags.get("addr:city"),
                ] if p
            ) or None

            out.append({
                "id": f"{element.get('type')}/{element.get('id')}",
                "name": name,
                "kind": kind,
                "latitude": point_lat,
                "longitude": point_lon,
                "distance_km": round(_haversine_km((lat, lon), (point_lat, point_lon)), 2),
                "phone": phone,
                "website": tags.get("website") or tags.get("contact:website"),
                "opening_hours": tags.get("opening_hours"),
                "operator": tags.get("operator"),
                "address": address,
            })

        out.sort(key=lambda f: f["distance_km"])
        out = out[:limit]
        _cache.put(key, out)
        return out


# ------------------------------------------------------------------ composite

class PlacesService:
    def __init__(self, provider):
        self.local = LocalPlaceProvider(provider)
        self.osm = OSMPlaceProvider()

    def search(self, query, limit=8):
        """Corridor nodes first, then real places. Deduplicated by name.

        Network nodes lead because they are the ones that can be planned from directly; an OSM
        result carrying the same name would only offer the user a worse version of a choice
        they already have.
        """
        local_hits = self.local.search(query, limit=limit)
        remote_hits = self.osm.search(query, limit=limit)

        degraded = remote_hits is None
        combined = list(local_hits)
        seen = {hit["name"].lower() for hit in local_hits}
        for hit in remote_hits or []:
            if hit["name"].lower() in seen:
                continue
            seen.add(hit["name"].lower())
            combined.append(hit)

        return {
            "results": combined[: limit * 2],
            "degraded": degraded,
            "attribution": OSM_ATTRIBUTION,
        }

    def nearby(self, lat, lon, radius_km=5.0, limit=20):
        """Facilities you could hand goods over at, plus the nearest routable corridor node."""
        facilities = self.osm.nearby_facilities(lat, lon, radius_km=radius_km, limit=limit)
        return {
            "facilities": facilities or [],
            "degraded": facilities is None,
            "nearest_network_points": self.local.nearest(lat, lon, limit=3),
            "attribution": OSM_ATTRIBUTION,
            "note": (
                "Contact details come from OpenStreetMap and are shown exactly as recorded "
                "there. A missing number means OSM has none, not that the facility has none."
            ),
        }

    def resolve(self, lat, lon):
        """Snap an arbitrary point onto the corridor network so it can be planned from."""
        nearest = self.local.nearest(lat, lon, limit=3)
        return {
            "nearest_network_points": nearest,
            "origin": nearest[0] if nearest else None,
        }
