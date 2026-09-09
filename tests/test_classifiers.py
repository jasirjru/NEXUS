"""Tests for classical ML classifier baselines."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexus.models.classifiers.baselines import (
    GradientBoostingBaseline,
    RandomForestBaseline,
    XGBoostBaseline,
    LightGBMBaseline,
    get_available_classifiers,
    cross_validate_classifier,
)


def _make_data(n: int = 100, n_features: int = 10, seed: int = 42):
    rng = np.random.RandomState(seed)
    X = pd.DataFrame(rng.randn(n, n_features), columns=[f"f{i}" for i in range(n_features)])
    y = np.concatenate([np.zeros(n - 15), np.ones(15)]).astype(int)
    rng.shuffle(y)
    return X, y


class TestRandomForest:
    def test_fit_predict(self):
        X, y = _make_data()
        clf = RandomForestBaseline()
        clf.fit(X, y)
        probs = clf.predict_proba(X)
        assert probs.shape == (len(X),)
        assert 0 <= probs.min() and probs.max() <= 1

    def test_get_params(self):
        X, y = _make_data()
        clf = RandomForestBaseline()
        clf.fit(X, y)
        params = clf.get_params()
        assert "feature_importances" in params


class TestGradientBoosting:
    def test_fit_predict(self):
        X, y = _make_data()
        clf = GradientBoostingBaseline()
        clf.fit(X, y)
        probs = clf.predict_proba(X)
        assert probs.shape == (len(X),)
        assert 0 <= probs.min() and probs.max() <= 1


class TestXGBoost:
    def test_graceful_unavailable(self):
        clf = XGBoostBaseline()
        if not clf.available:
            probs = clf.predict_proba(pd.DataFrame(np.zeros((5, 3))))
            assert all(p == 0.5 for p in probs)


class TestLightGBM:
    def test_graceful_unavailable(self):
        clf = LightGBMBaseline()
        if not clf.available:
            probs = clf.predict_proba(pd.DataFrame(np.zeros((5, 3))))
            assert all(p == 0.5 for p in probs)


class TestFactory:
    def test_get_available(self):
        classifiers = get_available_classifiers()
        # At minimum RF and GBDT are always available (sklearn)
        names = [c.name for c in classifiers]
        assert "random_forest" in names
        assert "gradient_boosting" in names

    def test_cross_validate(self):
        X, y = _make_data()
        clf = RandomForestBaseline()
        result = cross_validate_classifier(clf, X, y, n_splits=2)
        assert "cv_roc_auc" in result
        assert result["n_splits"] == 2
