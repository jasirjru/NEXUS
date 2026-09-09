"""Classical supervised baselines for entity classification.

Per the blueprint: implement strong classical baselines FIRST.
- Random Forest
- Gradient Boosting (sklearn)
- XGBoost (optional, graceful if not installed)
- LightGBM (optional, graceful if not installed)

All classifiers share a uniform interface so they can be compared in ablation
studies and used interchangeably in the risk engine.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from nexus.core.logging_setup import get_logger

log = get_logger("nexus.models.classifiers")


class BaseClassifier:
    """Uniform interface for supervised classifiers used by risk/ablation."""

    name: str = "base"

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "BaseClassifier":
        raise NotImplementedError

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Returns probability of class 1 (anomalous)."""
        raise NotImplementedError

    def score(self, X: pd.DataFrame) -> np.ndarray:
        """Alias for predict_proba for compatibility with detector interface."""
        return self.predict_proba(X)

    def get_params(self) -> dict[str, Any]:
        return {}


class RandomForestBaseline(BaseClassifier):
    """Random Forest with balanced class weights."""

    name = "random_forest"

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int | None = 10,
        random_state: int = 42,
    ) -> None:
        self.params = dict(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=random_state,
        )
        self.pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("rf", RandomForestClassifier(
                class_weight="balanced", **self.params,
            )),
        ])

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "RandomForestBaseline":
        self.pipe.fit(X.to_numpy(float), y.astype(int))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.pipe.predict_proba(X.to_numpy(float))[:, 1]

    def get_params(self) -> dict[str, Any]:
        rf = self.pipe.named_steps["rf"]
        return {
            **self.params,
            "feature_importances": dict(
                zip(
                    [f"f{i}" for i in range(len(rf.feature_importances_))],
                    rf.feature_importances_.round(4).tolist(),
                )
            ) if hasattr(rf, "feature_importances_") else {},
        }


class GradientBoostingBaseline(BaseClassifier):
    """Sklearn GradientBoostingClassifier baseline."""

    name = "gradient_boosting"

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int = 4,
        learning_rate: float = 0.1,
        random_state: int = 42,
    ) -> None:
        self.params = dict(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=random_state,
        )
        self.pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("gb", GradientBoostingClassifier(**self.params)),
        ])

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "GradientBoostingBaseline":
        self.pipe.fit(X.to_numpy(float), y.astype(int))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.pipe.predict_proba(X.to_numpy(float))[:, 1]

    def get_params(self) -> dict[str, Any]:
        gb = self.pipe.named_steps["gb"]
        return {
            **self.params,
            "feature_importances": dict(
                zip(
                    [f"f{i}" for i in range(len(gb.feature_importances_))],
                    gb.feature_importances_.round(4).tolist(),
                )
            ) if hasattr(gb, "feature_importances_") else {},
        }


class XGBoostBaseline(BaseClassifier):
    """XGBoost classifier; gracefully unavailable if xgboost not installed."""

    name = "xgboost"
    available = True

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int = 6,
        learning_rate: float = 0.1,
        random_state: int = 42,
    ) -> None:
        self.params = dict(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=random_state,
        )
        try:
            from xgboost import XGBClassifier
            self.pipe = Pipeline([
                ("scaler", StandardScaler()),
                ("xgb", XGBClassifier(
                    use_label_encoder=False,
                    eval_metric="logloss",
                    scale_pos_weight=1,  # will be set in fit()
                    **self.params,
                )),
            ])
        except ImportError:
            self.available = False
            log.info("xgboost not installed; XGBoostBaseline unavailable")

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "XGBoostBaseline":
        if not self.available:
            return self
        y = y.astype(int)
        # compute scale_pos_weight for class imbalance
        n_neg = int((y == 0).sum())
        n_pos = max(int((y == 1).sum()), 1)
        self.pipe.named_steps["xgb"].set_params(scale_pos_weight=n_neg / n_pos)
        self.pipe.fit(X.to_numpy(float), y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self.available:
            return np.full(len(X), 0.5)
        return self.pipe.predict_proba(X.to_numpy(float))[:, 1]

    def get_params(self) -> dict[str, Any]:
        return {**self.params, "available": self.available}


class LightGBMBaseline(BaseClassifier):
    """LightGBM classifier; gracefully unavailable if lightgbm not installed."""

    name = "lightgbm"
    available = True

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int = 6,
        learning_rate: float = 0.1,
        random_state: int = 42,
    ) -> None:
        self.params = dict(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=random_state,
        )
        try:
            from lightgbm import LGBMClassifier
            self.pipe = Pipeline([
                ("scaler", StandardScaler()),
                ("lgbm", LGBMClassifier(
                    is_unbalance=True,
                    verbose=-1,
                    **self.params,
                )),
            ])
        except ImportError:
            self.available = False
            log.info("lightgbm not installed; LightGBMBaseline unavailable")

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "LightGBMBaseline":
        if not self.available:
            return self
        self.pipe.fit(X.to_numpy(float), y.astype(int))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self.available:
            return np.full(len(X), 0.5)
        return self.pipe.predict_proba(X.to_numpy(float))[:, 1]

    def get_params(self) -> dict[str, Any]:
        return {**self.params, "available": self.available}


# ---------------------------------------------------------------- factory
ALL_CLASSIFIERS: dict[str, type[BaseClassifier]] = {
    "random_forest": RandomForestBaseline,
    "gradient_boosting": GradientBoostingBaseline,
    "xgboost": XGBoostBaseline,
    "lightgbm": LightGBMBaseline,
}


def get_available_classifiers() -> list[BaseClassifier]:
    """Instantiate all available classifiers."""
    result = []
    for cls in ALL_CLASSIFIERS.values():
        inst = cls()
        if getattr(inst, "available", True):
            result.append(inst)
    return result


def cross_validate_classifier(
    clf: BaseClassifier, X: pd.DataFrame, y: np.ndarray, n_splits: int = 3,
) -> dict[str, float]:
    """Stratified K-fold cross-validation returning mean ROC-AUC."""
    y = np.asarray(y).astype(int)
    if len(set(y)) < 2 or sum(y) < n_splits:
        return {"cv_roc_auc": float("nan"), "n_splits": 0}
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    aucs = []
    for train_idx, val_idx in skf.split(X, y):
        clf_clone = type(clf)()
        X_train, y_train = X.iloc[train_idx], y[train_idx]
        X_val, y_val = X.iloc[val_idx], y[val_idx]
        clf_clone.fit(X_train, y_train)
        probs = clf_clone.predict_proba(X_val)
        if len(set(y_val)) >= 2:
            aucs.append(float(roc_auc_score(y_val, probs)))
    return {"cv_roc_auc": float(np.mean(aucs)) if aucs else float("nan"), "n_splits": len(aucs)}
