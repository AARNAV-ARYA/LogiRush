# tests/test_disaster_prediction.py
from src.modeling.disaster_prediction import (
    FEATURE_NAMES,
    HeuristicDisasterPredictor,
    generate_training_data,
    get_default_predictor,
)

SAFE_VALLEY = {
    "rainfall_mm_24h": 10,
    "forecast_rainfall_mm_48h": 15,
    "slope_gradient_deg": 3,
    "elevation_m": 80,
    "historical_landslides_5y": 0,
    "historical_floods_5y": 0,
    "road_vulnerability_index": 20,
    "recent_incident_count": 0,
}

DANGEROUS_HILL = {
    "rainfall_mm_24h": 180,
    "forecast_rainfall_mm_48h": 240,
    "slope_gradient_deg": 32,
    "elevation_m": 1500,
    "historical_landslides_5y": 18,
    "historical_floods_5y": 4,
    "road_vulnerability_index": 90,
    "recent_incident_count": 4,
}


def test_training_data_is_reproducible():
    a = generate_training_data(n_samples=200)
    b = generate_training_data(n_samples=200)
    assert a == b, "Seeded generation must be reproducible for auditability"


def test_training_data_shape_and_labels():
    X, y_flood, y_landslide = generate_training_data(n_samples=150)
    assert len(X) == len(y_flood) == len(y_landslide) == 150
    assert all(len(row) == len(FEATURE_NAMES) for row in X)
    # Labels must contain both classes, otherwise the model can't learn anything.
    assert set(y_flood) == {0, 1}
    assert set(y_landslide) == {0, 1}


def test_probabilities_are_in_range():
    predictor = get_default_predictor()
    p = predictor.predict(DANGEROUS_HILL)
    for value in (p.flood_probability, p.landslide_probability, p.combined_disruption_probability):
        assert 0.0 <= value <= 1.0


def test_dangerous_terrain_scores_higher_than_safe_terrain():
    predictor = get_default_predictor()
    safe = predictor.predict(SAFE_VALLEY)
    risky = predictor.predict(DANGEROUS_HILL)
    assert risky.landslide_probability > safe.landslide_probability
    assert risky.combined_disruption_probability > safe.combined_disruption_probability


def test_combined_probability_is_at_least_each_component():
    # Independence combination: 1-(1-a)(1-b) >= max(a, b)
    predictor = get_default_predictor()
    p = predictor.predict(DANGEROUS_HILL)
    assert p.combined_disruption_probability >= p.flood_probability - 1e-9
    assert p.combined_disruption_probability >= p.landslide_probability - 1e-9


def test_missing_features_do_not_raise():
    predictor = get_default_predictor()
    p = predictor.predict({})
    assert 0.0 <= p.combined_disruption_probability <= 1.0


def test_prediction_is_explainable():
    predictor = get_default_predictor()
    p = predictor.predict(DANGEROUS_HILL)
    assert p.top_drivers, "Every prediction must come with drivers for explainability"
    assert all({"feature", "value", "contribution"} <= set(d) for d in p.top_drivers)
    importances = predictor.feature_importances()
    assert set(importances.keys()) <= set(FEATURE_NAMES)


def test_heuristic_fallback_is_labelled_and_functional():
    p = HeuristicDisasterPredictor().predict(DANGEROUS_HILL)
    assert p.model_type == "heuristic_fallback"
    assert 0.0 <= p.combined_disruption_probability <= 1.0
