"""ML tests: detectors, risk engine calibration, evaluation metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexus.evaluation.metrics import calibration_metrics, classification_metrics, ranking_metrics
from nexus.models.anomaly.detectors import (
    AnomalyEnsemble,
    IsolationForestDetector,
    LOFDetector,
    RobustZScore,
)
from nexus.models.risk.engine import RiskEngine


def _synthetic(n_normal=300, n_anom=20, seed=7):
    rng = np.random.default_rng(seed)
    normal = rng.normal(0, 1, size=(n_normal, 6))
    # isolated extreme outliers: each anomaly is extreme on ONE feature alone.
    # (Clustered anomalies would be invisible to LOF by design - local density
    # is only computed relative to neighbors - so isolated points are the fair
    # unsupervised-detection scenario.)
    anom = rng.normal(0, 1, size=(n_anom, 6))
    for i in range(n_anom):
        anom[i, i % 6] += (18 + i) * (1 if i % 2 else -1)
    X = pd.DataFrame(np.vstack([normal, anom]), columns=[f"f{i}" for i in range(6)])
    y = np.array([0] * n_normal + [1] * n_anom)
    return X, y


def test_detectors_rank_anomalies_on_top():
    X, y = _synthetic()
    for det in [RobustZScore(), IsolationForestDetector(), LOFDetector()]:
        det.fit(X)
        s = det.score(X)
        assert s.min() >= 0.0 and s.max() <= 1.0
        # mean score of true anomalies should exceed normals
        assert s[y == 1].mean() > s[y == 0].mean()


def test_ensemble_beats_random():
    X, y = _synthetic()
    ens = AnomalyEnsemble()
    ens.fit(X)
    s = ens.score(X)
    m = classification_metrics(y, s)
    assert m["roc_auc"] > 0.9


def test_risk_engine_calibrated_output():
    X, y = _synthetic()
    # give the risk engine more positives by oversampling anomalies
    idx_pos = np.where(y == 1)[0]
    idx = np.concatenate([np.where(y == 0)[0][:200], np.tile(idx_pos, 2)])
    engine = RiskEngine()
    engine.fit_supervised(X.iloc[idx], y[idx])
    results = engine.predict(X)
    assert all(0.0 <= r.risk <= 1.0 for r in results)
    assert all(0.0 <= r.confidence <= 1.0 for r in results)
    assert engine.calibrated  # enough positives -> calibration active


def test_metrics_ranges():
    y = np.array([0, 0, 0, 1, 1, 1, 0, 1])
    s = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9, 0.15, 0.6])
    cm = classification_metrics(y, s)
    assert 0 <= cm["f1"] <= 1 and 0 <= cm["roc_auc"] <= 1
    rm = ranking_metrics(y, s, k_values=(3,))
    assert rm["precision_at_3"] >= 0
    cal = calibration_metrics(y, s / 1.2)
    assert 0 <= cal["brier"] <= 1
    assert len(cal["calibration_curve"]["bins"]) > 0
