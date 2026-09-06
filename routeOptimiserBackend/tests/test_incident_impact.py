# tests/test_incident_impact.py
"""Tests for how community incidents affect accessibility and traversability.

These guard two rules that are easy to get subtly wrong and dangerous when wrong:
  1. A verified severe incident closes ONLY the segment it was attributed to — not every
     road within the attribution radius.
  2. Nearby (non-attributed) incidents still raise risk, they just don't close roads.
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture(scope="module")
def db_session_module():
    tmp_dir = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmp_dir, 'impact.db')}"
    import src.db.session as session_module

    session_module._engine = None
    session_module._SessionLocal = None
    session_module.init_db()
    return session_module


def _add_incident(session_module, *, segment_id, latitude, longitude, severity=5,
                  status="verified", incident_type="landslide"):
    from src.db.models import Incident

    session = session_module.get_session()
    try:
        incident = Incident(
            client_uuid=str(uuid.uuid4()),
            incident_type=incident_type,
            severity=severity,
            latitude=latitude,
            longitude=longitude,
            segment_id=segment_id,
            verification_status=status,
            reported_at=datetime.now(timezone.utc),
        )
        session.add(incident)
        session.commit()
        return incident.id
    finally:
        session.close()


def _assess(segment_id):
    from src.services.accessibility_service import AccessibilityService

    return next(
        s for s in AccessibilityService().assess_all_segments() if s["id"] == segment_id
    )


def test_verified_severe_incident_closes_only_its_own_segment(db_session_module):
    # Jowai sits near several corridors; place a severity-5 landslide attributed to RS013
    # (Shillong-Jowai) and confirm neighbours are not also closed.
    _add_incident(db_session_module, segment_id="RS013", latitude=25.45, longitude=92.20)

    from src.services.accessibility_service import AccessibilityService

    assessed = {s["id"]: s for s in AccessibilityService().assess_all_segments()}

    assert assessed["RS013"]["impassable"] is True, "Attributed segment must close"

    # Other segments within the attribution radius must NOT be closed by this one report.
    neighbours = [s for sid, s in assessed.items() if sid != "RS013" and s["active_incident_count"] > 0]
    assert neighbours, "Expected the incident to be attributed to nearby segments for risk"
    closed_neighbours = [s["id"] for s in neighbours if s["impassable"]]
    assert not closed_neighbours, (
        f"A single report must not close neighbouring corridors, but closed: {closed_neighbours}"
    )


def test_nearby_incident_still_raises_risk_without_closing(db_session_module):
    from src.services.accessibility_service import AccessibilityService

    assessed = {s["id"]: s for s in AccessibilityService().assess_all_segments()}
    neighbours = [
        s for sid, s in assessed.items()
        if sid != "RS013" and s["active_incident_count"] > 0 and not s["impassable"]
    ]
    assert neighbours
    # Incident pressure must show up in the risk inputs used by the accessibility formula.
    assert all(s["risk_inputs"]["incident_risk"] > 0 for s in neighbours)


def test_unverified_severe_incident_does_not_close_a_road(db_session_module):
    _add_incident(
        db_session_module, segment_id="RS024", latitude=23.83, longitude=91.29, status="unverified"
    )
    segment = _assess("RS024")
    assert segment["impassable"] is False, "Unverified reports must never close a corridor"
    assert segment["active_incident_count"] >= 1


def test_rejected_incidents_are_ignored(db_session_module):
    _add_incident(
        db_session_module, segment_id="RS025", latitude=24.37, longitude=92.17,
        status="rejected", severity=5,
    )
    segment = _assess("RS025")
    assert segment["impassable"] is False


# ---------------------------------------------------------------------------------------
# Attribution has to be bounded.
#
# "Nearest corridor" with no maximum distance is not attribution, it is a guess that always
# answers. A report filed from Mumbai has a nearest NER corridor the same way it has a
# nearest bus stop in Kohima, and before these tests existed that guess was stored, drawn on
# the map as that corridor's problem, and — because an explicitly attributed report skips the
# proximity check — could close a highway 1,700 km from the person reporting it.
# ---------------------------------------------------------------------------------------


def test_a_point_on_the_network_is_attributed_with_its_distance():
    from src.services.accessibility_service import AccessibilityService

    # Just outside Guwahati, on the corridor network.
    segment_id, distance_km = AccessibilityService().nearest_segment(26.14, 91.73)
    assert segment_id is not None
    assert distance_km is not None and distance_km < 5


def test_a_point_far_from_the_network_is_attributed_to_nothing():
    from src.services.accessibility_service import (
        INCIDENT_SNAP_RADIUS_KM,
        AccessibilityService,
    )

    service = AccessibilityService()
    for name, lat, lon in [
        ("Mumbai", 19.0760, 72.8777),
        ("Delhi", 28.6139, 77.2090),
        ("Kolkata", 22.5726, 88.3639),
        ("Bay of Bengal", 18.0, 89.0),
    ]:
        segment_id, distance_km = service.nearest_segment(lat, lon)
        assert segment_id is None, f"{name} must not be attributed to an NER corridor"
        # The distance still comes back, so the interface can say how far off it was
        # instead of silently dropping the report on the floor.
        assert distance_km > INCIDENT_SNAP_RADIUS_KM


def test_reporting_off_network_does_not_claim_a_corridor(db_session_module):
    """End to end: an off-network report is stored, but attributed to nothing."""
    import uuid as _uuid

    from src.api.ner_routes import _store_incident

    stored, created, error = _store_incident({
        "client_uuid": str(_uuid.uuid4()),
        "type": "landslide",
        "severity": 5,
        "latitude": 19.0760,
        "longitude": 72.8777,
        "description": "Filed from Mumbai by mistake",
    })
    assert error is None and created is True
    assert stored["segment_id"] is None
    assert stored["segment_distance_km"] > 1000
    # And its own coordinates are preserved exactly, so the map still shows where it is.
    assert stored["latitude"] == 19.0760 and stored["longitude"] == 72.8777


def test_a_distant_attribution_cannot_close_a_corridor(db_session_module):
    """A row that already carries a bad attribution must not be able to act on it.

    Databases written before the snap radius existed contain exactly these rows, and an
    upgrade must not leave a severity-5 landslide "in Mumbai" holding a highway in Assam shut.
    """
    _add_incident(
        db_session_module, segment_id="RS001", latitude=19.0760, longitude=72.8777,
        severity=5, status="verified", incident_type="landslide",
    )
    segment = _assess("RS001")
    assert segment["impassable"] is False
    assert segment["active_incident_count"] == 0
