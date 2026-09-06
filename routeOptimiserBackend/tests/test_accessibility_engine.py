# tests/test_accessibility_engine.py
import pytest

from src.modeling.accessibility_engine import (
    compute_accessibility_score,
    categorize_accessibility,
    assess_segment,
)


def test_all_zero_risk_is_perfect_score():
    assert compute_accessibility_score(0, 0, 0, 0, 0) == 100.0


def test_all_max_risk_is_zero_score():
    assert compute_accessibility_score(100, 100, 100, 100, 100) == 0.0


def test_formula_matches_spec_weights():
    # AccessibilityScore = 100 - (0.25*W + 0.30*L + 0.20*F + 0.15*I + 0.10*D)
    score = compute_accessibility_score(
        weather_risk=40, landslide_risk=80, flood_risk=20, incident_risk=15, delay_risk=35
    )
    expected = 100 - (0.25 * 40 + 0.30 * 80 + 0.20 * 20 + 0.15 * 15 + 0.10 * 35)
    assert score == round(expected, 2)


def test_landslide_has_highest_weight():
    # Two inputs with the same total risk "budget" but concentrated on landslide vs. delay
    # should score lower when concentrated on landslide, since it carries the highest weight.
    landslide_heavy = compute_accessibility_score(0, 50, 0, 0, 0)
    delay_heavy = compute_accessibility_score(0, 0, 0, 0, 50)
    assert landslide_heavy < delay_heavy


@pytest.mark.parametrize(
    "score,expected_category",
    [
        (100, "Excellent"),
        (80, "Excellent"),
        (79.9, "Good"),
        (60, "Good"),
        (59.9, "Moderate"),
        (40, "Moderate"),
        (39.9, "Poor"),
        (20, "Poor"),
        (19.9, "Critical"),
        (0, "Critical"),
    ],
)
def test_category_bands_match_spec(score, expected_category):
    assert categorize_accessibility(score) == expected_category


def test_out_of_range_inputs_are_clamped_not_rejected():
    # Community-reported / sensor-derived risk inputs may occasionally be out of range;
    # the engine should clamp rather than raise, so one bad input doesn't crash a request.
    score = compute_accessibility_score(-10, 150, 0, 0, 0)
    assert score == compute_accessibility_score(0, 100, 0, 0, 0)


def test_assess_segment_returns_score_category_and_inputs():
    result = assess_segment(
        weather_risk=40, landslide_risk=85, flood_risk=15, incident_risk=25, delay_risk=55
    )
    assert result.category == categorize_accessibility(result.score)
    assert result.inputs["landslide_risk"] == 85
