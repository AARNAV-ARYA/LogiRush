"""
Weight-aware pricing and multimodal option tests.

The bug these exist to prevent: before this feature, cost was `distance * flat_rate`, so a
100 kg consignment and a 10 tonne consignment on the same corridor were quoted the identical
price. Anything here that stops failing means that regression has come back.
"""

import pytest

from src.modeling.transport_modes import (
    TRANSPORT_MODES,
    cost_breakdown,
    duration_hours,
    list_modes,
    mode_serves,
    next_capacity_threshold,
    vehicles_required,
)


# ----------------------------------------------------------------- pricing model


def test_cost_increases_with_weight_on_same_route():
    """The headline defect: two different weights must not produce the same price."""
    light = cost_breakdown(100, 500, "truck")["total_inr"]
    heavy = cost_breakdown(5000, 500, "truck")["total_inr"]
    assert heavy > light


def test_small_weight_difference_changes_price():
    """x kg and x+10 kg must differ - the user-visible symptom of the old flat rate."""
    a = cost_breakdown(1000, 400, "lcv")["total_inr"]
    b = cost_breakdown(1010, 400, "lcv")["total_inr"]
    assert b > a


def test_cost_is_monotonic_in_weight():
    previous = 0.0
    for weight in [50, 200, 900, 1000, 2500, 5000, 9000, 12000, 30000]:
        total = cost_breakdown(weight, 300, "truck")["total_inr"]
        assert total > previous, f"cost fell going up to {weight} kg"
        previous = total


def test_cost_steps_at_capacity_boundary():
    """Crossing a vehicle's capacity adds a whole vehicle, so the price jumps."""
    capacity = TRANSPORT_MODES["truck"]["capacity_kg"]
    under = cost_breakdown(capacity, 400, "truck")
    over = cost_breakdown(capacity + 1, 400, "truck")
    assert under["vehicles"] == 1
    assert over["vehicles"] == 2
    assert over["total_inr"] > under["total_inr"] * 1.5


def test_cost_scales_with_distance():
    near = cost_breakdown(2000, 100, "truck")["total_inr"]
    far = cost_breakdown(2000, 1000, "truck")["total_inr"]
    assert far > near


def test_cost_breakdown_components_sum_to_total():
    b = cost_breakdown(7500, 620, "truck")
    parts = b["dispatch_inr"] + b["running_inr"] + b["haulage_inr"] + b["handling_inr"]
    assert parts == pytest.approx(b["total_inr"], rel=1e-6)


def test_per_tonne_cost_falls_with_consolidation():
    """Economies of scale: filling a vehicle is cheaper per tonne than half-filling it."""
    half = cost_breakdown(4500, 500, "truck")["cost_per_tonne_inr"]
    full = cost_breakdown(9000, 500, "truck")["cost_per_tonne_inr"]
    assert full < half


def test_vehicles_required_rounds_up():
    assert vehicles_required(1, "truck") == 1
    assert vehicles_required(9000, "truck") == 1
    assert vehicles_required(9001, "truck") == 2
    assert vehicles_required(18000, "truck") == 2
    assert vehicles_required(18001, "truck") == 3


def test_capacity_threshold_reports_headroom():
    t = next_capacity_threshold(7000, "truck")
    assert t["vehicles"] == 1
    assert t["headroom_kg"] == 2000
    assert t["next_vehicle_at_kg"] == 9001


# ----------------------------------------------------------------- mode characteristics


def test_bulk_modes_are_cheaper_per_tonne_than_air():
    rail = cost_breakdown(30000, 400, "rail")["cost_per_tonne_inr"]
    air = cost_breakdown(30000, 400, "air_heli")["cost_per_tonne_inr"]
    assert rail < air


def test_air_is_faster_than_road_for_same_distance():
    assert duration_hours(500, "air_heli") < duration_hours(500, "truck", road_hours=14)


def test_heavier_vehicle_classes_need_better_roads():
    """This ordering is what makes vehicle classes take different routes."""
    assert (
        TRANSPORT_MODES["pickup"]["min_accessibility"]
        < TRANSPORT_MODES["lcv"]["min_accessibility"]
        < TRANSPORT_MODES["truck"]["min_accessibility"]
        < TRANSPORT_MODES["multi_axle"]["min_accessibility"]
    )


def test_porter_and_air_ignore_road_quality():
    """The modes that exist precisely for cut-off places must not be gated on road score."""
    assert TRANSPORT_MODES["porter"]["min_accessibility"] == 0
    assert TRANSPORT_MODES["air_heli"]["min_accessibility"] == 0


def test_rail_only_serves_railheads():
    assert mode_serves("LOC002", "LOC006", "rail")       # Guwahati - Dibrugarh
    assert not mode_serves("LOC002", "LOC012", "rail")   # Aizawl has no railhead


def test_waterway_only_serves_river_terminals():
    assert mode_serves("LOC002", "LOC006", "waterway")   # both on the Brahmaputra
    assert not mode_serves("LOC002", "LOC016", "waterway")  # Imphal is not a river port


def test_road_modes_serve_any_pair():
    for mode_id in ["pickup", "lcv", "truck", "multi_axle", "porter"]:
        assert mode_serves("LOC001", "LOC027", mode_id)


def test_list_modes_exposes_rate_card():
    modes = list_modes()
    assert len(modes) == len(TRANSPORT_MODES)
    for m in modes:
        assert m["rate_card"]["per_km_per_vehicle_inr"] > 0
        assert m["capacity_kg"] > 0
        assert m["note"]
    # ordered lightest first so the UI can present a natural progression
    assert modes[0]["capacity_kg"] <= modes[-1]["capacity_kg"]
