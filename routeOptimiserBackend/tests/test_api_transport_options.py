"""
End-to-end checks that weight actually reaches the planner and changes the answer.

These go through the real HTTP layer because the reported defect was user-visible: the
planner screen showed the same rate no matter what weight was typed in.
"""

import pytest

from main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def plan(client, **overrides):
    payload = {
        "origin": "LOC001",
        "destination": "LOC012",
        "cargo_type": "relief",
        "urgency": "normal",
        "weight_kg": 1000,
    }
    payload.update(overrides)
    response = client.post("/api/ner/plan-route", json=payload)
    return response, response.get_json()


def test_plan_route_accepts_weight(client):
    response, body = plan(client)
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["weight_kg"] == 1000


def test_different_weights_give_different_prices(client):
    _, light = plan(client, weight_kg=200)
    _, heavy = plan(client, weight_kg=8000)
    assert (
        light["recommended_route"]["estimated_cost_inr"]
        != heavy["recommended_route"]["estimated_cost_inr"]
    ), "weight is being ignored in pricing again"
    assert (
        heavy["recommended_route"]["estimated_cost_inr"]
        > light["recommended_route"]["estimated_cost_inr"]
    )


def test_ten_kilo_difference_is_visible(client):
    _, a = plan(client, weight_kg=2000)
    _, b = plan(client, weight_kg=2010)
    assert (
        a["recommended_route"]["estimated_cost_inr"]
        != b["recommended_route"]["estimated_cost_inr"]
    )


def test_response_exposes_transport_options(client):
    _, body = plan(client, weight_kg=5000)
    options = body["transport_options"]
    assert options, "no transport options returned"
    assert body["recommended_transport"]
    feasible = [o for o in options if o["feasible"]]
    assert feasible
    for o in feasible:
        assert o["cost_inr"] > 0
        assert o["eta_hours"] > 0
        assert o["vehicles"] >= 1
        assert o["why"], "every option must explain itself"


def test_infeasible_modes_explain_why(client):
    """Aizawl has no railhead, so rail must be listed as unavailable with a reason."""
    _, body = plan(client, destination="LOC012", weight_kg=5000)
    rail = next(o for o in body["transport_options"] if o["mode"] == "rail")
    assert rail["feasible"] is False
    assert "railhead" in rail["reason"].lower()
    assert rail["blocker"] == "infrastructure"


def test_bulk_consignment_between_railheads_prefers_rail(client):
    """40 tonnes Guwahati to Dibrugarh: rail should beat road on a cargo profile that
    cares about cost and reliability."""
    _, body = plan(
        client, origin="LOC002", destination="LOC006", weight_kg=40000, cargo_type="relief"
    )
    assert body["recommended_transport"] in {"rail", "waterway"}


def test_small_urgent_medicine_can_justify_airlift(client):
    _, body = plan(
        client,
        origin="LOC002",
        destination="LOC012",
        weight_kg=250,
        cargo_type="medicine",
        urgency="critical",
    )
    modes = [o["mode"] for o in body["transport_options"] if o["feasible"]]
    assert "air_heli" in modes


def test_routine_shipment_does_not_recommend_airlift(client):
    """Cost sanity: a normal-urgency general load must not be sent by helicopter."""
    _, body = plan(
        client,
        origin="LOC002",
        destination="LOC012",
        weight_kg=250,
        cargo_type="general",
        urgency="low",
    )
    assert body["recommended_transport"] != "air_heli"


def test_vehicle_classes_can_take_different_routes(client):
    """The point of pruning per mode: a heavy truck may be routed differently from a pickup."""
    _, body = plan(client, origin="LOC001", destination="LOC012", weight_kg=3000)
    road = {
        o["mode"]: tuple(o["path_names"])
        for o in body["transport_options"]
        if o["feasible"] and o["network"] == "road"
    }
    assert len(set(road.values())) > 1, "all road classes took an identical route"


def test_weight_sensitivity_explains_next_threshold(client):
    _, body = plan(client, weight_kg=5000)
    sens = body["weight_sensitivity"]
    assert sens["next_vehicle_at_kg"] > 5000
    assert sens["step_increase_inr"] > 0
    assert sens["summary"]
    assert sens["cost_curves"]


def test_invalid_weight_rejected(client):
    for bad in [0, -10, "heavy"]:
        response, body = plan(client, weight_kg=bad)
        assert response.status_code == 400, f"{bad} should be rejected"
        assert body["status"] == "error"


def test_weight_defaults_when_omitted(client):
    response = client.post(
        "/api/ner/plan-route",
        json={"origin": "LOC001", "destination": "LOC012", "cargo_type": "relief"},
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["weight_kg"] > 0


def test_transport_modes_endpoint(client):
    response = client.get("/api/ner/transport-modes")
    body = response.get_json()
    assert response.status_code == 200
    assert body["count"] >= 8
    ids = {m["id"] for m in body["modes"]}
    assert {"pickup", "truck", "rail", "waterway", "air_heli", "porter"} <= ids
