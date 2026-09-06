# src/data_processing/weather_provider.py
"""
Live rainfall for the corridor network — Open-Meteo.

Why this exists
---------------
The platform's rainfall figures were a frozen snapshot in a CSV: `rainfall_mm_24h` and
`forecast_rainfall_mm_48h`, hand-authored, changing only when the repository did. They are
also the disaster model's two strongest features and a quarter of every accessibility score,
so "the weather data is synthetic" was not a footnote — it was the largest single assumption
in every number the platform showed.

This module replaces those two values with real precipitation, and it does so *behind the
provider interface* rather than beside it. That distinction is the whole point: an endpoint
that reports the weather proves an API call works, while the map, the risk scores and the
routing carry on running off the CSV. Substituting the features means the corridor colours,
the model's probabilities and the chosen route all move when it actually rains.

On the source
-------------
Open-Meteo is free, keyless and rate-limit-friendly, and serves the national weather
services' own numerical models (DWD ICON, ECMWF, NOAA GFS). It is **real meteorological
data, and it is not IMD.** For a corridor in Meghalaya the difference is a different model's
QPF, not a different reality — but the honest label is "live forecast data", never "official
IMD data", and the provenance manifest says exactly that.

What is derived, and how
------------------------
    rainfall_mm_24h            summed hourly precipitation over the last 24 h
    forecast_rainfall_mm_48h   summed hourly precipitation over the next 48 h

`weather_risk` (0-100, a quarter of the accessibility score) is then a documented, purely
deterministic ladder over those two numbers — see `rainfall_to_weather_risk`. No ML touches
it, which is what the project's AI Usage Policy requires of anything feeding an accessibility
score.

Failure is not an option the network gives us, so it is designed for: every fetch is
time-boxed, cached, and on any error the caller silently keeps the CSV snapshot it already
had. A weather API having a bad afternoon must never be able to take the routing offline.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("weather")


def _ssl_context():
    """A TLS context that can actually verify a certificate on this machine.

    Python does not use the operating system's trust store on macOS, and a Homebrew or
    Anaconda interpreter that never ran `Install Certificates.command` fails every HTTPS
    request with CERTIFICATE_VERIFY_FAILED. Because this module degrades gracefully, that
    presents as "live weather is unavailable" — indistinguishable from the API being down,
    and it would have been diagnosed as a broken feature rather than a missing CA bundle.

    certifi ships the same bundle and is already installed (requests depends on it), so
    preferring it makes the fetch work identically on a developer's laptop and in the
    container. Verification is never disabled: an unverified HTTPS request is worse than no
    request, since the whole point is trusting the numbers that come back.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # pragma: no cover - certifi is a transitive dependency of requests
        return ssl.create_default_context()


_SSL_CONTEXT = _ssl_context()

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Live by default: a demonstration that silently runs on snapshot data because someone forgot
# an environment variable is the failure this module exists to prevent. Set to 0 to pin the
# CSV snapshot (offline work, or a reproducible run).
LIVE_ENABLED = os.environ.get("NER_LIVE_WEATHER", "1").strip().lower() not in ("0", "false", "no")

# Long enough that a demo never waits on a second fetch, short enough to be genuinely current.
# Rainfall accumulations over 24/48 h do not move meaningfully inside a quarter of an hour.
CACHE_TTL_S = int(os.environ.get("WEATHER_CACHE_TTL_S", "900"))

# A field deployment is on a bad link. Four seconds, then fall back — the snapshot is right
# there, and a slow answer is worse than an honest old one.
TIMEOUT_S = float(os.environ.get("WEATHER_TIMEOUT_S", "4.0"))

USER_AGENT = "ner-logistics-platform/1.0 (SIH demo; corridor rainfall)"


def rainfall_to_weather_risk(mm_24h: float, mm_48h: float) -> float:
    """Map observed and forecast rainfall to the 0-100 weather risk the score expects.

    The bands are IMD's own published 24-hour rainfall classification — light, moderate,
    heavy, very heavy, extremely heavy — because inventing a private scale when the national
    meteorological service has already defined one would be both arbitrary and harder to
    defend. The classification is official; the rainfall it is applied to comes from
    Open-Meteo, and the platform says so.

        IMD band                 24 h rainfall      weather_risk
        no rain / very light     < 2.5 mm                      5
        light                    2.5 - 15.5 mm                20
        moderate                 15.6 - 64.4 mm               40
        heavy                    64.5 - 115.5 mm              65
        very heavy               115.6 - 204.4 mm             85
        extremely heavy          >= 204.5 mm                 100

    The 48-hour forecast then adds up to 20 more: rain that has not fallen yet still closes
    roads, and a corridor with 90 mm coming is not in the same state as one with none, even
    when the last day was identical. It is capped so a forecast can never outweigh what has
    actually happened on the ground.

    Deterministic and total: same inputs, same output, no model, no randomness.
    """
    observed = max(0.0, float(mm_24h or 0.0))
    forecast = max(0.0, float(mm_48h or 0.0))

    if observed < 2.5:
        base = 5.0
    elif observed < 15.6:
        base = 20.0
    elif observed < 64.5:
        base = 40.0
    elif observed < 115.6:
        base = 65.0
    elif observed < 204.5:
        base = 85.0
    else:
        base = 100.0

    # 0 mm -> 0, 100 mm or more forecast -> the full 20.
    lookahead = min(20.0, forecast / 5.0)
    return round(min(100.0, base + lookahead), 1)


class _Snapshot:
    """One fetch of the whole network, with the time it was taken.

    Kept as a single object rather than per-coordinate entries so every corridor on a screen
    is described by the same moment. A map where half the corridors are ten minutes older
    than the other half is a map nobody can reason about.
    """

    def __init__(self, readings: dict, fetched_at: float, error: str | None = None):
        self.readings = readings          # (lat, lon) rounded -> {"rain_24h": .., "rain_48h": ..}
        self.fetched_at = fetched_at
        self.error = error

    @property
    def age_s(self) -> float:
        return time.time() - self.fetched_at

    def is_fresh(self) -> bool:
        return self.error is None and self.age_s < CACHE_TTL_S


class OpenMeteoWeatherProvider:
    """Batched live rainfall for a set of coordinates.

    Open-Meteo accepts comma-separated latitude/longitude lists and answers with one entry
    per point, so the entire 32-corridor network costs a single HTTP request rather than 32.
    That is what makes refreshing the whole map affordable enough to do on a timer.
    """

    def __init__(self, url: str = OPEN_METEO_URL):
        self.url = url
        self._snapshot: _Snapshot | None = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------- network

    def _fetch(self, coordinates: list[tuple[float, float]]) -> dict:
        """One request for every coordinate. Raises on failure; the caller decides."""
        query = urllib.parse.urlencode({
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in coordinates),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in coordinates),
            "hourly": "precipitation",
            # past_days=1 gives the 24 h that have already happened; forecast_days=3 covers
            # the 48 h ahead with room for the partial current hour at either end.
            "past_days": "1",
            "forecast_days": "3",
            "timezone": "UTC",
        })
        request = urllib.request.Request(
            f"{self.url}?{query}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_S, context=_SSL_CONTEXT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))

        # A single coordinate comes back as an object, several as a list. Normalising here
        # keeps every caller from having to know that.
        entries = payload if isinstance(payload, list) else [payload]

        readings = {}
        for (lat, lon), entry in zip(coordinates, entries):
            readings[_key(lat, lon)] = _accumulate(entry)
        return readings

    # -------------------------------------------------------------- public

    def get(self, coordinates: list[tuple[float, float]]) -> _Snapshot:
        """Rainfall for these coordinates, from cache when it is still fresh.

        Never raises. On failure it returns a snapshot carrying the error and no readings,
        which every caller treats as "keep the values you already have".
        """
        with self._lock:
            if self._snapshot is not None and self._snapshot.is_fresh():
                return self._snapshot

        started = time.time()
        try:
            readings = self._fetch(coordinates)
            snapshot = _Snapshot(readings, time.time())
            logger.info(
                "Live rainfall for %d corridors in %.2fs (Open-Meteo).",
                len(readings), time.time() - started,
            )
        except Exception as e:
            snapshot = _Snapshot({}, time.time(), error=f"{type(e).__name__}: {e}")
            logger.warning("Live rainfall unavailable, using the shipped snapshot: %s", e)

        with self._lock:
            # A failed fetch must not evict readings that are merely stale: an hour-old real
            # measurement beats a hand-typed one from last month, and the manifest reports
            # the age either way.
            if snapshot.error and self._snapshot is not None and self._snapshot.readings:
                self._snapshot.error = snapshot.error
                return self._snapshot
            self._snapshot = snapshot
        return snapshot

    def status(self) -> dict:
        """What the last fetch did, for the provenance manifest and the weather endpoint."""
        with self._lock:
            snapshot = self._snapshot
        if snapshot is None:
            return {"enabled": LIVE_ENABLED, "state": "not yet fetched", "source": "Open-Meteo"}
        return {
            "enabled": LIVE_ENABLED,
            "state": "live" if snapshot.readings else "unavailable",
            "source": "Open-Meteo (DWD ICON / ECMWF / NOAA GFS model output)",
            "official_imd": False,
            "corridors": len(snapshot.readings),
            "fetched_at": datetime.fromtimestamp(snapshot.fetched_at, tz=timezone.utc).isoformat(),
            "age_seconds": round(snapshot.age_s, 1),
            "cache_ttl_seconds": CACHE_TTL_S,
            "error": snapshot.error,
        }


def _key(lat: float, lon: float) -> tuple:
    return (round(float(lat), 3), round(float(lon), 3))


def _accumulate(entry: dict) -> dict:
    """Turn an hourly precipitation series into the two totals the model wants.

    Open-Meteo returns hours in order, `past_days` first, so the hour matching "now" splits
    the series into what has fallen and what is forecast. Finding that index by timestamp
    rather than assuming a fixed offset is what keeps this correct across time zones and the
    partial hour the API is currently inside.
    """
    hourly = entry.get("hourly") or {}
    times = hourly.get("time") or []
    precipitation = hourly.get("precipitation") or []
    if not times or not precipitation:
        return {"rain_24h": 0.0, "rain_48h": 0.0}

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    now_iso = now.strftime("%Y-%m-%dT%H:00")
    try:
        split = times.index(now_iso)
    except ValueError:
        # The series does not contain the current hour (clock skew, or an API window shift).
        # past_days=1 puts "now" 24 hours in; falling back to that is better than refusing.
        split = min(24, len(times))

    def total(values):
        return round(sum(v for v in values if isinstance(v, (int, float))), 1)

    return {
        "rain_24h": total(precipitation[max(0, split - 24):split]),
        "rain_48h": total(precipitation[split:split + 48]),
    }


# One provider for the process. The cache is the point, and a per-request instance would
# have none.
weather_provider = OpenMeteoWeatherProvider()
