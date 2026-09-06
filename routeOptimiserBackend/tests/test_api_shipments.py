# tests/test_api_shipments.py
"""Shipment lifecycle, snapshotting, and dynamic replanning."""

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture(scope="module")
def client():
    tmp_dir = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmp_dir, 'shipments.db')}"
    import src.db.session as session_module

    session_module._engine = None
    session_module._SessionLocal = None
    session_module.init_db()

    from main import app

    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def _payload(**overrides):
    payload = {
        "client_uuid": str(uuid.uuid4()),
        "origin_id": "LOC002",
        "destination_id": "LOC007",
        "cargo_type": "relief",
        "urgency": "high",
        "weight_kg": 1500,
        "priority": 2,
    }
    payload.update(overrides)
    return payload


def test_create_shipment_plans_and_stores_route(client):
    response = client.post("/api/ner/shipments", json=_payload())
    assert response.status_code == 201
    body = response.get_json()
    assert body["created"] is True
    assert body["shipment"]["status"] == "planned"
    assert body["planned_route"]["path"][0] == "LOC002"
    assert body["planned_route"]["eta_hours"] > 0
    assert body["routable"] is True


def test_create_shipment_is_idempotent(client):
    payload = _payload()
    first = client.post("/api/ner/shipments", json=payload)
    second = client.post("/api/ner/shipments", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["duplicate"] is True
    assert first.get_json()["shipment"]["id"] == second.get_json()["shipment"]["id"]


@pytest.mark.parametrize(
    "bad,fragment",
    [
        ({"origin_id": "LOC002"}, "required"),
        ({"origin_id": "LOC002", "destination_id": "LOC002"}, "different"),
        ({"origin_id": "LOC002", "destination_id": "LOC007", "cargo_type": "plutonium"}, "cargo_type"),
        ({"origin_id": "LOC002", "destination_id": "LOC007", "urgency": "yesterday"}, "urgency"),
        ({"origin_id": "LOC002", "destination_id": "LOC007", "weight_kg": -5}, "negative"),
        ({"origin_id": "LOC002", "destination_id": "LOC007", "priority": 99}, "priority"),
    ],
)
def test_shipment_validation(client, bad, fragment):
    response = client.post("/api/ner/shipments", json=bad)
    assert response.status_code == 400
    assert fragment in response.get_json()["message"].lower()


def test_unknown_location_returns_404(client):
    response = client.post("/api/ner/shipments", json=_payload(origin_id="LOC999"))
    assert response.status_code == 404


def test_list_and_filter_shipments(client):
    client.post("/api/ner/shipments", json=_payload())
    all_shipments = client.get("/api/ner/shipments").get_json()
    assert all_shipments["count"] >= 1

    filtered = client.get("/api/ner/shipments?status=planned").get_json()
    assert all(s["status"] == "planned" for s in filtered["shipments"])

    bad = client.get("/api/ner/shipments?status=teleported")
    assert bad.status_code == 400


def test_get_single_shipment(client):
    created = client.post("/api/ner/shipments", json=_payload()).get_json()
    shipment_id = created["shipment"]["id"]
    response = client.get(f"/api/ner/shipments/{shipment_id}")
    assert response.status_code == 200
    assert response.get_json()["shipment"]["id"] == shipment_id
    assert client.get("/api/ner/shipments/999999").status_code == 404


def test_status_transitions(client):
    created = client.post("/api/ner/shipments", json=_payload()).get_json()
    shipment_id = created["shipment"]["id"]
    for status in ["dispatched", "in_transit", "delivered"]:
        response = client.post(f"/api/ner/shipments/{shipment_id}/status", json={"status": status})
        assert response.status_code == 200
        assert response.get_json()["shipment"]["status"] == status

    bad = client.post(f"/api/ner/shipments/{shipment_id}/status", json={"status": "levitating"})
    assert bad.status_code == 400


def test_replan_reports_no_change_when_conditions_are_stable(client):
    created = client.post("/api/ner/shipments", json=_payload()).get_json()
    shipment_id = created["shipment"]["id"]
    response = client.post(f"/api/ner/shipments/{shipment_id}/replan", json={})
    assert response.status_code == 200
    body = response.get_json()
    assert body["route_changed"] is False
    assert body["routable"] is True
    assert "still the best" in body["summary"]


def test_replan_detects_a_route_change_after_a_blocking_incident(client):
    """The core dynamic-adaptation behaviour: block the chosen corridor, replan, see it change."""
    from src.db.models import Incident
    from src.db.session import get_session

    created = client.post(
        "/api/ner/shipments",
        json=_payload(cargo_type="perishable", urgency="critical"),
    ).get_json()
    shipment_id = created["shipment"]["id"]
    # The create response carries full segment objects; the stored snapshot carries ids.
    blocked_segment = created["planned_route"]["segments"][0]["segment_id"]

    session = get_session()
    try:
        session.add(
            Incident(
                client_uuid=str(uuid.uuid4()),
                incident_type="landslide",
                severity=5,
                latitude=25.49,
                longitude=92.26,
                segment_id=blocked_segment,
                verification_status="verified",
                reported_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    finally:
        session.close()

    from src.services.routing_service import routing_service

    routing_service.invalidate()

    response = client.post(f"/api/ner/shipments/{shipment_id}/replan", json={"update_snapshot": True})
    assert response.status_code == 200
    body = response.get_json()
    assert body["route_changed"] is True, "Blocking the chosen corridor must change the route"
    current_segment_ids = [s["segment_id"] for s in body["current_route"]["segments"]]
    assert blocked_segment not in current_segment_ids
    assert body["snapshot_updated"] is True
    assert "Conditions changed" in body["summary"]


def test_replan_missing_shipment_returns_404(client):
    assert client.post("/api/ner/shipments/999999/replan", json={}).status_code == 404
