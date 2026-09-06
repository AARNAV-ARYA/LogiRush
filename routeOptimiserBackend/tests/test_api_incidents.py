# tests/test_api_incidents.py
"""API-level tests for incident reporting and offline sync.

Uses a temporary SQLite database per test session so the developer's local data is never
touched and the tests are order-independent.
"""

import os
import tempfile
import uuid

import pytest


@pytest.fixture(scope="module")
def client():
    # Point the app at a throwaway database BEFORE anything imports the session module.
    tmp_dir = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmp_dir, 'test.db')}"

    import src.db.session as session_module

    session_module._engine = None
    session_module._SessionLocal = None
    session_module.init_db()

    from main import app

    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def _incident_payload(**overrides):
    payload = {
        "client_uuid": str(uuid.uuid4()),
        "type": "landslide",
        "severity": 4,
        "description": "Debris blocking one lane",
        "latitude": 25.7,
        "longitude": 93.9,
        "reporter_name": "Field Team",
    }
    payload.update(overrides)
    return payload


def test_health_endpoint(client):
    response = client.get("/api/ner/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data_source"] == "mock"


def test_create_incident(client):
    response = client.post("/api/ner/incidents", json=_incident_payload())
    assert response.status_code == 201
    body = response.get_json()
    assert body["created"] is True
    assert body["incident"]["type"] == "landslide"
    # Incidents must be attributed to a road segment deterministically at ingest.
    assert body["incident"]["segment_id"] is not None


def test_duplicate_client_uuid_is_idempotent(client):
    payload = _incident_payload()
    first = client.post("/api/ner/incidents", json=payload)
    second = client.post("/api/ner/incidents", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["duplicate"] is True
    # Same row, not a second one — this is what makes offline replay safe.
    assert first.get_json()["incident"]["id"] == second.get_json()["incident"]["id"]


@pytest.mark.parametrize(
    "bad_payload,expected_fragment",
    [
        ({"type": "alien_invasion", "latitude": 25.0, "longitude": 93.0}, "type"),
        ({"type": "flood", "severity": 9, "latitude": 25.0, "longitude": 93.0}, "severity"),
        ({"type": "flood", "latitude": 999, "longitude": 93.0}, "range"),
        ({"type": "flood"}, "latitude"),
    ],
)
def test_invalid_incidents_are_rejected(client, bad_payload, expected_fragment):
    response = client.post("/api/ner/incidents", json=bad_payload)
    assert response.status_code == 400
    assert expected_fragment.lower() in response.get_json()["message"].lower()


def test_offline_sync_reports_per_item_status(client):
    shared = _incident_payload(type="flood")
    client.post("/api/ner/incidents", json=shared)  # already synced earlier

    batch = {
        "incidents": [
            _incident_payload(type="road_block"),
            shared,  # replayed duplicate
            {"type": "not_a_type", "latitude": 25.0, "longitude": 93.0},  # invalid
        ]
    }
    response = client.post("/api/ner/incidents/sync", json=batch)
    assert response.status_code == 200
    body = response.get_json()
    assert body["processed"] == 3
    assert body["created"] == 1
    assert body["duplicates"] == 1
    assert body["errors"] == 1
    statuses = [r["status"] for r in body["results"]]
    assert statuses == ["created", "duplicate", "error"]


# ---------------------------------------------------------------- access control
#
# These replace two tests that called /verify with no credentials and expected it to work.
# That it used to work was the bug: verification closes roads, so "anyone who can reach the
# endpoint" was never an acceptable answer to "who verifies?".


@pytest.fixture(scope="module")
def actors(client):
    """Create one of each role and return their bearer tokens."""
    from src.api.auth import hash_password
    from src.db.models import Base, User
    from src.db.session import get_engine, get_session

    Base.metadata.create_all(bind=get_engine())
    session = get_session()
    # v1/v2 cover the whole region so the rule tests below exercise the rule under test and
    # not, accidentally, the jurisdiction check. `narrow` exists precisely to test that.
    ALL_NER = ("Assam,Arunachal Pradesh,Manipur,Meghalaya,"
               "Mizoram,Nagaland,Sikkim,Tripura,West Bengal")
    specs = [
        ("rep", "Reporter", "reporter", None),
        ("v1", "Verifier One", "verifier", ALL_NER),
        ("v2", "Verifier Two", "verifier", ALL_NER),
        ("narrow", "Sikkim Only", "verifier", "Sikkim"),
        ("ctl", "Controller", "controller", None),
    ]
    try:
        for username, name, role, juris in specs:
            if not session.query(User).filter(User.username == username).first():
                session.add(User(username=username, full_name=name, role=role,
                                 jurisdiction=juris, password_hash=hash_password("pw")))
        session.commit()
    finally:
        session.close()

    tokens = {}
    for username, *_ in specs:
        body = client.post("/api/auth/login",
                           json={"username": username, "password": "pw"}).get_json()
        tokens[username] = body["token"]
    return tokens


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _new_incident(client, **overrides):
    payload = _incident_payload()
    payload.update(overrides)
    return client.post("/api/ner/incidents", json=payload).get_json()["incident"]["id"]


def test_verify_requires_authentication(client):
    incident_id = _new_incident(client)
    assert client.post(f"/api/ner/incidents/{incident_id}/verify").status_code == 401


def test_reporter_cannot_verify(client, actors):
    incident_id = _new_incident(client)
    response = client.post(f"/api/ner/incidents/{incident_id}/verify",
                           headers=_auth(actors["rep"]))
    assert response.status_code == 403


def test_verifier_cannot_delete(client, actors):
    incident_id = _new_incident(client)
    response = client.delete(f"/api/ner/incidents/{incident_id}",
                             json={"reason": "spam"}, headers=_auth(actors["v1"]))
    assert response.status_code == 403


def test_controller_delete_requires_a_reason(client, actors):
    incident_id = _new_incident(client)
    assert client.delete(f"/api/ner/incidents/{incident_id}",
                         json={}, headers=_auth(actors["ctl"])).status_code == 400
    assert client.delete(f"/api/ner/incidents/{incident_id}",
                         json={"reason": "duplicate of #4"},
                         headers=_auth(actors["ctl"])).status_code == 200


def test_verifier_is_confined_to_their_jurisdiction(client, actors):
    """A verifier assigned to Sikkim has no business closing a highway in Nagaland."""
    incident_id = _new_incident(client)
    response = client.post(f"/api/ner/incidents/{incident_id}/verify",
                           headers=_auth(actors["narrow"]))
    assert response.status_code == 403
    assert "jurisdiction" in response.get_json()["message"].lower()


def test_controller_may_act_outside_any_jurisdiction(client, actors):
    incident_id = _new_incident(client, severity=1, type="other")
    response = client.post(f"/api/ner/incidents/{incident_id}/verify",
                           headers=_auth(actors["ctl"]))
    assert response.status_code == 200


def test_low_severity_verification_takes_effect_immediately(client, actors):
    """The two-person rule is scoped to closures, not applied to every report."""
    incident_id = _new_incident(client, severity=2, type="accident")
    response = client.post(f"/api/ner/incidents/{incident_id}/verify",
                           headers=_auth(actors["v1"]))
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["incident"]["verification_status"] == "verified"


def test_closure_needs_a_second_signature(client, actors):
    """A severity-5 blocking report must not close a road on one person's say-so."""
    incident_id = _new_incident(client, severity=5, type="landslide")

    first = client.post(f"/api/ner/incidents/{incident_id}/verify",
                        headers=_auth(actors["v1"])).get_json()
    assert first["incident"]["verification_status"] == "awaiting_countersign"

    repeat = client.post(f"/api/ner/incidents/{incident_id}/verify",
                         headers=_auth(actors["v1"]))
    assert repeat.status_code == 409, "the same verifier must not be able to countersign"

    second = client.post(f"/api/ner/incidents/{incident_id}/verify",
                         headers=_auth(actors["v2"])).get_json()
    assert second["incident"]["verification_status"] == "verified"
    assert second["incident"]["countersigned_by"] == "v2"


def test_resolved_incident_stops_affecting_routing(client, actors):
    """The reason `resolved` exists: a cleared slip reopens its corridor at once."""
    from src.db.models import ACTIVE_STATUSES

    incident_id = _new_incident(client, severity=5, type="landslide")
    client.post(f"/api/ner/incidents/{incident_id}/verify", headers=_auth(actors["v1"]))
    client.post(f"/api/ner/incidents/{incident_id}/verify", headers=_auth(actors["v2"]))

    resolved = client.post(f"/api/ner/incidents/{incident_id}/resolve",
                           json={"reason": "cleared by BRO"},
                           headers=_auth(actors["v1"])).get_json()
    assert resolved["incident"]["verification_status"] == "resolved"
    assert "resolved" not in ACTIVE_STATUSES, "a resolved report must be inert for routing"


def test_every_decision_is_audited(client, actors):
    incident_id = _new_incident(client, severity=1, type="other")
    client.post(f"/api/ner/incidents/{incident_id}/verify", headers=_auth(actors["v1"]))
    client.post(f"/api/ner/incidents/{incident_id}/resolve",
                json={"reason": "done"}, headers=_auth(actors["v1"]))

    audit = client.get(f"/api/ner/incidents/{incident_id}/audit").get_json()["audit"]
    assert [row["action"] for row in audit] == ["verify", "resolve"]
    assert all(row["actor"] == "v1" for row in audit)


def test_incidents_are_listed(client):
    client.post("/api/ner/incidents", json=_incident_payload())
    response = client.get("/api/ner/incidents?limit=10")
    assert response.status_code == 200
    assert len(response.get_json()["incidents"]) >= 1


# ---------------------------------------------------------------------------------------
# Attribution, shown to the reporter before it becomes a record.
# ---------------------------------------------------------------------------------------


def test_preview_names_the_corridor_a_report_would_land_on(client):
    response = client.get("/api/ner/incidents/preview?lat=26.14&lon=91.73")
    assert response.status_code == 200
    body = response.get_json()
    assert body["on_network"] is True
    assert body["segment_id"]
    # A corridor id means nothing to a reporter; the two towns it runs between do.
    assert "→" in body["segment_label"]
    assert body["distance_km"] < 5


def test_preview_says_so_when_a_point_is_off_the_network(client):
    response = client.get("/api/ner/incidents/preview?lat=19.0760&lon=72.8777")
    assert response.status_code == 200
    body = response.get_json()
    assert body["on_network"] is False
    assert body["segment_id"] is None
    assert body["segment_label"] is None
    # Still says how far off it was, which is what tells someone they fat-fingered a digit.
    assert body["distance_km"] > body["snap_radius_km"]


def test_preview_rejects_nonsense_coordinates(client):
    assert client.get("/api/ner/incidents/preview?lat=abc&lon=91.7").status_code == 400
    assert client.get("/api/ner/incidents/preview?lat=999&lon=91.7").status_code == 400
    assert client.get("/api/ner/incidents/preview?lon=91.7").status_code == 400


def test_created_incident_reports_its_own_attribution(client):
    response = client.post("/api/ner/incidents", json=_incident_payload(latitude=26.14, longitude=91.73))
    assert response.status_code == 201
    body = response.get_json()
    assert body["attribution"]["on_network"] is True
    assert body["attribution"]["segment_id"] == body["incident"]["segment_id"]
    assert body["incident"]["segment_distance_km"] is not None


def test_an_off_network_report_is_kept_but_claims_no_corridor(client):
    response = client.post(
        "/api/ner/incidents", json=_incident_payload(latitude=19.0760, longitude=72.8777)
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["incident"]["segment_id"] is None
    assert body["attribution"]["on_network"] is False
    # The report itself is not thrown away — it is still a person telling us something.
    assert body["incident"]["latitude"] == 19.0760


# ---------------------------------------------------------------- one database, two clients
#
# The web console and the field app are separate programs that must behave as one system: a
# report filed on a phone has to appear in the review queue on the website. These tests pin
# the two properties that makes true — a shared table, and a record of which client filed
# each report — because when it breaks, it breaks silently and looks like "the databases are
# not connected".


def test_a_report_from_the_field_app_appears_in_the_web_review_queue(client):
    """The whole app-to-console path, at the only level that proves it: one write, one read."""
    filed = client.post("/api/ner/incidents", json=_incident_payload(
        source="app", description="Slip across both lanes, filed from a phone"
    ))
    assert filed.status_code == 201
    incident_id = filed.get_json()["incident"]["id"]

    # The review queue is an unauthenticated read of the same table — exactly what the
    # website's Incident Review screen calls.
    queue = client.get("/api/ner/incidents?limit=200").get_json()["incidents"]
    match = next((i for i in queue if i["id"] == incident_id), None)
    assert match is not None, "a report filed from the app is missing from the review queue"
    assert match["source"] == "app"
    assert match["description"] == "Slip across both lanes, filed from a phone"


def test_an_offline_queue_flush_from_the_app_lands_in_the_same_queue(client):
    """The path a phone actually uses: a batch, hours later, over the sync endpoint."""
    batch = [
        _incident_payload(source="app", type="flood", severity=3),
        _incident_payload(source="app", type="road_block", severity=2),
    ]
    response = client.post("/api/ner/incidents/sync", json={"incidents": batch})
    assert response.status_code == 200
    assert response.get_json()["created"] == 2

    queue = client.get("/api/ner/incidents?limit=200").get_json()["incidents"]
    filed = {i["client_uuid"]: i for i in queue}
    for item in batch:
        assert filed[item["client_uuid"]]["source"] == "app"


def test_source_is_recorded_not_guessed(client):
    """An unmarked or unrecognised caller is "api" — never quietly relabelled as a client."""
    web = client.post("/api/ner/incidents", json=_incident_payload(source="web"))
    assert web.get_json()["incident"]["source"] == "web"

    unmarked = client.post("/api/ner/incidents", json=_incident_payload())
    assert unmarked.get_json()["incident"]["source"] == "api"

    # A bad value must not lose the report — where it came from is metadata, not content.
    nonsense = client.post("/api/ner/incidents", json=_incident_payload(source="pigeon"))
    assert nonsense.status_code == 201
    assert nonsense.get_json()["incident"]["source"] == "api"


def test_list_reports_the_true_total_not_the_page_size(client):
    """The field app's connection test asks for one report and shows the total.

    If `total` tracked the page limit, that check would read "1 report" against a database
    holding thousands, and a reporter pointed at the wrong backend would see nothing wrong.
    """
    body = client.get("/api/ner/incidents?limit=1").get_json()
    assert body["count"] == 1
    assert body["total"] > 1


def test_a_photograph_survives_being_stored(client):
    """A downscaled field photo arrives as a base64 data URI tens of thousands of characters
    long. It used to go into a VARCHAR(512), which SQLite ignores and PostgreSQL rejects —
    so every photographed report worked locally and failed on the shared database."""
    data_uri = "data:image/jpeg;base64," + ("A" * 60000)
    response = client.post("/api/ner/incidents", json=_incident_payload(image_url=data_uri))
    assert response.status_code == 201
    assert response.get_json()["incident"]["image_url"] == data_uri


def test_timestamps_carry_an_offset(client):
    """A naive ISO string is not UTC to a browser — it is local time.

    Every timestamp here is written as UTC, but SQLite has no timezone type and hands them
    back naive. Both clients parse these with `new Date(...)`, so an unstamped value made a
    report filed a minute ago read as "5 h ago" in the review queue — the one property a
    verifier judges a report by. PostgreSQL keeps the offset, so this only ever broke on the
    SQLite path, which is every local run and every demo.
    """
    from datetime import datetime, timezone

    body = client.post("/api/ner/incidents", json=_incident_payload()).get_json()["incident"]
    for field in ("reported_at", "created_at"):
        parsed = datetime.fromisoformat(body[field])
        assert parsed.tzinfo is not None, f"{field} has no offset"
        # And it must say UTC rather than merely saying something: a report just filed cannot
        # be hours old.
        assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 300
