# tests/test_model_evaluation.py
"""The model evaluation must be correct arithmetic and must never overclaim.

Runs on a reduced sample so the suite stays fast; the full report is produced by
`python evaluate_models.py`.
"""

import csv
import os
import random
import tempfile

import pytest

from src.modeling import model_evaluation as me
from src.modeling.disaster_prediction import FEATURE_NAMES


@pytest.fixture(scope="module")
def report():
    return me.evaluate_synthetic(n_samples=1200, folds=3)


def test_metrics_match_scikit_learn():
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    rng = random.Random(3)
    y = [rng.randint(0, 1) for _ in range(400)]
    p = [round(rng.random(), 2) for _ in range(400)]
    assert me._roc_auc(y, p) == pytest.approx(roc_auc_score(y, p))
    assert me._brier(y, p) == pytest.approx(brier_score_loss(y, p))
    assert me._log_loss(y, p) == pytest.approx(log_loss(y, p))


def test_split_is_stratified_and_disjoint():
    y = [1] * 100 + [0] * 300
    train, test = me._stratified_split(y, 0.25, 1)
    assert not set(train) & set(test)
    assert sum(y[i] for i in test) == 25 and len(test) == 100


def test_the_forest_beats_no_skill_but_never_the_oracle(report):
    for target in ("flood", "landslide"):
        r = report["targets"][target]
        assert r["holdout"]["brier"] < r["holdout"]["brier_no_skill"]
        assert r["holdout"]["roc_auc"] > 0.6
        # The oracle generated the labels; a model beating it by more than noise is a leak.
        assert r["holdout"]["roc_auc"] <= r["oracle_holdout"]["roc_auc"] + 0.03
        assert len(r["cross_validation"]["folds"]) == 3


def test_every_report_says_it_is_synthetic(report):
    assert report["data"] == "synthetic"
    assert "not evidence of real-world" in report["caveat"]
    assert report["interpretation"][-1] == me.SYNTHETIC_CAVEAT


def test_evaluation_on_real_events_file_is_scored():
    rng = random.Random(5)
    path = os.path.join(tempfile.mkdtemp(), "events.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FEATURE_NAMES + ["flood_event", "landslide_event"])
        for _ in range(60):
            w.writerow([round(rng.uniform(0, 150), 1) for _ in FEATURE_NAMES] + [rng.randint(0, 1), rng.randint(0, 1)])
    out = me.evaluate_on_events(path)
    assert out["data"] == "real events" and out["rows"] == 60
    assert set(out["targets"]) == {"flood", "landslide"}


def test_events_file_missing_features_is_rejected():
    path = os.path.join(tempfile.mkdtemp(), "bad.csv")
    with open(path, "w") as f:
        f.write("rainfall_mm_24h,flood_event\n10,1\n")
    with pytest.raises(ValueError):
        me.evaluate_on_events(path)
