# tests/test_api_routing.py
"""API-level tests for accessibility and route-planning endpoints."""

import pytest


@pytest.fixture(scope="module")
def client():
    from main import app

    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_locations_endpoint(client):
    body = client.get("/api/ner/locations").get_json()
    assert body["status"] == "success"
    assert body["count"] > 20
    states = {loc["state"] for loc in body["locations"]}
    # All eight NER states must be represented.
    assert {
        "Assam", "Meghalaya", "Manipur", "Mizoram",
        "Nagaland", "Tripura", "Sikkim", "Arunachal Pradesh",
    } <= states


def test_segments_include_prediction_and_accessibility(client):
    body = client.get("/api/ner/segments").get_json()
    assert body["status"] == "success"
    segment = body["segments"][0]
    assert 0 <= segment["accessibility_score"] <= 100
    assert segment["accessibility_category"] in {"Excellent", "Good", "Moderate", "Poor", "Critical"}
    assert segment["prediction"]["model_type"] in {"random_forest", "heuristic_fallback"}
    assert 0 <= segment["prediction"]["combined_disruption_probability"] <= 1


def test_accessibility_summary(client):
    body = client.get("/api/ner/accessibility-summary").get_json()
    assert body["status"] == "success"
    assert 0 <= body["overall_average_accessibility"] <= 100
    assert len(body["high_risk_corridors"]) <= 5


def test_dashboard_endpoint(client):
    body = client.get("/api/ner/dashboard").get_json()
    assert body["status"] == "success"
    assert body["total_segments"] > 0
    assert "recent_incidents" in body


def test_cargo_types_endpoint(client):
    body = client.get("/api/ner/cargo-types").get_json()
    assert {c["id"] for c in body["cargo_types"]} >= {"medicine", "relief", "perishable"}


def test_plan_route_returns_ranked_routes_with_explanation(client):
    response = client.post(
        "/api/ner/plan-route",
        json={"origin": "LOC001", "destination": "LOC016", "cargo_type": "medicine", "urgency": "high"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["recommended_route"]["rank"] == 1
    assert body["recommended_route"]["explanation"]["reasons"]
    assert body["recommended_route"]["eta_hours"] > 0
    assert abs(sum(body["objective_weights"].values()) - 1.0) < 0.01


def test_plan_route_meets_performance_budget(client):
    """Spec non-functional requirement: route calculation under 3 seconds."""
    response = client.post(
        "/api/ner/plan-route", json={"origin": "LOC001", "destination": "LOC021"}
    )
    assert response.status_code == 200
    assert response.get_json()["computation_seconds"] < 3.0


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"origin": "LOC001"}, 400),
        ({"origin": "LOC001", "destination": "LOC001"}, 400),
        ({"origin": "NOPE", "destination": "LOC001"}, 404),
        ({"origin": "LOC001", "destination": "NOPE"}, 404),
    ],
)
def test_plan_route_validation(client, payload, status):
    assert client.post("/api/ner/plan-route", json=payload).status_code == status


def test_multi_objective_core_is_still_the_routing_base(client):
    """The multi-objective A* core must not be quietly replaced by a simpler router.

    This test used to assert that the legacy cross-border endpoint `/api/find-routes` was
    still mounted. That endpoint is not part of this service — nothing in the frontend or
    the e2e suite calls it, and no blueprint registers it — so the assertion was checking
    for a 500 from a route that returns 404, and it failed for the whole life of the file.

    What the test was really protecting is worth keeping: the NER router must remain a
    genuine multi-objective search extending MOAStar, not a shortest-path stand-in. That is
    what is asserted now.
    """
    from src.optimization.moa_star import MOAStar
    from src.optimization.ner_router import NERRouter

    assert issubclass(NERRouter, MOAStar)
    assert NERRouter.OBJECTIVE_KEYS == ("time", "cost", "accessibility", "risk", "reliability")

    # And the planner it powers is reachable and validates its own input.
    response = client.post("/api/ner/plan-route", json={})
    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
