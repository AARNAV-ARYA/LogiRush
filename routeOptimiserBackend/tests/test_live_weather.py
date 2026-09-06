# tests/test_live_weather.py
"""Tests for live rainfall.

The network is stubbed throughout. A test that reaches Open-Meteo would be testing the
monsoon, and would fail on a train.

What is worth pinning here is not that an HTTP call can be made — it is the two properties
that decide whether making the weather live was worth doing at all:

  * the live numbers reach the things that make decisions (the model's features, the
    accessibility score's weather term), rather than only a display endpoint; and
  * when the feed is unavailable the platform keeps working on the snapshot and *says* it is
    on the snapshot, rather than presenting stale or invented values as live.
"""

import time

import pytest

from src.data_processing import weather_provider as wp
from src.data_processing.ner_data_provider import (
    LiveWeatherNERDataProvider, MockNERDataProvider,
)


# ------------------------------------------------------------------ the risk ladder

@pytest.mark.parametrize("mm_24h,expected_base", [
    (0.0, 5.0),        # no rain
    (2.4, 5.0),        # still "very light" at the boundary
    (2.5, 20.0),       # light begins
    (15.5, 20.0),
    (15.6, 40.0),      # moderate begins
    (64.4, 40.0),
    (64.5, 65.0),      # heavy begins
    (115.6, 85.0),     # very heavy
    (204.5, 100.0),    # extremely heavy
])
def test_risk_ladder_follows_imd_rainfall_bands(mm_24h, expected_base):
    """The bands are IMD's published classification, so the boundaries are not ours to move."""
    assert wp.rainfall_to_weather_risk(mm_24h, 0.0) == expected_base


def test_forecast_adds_but_never_dominates():
    """Rain that has not fallen yet still closes roads, but what actually happened wins."""
    dry_now = wp.rainfall_to_weather_risk(0.0, 0.0)
    dry_now_wet_soon = wp.rainfall_to_weather_risk(0.0, 100.0)
    assert dry_now_wet_soon > dry_now

    # The forecast contribution is capped at 20, so a forecast can never lift a dry corridor
    # past one that has had moderate rain.
    assert wp.rainfall_to_weather_risk(0.0, 10_000.0) < wp.rainfall_to_weather_risk(20.0, 0.0)
    assert wp.rainfall_to_weather_risk(300.0, 300.0) <= 100.0


def test_risk_is_deterministic():
    """It feeds an accessibility score, which the AI Usage Policy requires to be ML-free and
    reproducible — same inputs, same number, every time."""
    assert wp.rainfall_to_weather_risk(37.0, 62.0) == wp.rainfall_to_weather_risk(37.0, 62.0)


# ------------------------------------------------------------------ splitting the series

def _series(past_hours, future_hours, past_mm=1.0, future_mm=2.0):
    """An hourly series centred on the current UTC hour, like Open-Meteo returns."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    times, values = [], []
    for i in range(past_hours, 0, -1):
        times.append((now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:00"))
        values.append(past_mm)
    for i in range(future_hours):
        times.append((now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00"))
        values.append(future_mm)
    return {"hourly": {"time": times, "precipitation": values}}


def test_observed_and_forecast_are_split_at_the_current_hour():
    """rainfall_mm_24h is what fell; forecast_rainfall_mm_48h is what is coming. Mixing the
    two would quietly double-count the present hour into both."""
    result = wp._accumulate(_series(24, 48, past_mm=1.0, future_mm=2.0))
    assert result["rain_24h"] == pytest.approx(24.0)
    assert result["rain_48h"] == pytest.approx(96.0)


def test_a_series_without_the_current_hour_still_yields_numbers():
    """Clock skew must degrade to a sane split, not an exception on every corridor."""
    result = wp._accumulate({"hourly": {"time": ["1999-01-01T00:00"], "precipitation": [5.0]}})
    assert result["rain_24h"] >= 0 and result["rain_48h"] >= 0


def test_an_empty_response_is_not_an_error():
    assert wp._accumulate({}) == {"rain_24h": 0.0, "rain_48h": 0.0}


# ------------------------------------------------------------------ substitution

class _StubProvider:
    """Stands in for Open-Meteo. Reports the same rainfall for every corridor."""

    def __init__(self, rain_24h=80.0, rain_48h=120.0, fail=False):
        self.rain_24h, self.rain_48h, self.fail = rain_24h, rain_48h, fail
        self.calls = 0

    def get(self, coordinates):
        self.calls += 1
        if self.fail:
            return wp._Snapshot({}, time.time(), error="stubbed outage")
        readings = {wp._key(lat, lon): {"rain_24h": self.rain_24h, "rain_48h": self.rain_48h}
                    for lat, lon in coordinates}
        return wp._Snapshot(readings, time.time())


@pytest.fixture
def live_enabled(monkeypatch):
    """The suite pins the snapshot globally (conftest); these tests need the live path on."""
    monkeypatch.setattr(wp, "LIVE_ENABLED", True)


def test_live_rainfall_reaches_the_models_features(live_enabled):
    """The point of the whole exercise: the numbers the model trains on are the live ones.

    A weather endpoint that reports live rain while get_segment_features() keeps returning
    the CSV would look identical from outside and change no decision the platform makes.
    """
    snapshot = MockNERDataProvider().get_segment_features()
    live = LiveWeatherNERDataProvider(provider=_StubProvider(80.0, 120.0)).get_segment_features()

    assert set(live) == set(snapshot), "no corridor may be lost when rainfall is substituted"
    for segment_id, feature in live.items():
        assert feature["rainfall_mm_24h"] == 80.0
        assert feature["forecast_rainfall_mm_48h"] == 120.0
        # Terrain and history are NOT live and must be passed through untouched.
        assert feature["slope_gradient_deg"] == snapshot[segment_id]["slope_gradient_deg"]
        assert feature["historical_floods_5y"] == snapshot[segment_id]["historical_floods_5y"]


def test_live_rainfall_reaches_the_accessibility_score(live_enabled):
    """weather_risk is a quarter of every accessibility score. If it stayed on the CSV, the
    map would colour corridors by hand-typed weather while the model used real rain."""
    live = LiveWeatherNERDataProvider(provider=_StubProvider(80.0, 120.0)).get_road_segments()

    # 80 mm in 24 h is IMD "heavy" (65), plus the capped forecast contribution (20).
    expected = wp.rainfall_to_weather_risk(80.0, 120.0)
    assert expected == 85.0
    assert {round(s.weather_risk, 1) for s in live} == {85.0}

    # Everything that is not weather stays exactly as it was — this substitutes one input,
    # it does not invent a new network.
    snapshot = {s.id: s for s in MockNERDataProvider().get_road_segments()}
    for segment in live:
        original = snapshot[segment.id]
        assert segment.landslide_risk == original.landslide_risk
        assert segment.flood_risk == original.flood_risk
        assert segment.distance_km == original.distance_km


def test_an_outage_falls_back_to_the_snapshot_rather_than_failing(live_enabled):
    """A weather API having a bad afternoon must never take routing offline."""
    provider = LiveWeatherNERDataProvider(provider=_StubProvider(fail=True))

    snapshot_features = MockNERDataProvider().get_segment_features()
    assert provider.get_segment_features() == snapshot_features

    snapshot_segments = {s.id: s.weather_risk for s in MockNERDataProvider().get_road_segments()}
    assert {s.id: s.weather_risk for s in provider.get_road_segments()} == snapshot_segments


def test_disabling_live_weather_makes_no_network_call(monkeypatch):
    """NER_LIVE_WEATHER=0 has to mean *no request*, not a request that is thrown away —
    otherwise offline and reproducible runs still hang on a DNS timeout."""
    monkeypatch.setattr(wp, "LIVE_ENABLED", False)
    stub = _StubProvider()
    provider = LiveWeatherNERDataProvider(provider=stub)

    provider.get_segment_features()
    provider.get_road_segments()
    assert stub.calls == 0


def test_corridors_are_read_at_their_midpoint_not_their_endpoints(live_enabled):
    """A 600 km corridor read at the city it ends in reports the weather in that city."""
    stub = _StubProvider()
    provider = LiveWeatherNERDataProvider(provider=stub)
    midpoints = provider._segment_midpoints()

    locations = {loc.id: loc for loc in provider.get_locations()}
    segment = next(s for s in MockNERDataProvider().get_road_segments() if s.id in midpoints)
    source, destination = locations[segment.source], locations[segment.destination]
    lat, lon = midpoints[segment.id]

    assert lat == pytest.approx((source.latitude + destination.latitude) / 2)
    assert lon == pytest.approx((source.longitude + destination.longitude) / 2)
    assert min(source.latitude, destination.latitude) <= lat <= max(source.latitude, destination.latitude)


# ------------------------------------------------------------------ honesty

def test_the_manifest_never_calls_open_meteo_an_imd_feed(live_enabled, monkeypatch):
    """Open-Meteo is real live data and is not the India Meteorological Department. That
    distinction is the single easiest thing to overstate on a provenance screen, so it is
    asserted rather than trusted."""
    monkeypatch.setattr(wp.weather_provider, "_snapshot",
                        wp._Snapshot({"x": {"rain_24h": 5.0, "rain_48h": 9.0}}, time.time()))

    from src.data_processing.data_sources import _rainfall_source

    entry = _rainfall_source()
    assert entry["trust"] == "live"
    assert "Open-Meteo" in entry["origin"]
    assert "NOT from IMD" in entry["summary"] or "not an IMD" in entry["caveat"]
    # IMD may appear only as the upstream that would replace this, never as its origin.
    assert "IMD" in entry["upstream"]["name"]


def test_the_manifest_admits_when_the_feed_is_down(monkeypatch):
    """A failed fetch must show as the snapshot, not as stale data presented as live."""
    monkeypatch.setattr(wp, "LIVE_ENABLED", False)
    monkeypatch.setattr(wp.weather_provider, "_snapshot", None)

    from src.data_processing.data_sources import _rainfall_source

    entry = _rainfall_source()
    assert entry["trust"] == "sample"
    assert "snapshot" in entry["summary"].lower()
