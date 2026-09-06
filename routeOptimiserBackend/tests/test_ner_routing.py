# tests/test_ner_routing.py
"""Tests for the NER graph, risk-aware router, and the guarantee that extending MOAStar
did not change the original cross-border behaviour."""

import pytest

from src.data_processing.ner_data_provider import MockNERDataProvider
from src.data_processing.ner_graph_builder import NERGraphBuilder
from src.modeling.cargo_profiles import get_weights
from src.optimization.moa_star import MOAStar
from src.optimization.ner_router import NERRouter, build_route_response
from src.services.accessibility_service import AccessibilityService


@pytest.fixture(scope="module")
def assessed():
    return AccessibilityService(provider=MockNERDataProvider()).assess_all_segments()


@pytest.fixture(scope="module")
def graph(assessed):
    return NERGraphBuilder().build(assessed_segments=assessed)


def test_original_moastar_objectives_unchanged():
    """The cross-border optimiser must still declare exactly its original four objectives."""
    assert MOAStar.OBJECTIVE_KEYS == ("time", "cost", "emissions", "customs")


def test_ner_router_declares_five_objectives():
    assert NERRouter.OBJECTIVE_KEYS == ("time", "cost", "accessibility", "risk", "reliability")


def test_graph_has_nodes_and_bidirectional_edges(graph):
    assert graph.number_of_nodes() > 20
    assert graph.number_of_edges() > 20
    # Roads are two-way: if A->B exists, B->A must too.
    for u, v in list(graph.edges())[:20]:
        assert graph.has_edge(v, u)


def test_impassable_segments_excluded_from_graph(assessed, graph):
    impassable_ids = {s["id"] for s in assessed if s["impassable"]}
    if not impassable_ids:
        pytest.skip("No impassable segments in current sample data")
    edge_segment_ids = {d.get("segment_id") for _, _, d in graph.edges(data=True)}
    assert not (impassable_ids & edge_segment_ids)


def test_route_found_between_connected_locations(graph):
    router = NERRouter(graph, weights=get_weights("general"))
    route = router.find_route("LOC001", "LOC016")
    assert route is not None
    assert route["path"][0] == "LOC001"
    assert route["path"][-1] == "LOC016"


def test_alternatives_are_distinct_and_ranked(graph):
    router = NERRouter(graph, weights=get_weights("general"))
    routes = router.find_routes("LOC001", "LOC007", max_routes=3)
    assert len(routes) >= 2
    paths = [tuple(r["path"]) for r in routes]
    assert len(paths) == len(set(paths)), "Alternatives must be distinct routes"
    scores = [r["score"] for r in routes]
    assert scores == sorted(scores), "Routes must be ranked best-first by true score"


def test_bottleneck_semantics_for_risk(graph):
    """Risk/accessibility/reliability are bottleneck (max) objectives, not sums.

    A route's risk score must equal its single worst segment, never the total, otherwise
    longer routes would be unfairly penalised and cargo weights would stop mattering.
    """
    router = NERRouter(graph, weights=get_weights("general"))
    route = router.find_route("LOC001", "LOC016")
    per_edge_risk = [e["obj_risk"] for e in route["edges"]]
    assert route["costs"]["risk"] == pytest.approx(max(per_edge_risk))
    assert route["costs"]["accessibility"] == pytest.approx(
        max(e["obj_accessibility"] for e in route["edges"])
    )


def test_cargo_profile_changes_selected_route(graph):
    """Module 4 must have a real effect: a time-critical perishable run and a risk-averse
    relief run should not always pick the same corridor."""
    perishable = NERRouter(graph, weights=get_weights("perishable", "critical")).find_route("LOC002", "LOC007")
    relief = NERRouter(graph, weights=get_weights("relief", "normal")).find_route("LOC002", "LOC007")
    assert perishable is not None and relief is not None
    assert perishable["path"] != relief["path"], (
        "Cargo profiles should select different corridors when a genuine "
        "speed-versus-safety trade-off exists"
    )


def test_perishable_is_faster_and_relief_is_safer(graph):
    perishable = NERRouter(graph, weights=get_weights("perishable", "critical")).find_route("LOC002", "LOC007")
    relief = NERRouter(graph, weights=get_weights("relief", "normal")).find_route("LOC002", "LOC007")
    assert perishable["total_hours"] <= relief["total_hours"]
    assert relief["costs"]["risk"] <= perishable["costs"]["risk"]


def test_route_response_includes_explanation(graph):
    router = NERRouter(graph, weights=get_weights("medicine"))
    route = router.find_route("LOC001", "LOC016")
    response = build_route_response(route, graph, "medicine", "normal")
    assert response["explanation"]["reasons"]
    assert response["explanation"]["caveat"], "Results must be framed as recommendations"
    assert response["eta_hours"] > 0
    assert response["total_distance_km"] > 0


def test_unknown_nodes_return_none(graph):
    router = NERRouter(graph, weights=get_weights("general"))
    assert router.find_route("NOPE", "LOC001") is None
