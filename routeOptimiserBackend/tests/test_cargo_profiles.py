# tests/test_cargo_profiles.py
import pytest

from src.modeling.cargo_profiles import (
    CARGO_PROFILES,
    OBJECTIVES,
    describe_priority_order,
    get_profile,
    get_weights,
    list_cargo_types,
)


@pytest.mark.parametrize("cargo_type", list(CARGO_PROFILES.keys()))
def test_every_profile_weights_sum_to_one(cargo_type):
    weights = get_weights(cargo_type)
    assert abs(sum(weights.values()) - 1.0) < 0.01
    assert set(weights.keys()) == set(OBJECTIVES)
    assert all(w >= 0 for w in weights.values())


def test_unknown_cargo_type_falls_back_to_general():
    assert get_profile("nonexistent-cargo")["label"] == CARGO_PROFILES["general"]["label"]


def test_medicine_prioritises_reliability_over_cost():
    # Spec: Medicine -> Reliability > Risk > Time > Cost
    order = describe_priority_order("medicine")
    assert order[0] == "reliability"
    assert order.index("risk") < order.index("time")
    assert order[-1] == "cost"


def test_perishable_prioritises_time_first():
    # Spec: Perishable -> Time > Reliability > Risk
    assert describe_priority_order("perishable")[0] == "time"


def test_relief_prioritises_risk_first():
    # Spec: Relief -> Risk > Reliability > Time
    assert describe_priority_order("relief")[0] == "risk"


def test_general_profile_is_balanced():
    weights = get_weights("general")
    assert len(set(weights.values())) == 1


def test_higher_urgency_increases_time_weight():
    low = get_weights("medicine", "low")["time"]
    normal = get_weights("medicine", "normal")["time"]
    critical = get_weights("medicine", "critical")["time"]
    assert low < normal < critical
    # Renormalisation must hold at every urgency level.
    assert abs(sum(get_weights("medicine", "critical").values()) - 1.0) < 0.01


def test_list_cargo_types_covers_all_spec_types():
    ids = {c["id"] for c in list_cargo_types()}
    assert {"general", "medicine", "food", "relief", "perishable"} <= ids
