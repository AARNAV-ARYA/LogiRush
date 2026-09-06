# tests/test_api_analytics.py
"""Analytics aggregates and model transparency endpoints."""

import pytest


@pytest.fixture(scope="module")
def client():
    from main import app

    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_analytics_distribution_covers_all_categories(client):
    body = client.get("/api/ner/analytics").get_json()
    assert body["status"] == "success"
    categories = [d["category"] for d in body["accessibility_distribution"]]
    assert categories == ["Excellent", "Good", "Moderate", "Poor", "Critical"]
    # Every segment must land in exactly one band.
    assert sum(d["count"] for d in body["accessibility_distribution"]) == body["total_segments"]


def test_analytics_state_breakdown_is_sorted_worst_first(client):
    body = client.get("/api/ner/analytics").get_json()
    scores = [s["average_accessibility"] for s in body["state_breakdown"]]
    assert scores == sorted(scores), "States should be ordered worst-accessibility first"
    assert all(0 <= s <= 100 for s in scores)
    assert all(s["segment_count"] > 0 for s in body["state_breakdown"])


def test_analytics_scatter_has_one_point_per_segment(client):
    body = client.get("/api/ner/analytics").get_json()
    assert len(body["risk_scatter"]) == body["total_segments"]
    point = body["risk_scatter"][0]
    assert {"id", "label", "accessibility", "disruption_percent", "impassable"} <= set(point)


def test_model_info_is_transparent_about_synthetic_training(client):
    body = client.get("/api/ner/model-info").get_json()
    assert body["status"] == "success"
    assert body["model_type"] in {"random_forest", "heuristic_fallback"}
    assert body["training"]["data"] == "synthetic"
    assert body["training"]["reproducible"] is True
    assert "not validated real-world" in body["training"]["warning"]
    # The AI usage policy boundaries must be stated explicitly.
    assert "route selection" in body["not_used_for"]
    assert "accessibility score calculation" in body["not_used_for"]


def test_model_info_reports_ranked_feature_importances(client):
    body = client.get("/api/ner/model-info").get_json()
    importances = body["feature_importances"]
    assert len(importances) == len(body["features"])
    values = [f["importance"] for f in importances]
    assert values == sorted(values, reverse=True), "Importances must be ranked highest first"


def test_plan_route_rejects_out_of_range_max_routes(client):
    response = client.post(
        "/api/ner/plan-route",
        json={"origin": "LOC001", "destination": "LOC016", "max_routes": 99},
    )
    assert response.status_code == 400


def test_plan_route_max_hours_constraint_can_make_a_trip_infeasible(client):
    """A tight time budget must be honoured, not silently ignored."""
    response = client.post(
        "/api/ner/plan-route",
        json={"origin": "LOC001", "destination": "LOC021", "max_hours": 0.5},
    )
    assert response.status_code == 200
    assert response.get_json()["routes"] == []
