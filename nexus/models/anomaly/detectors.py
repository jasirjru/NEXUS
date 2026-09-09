"""Anomaly detectors with a unified fit/score interface.

Hierarchy (per blueprint: baselines first):
- RobustZScore: statistical baseline (median/MAD-based) per feature
- IsolationForestDetector, LOFDetector: sklearn unsupervised
- AutoencoderDetector: torch if available, else skipped gracefully
- AnomalyEnsemble: rank-average of member scores -> score in [0,1]

All scores are oriented so HIGHER = MORE ANOMALOUS, and normalized to [0,1]
via empirical ranking so different models are comparable.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import RobustScaler

from nexus.core.logging_setup import get_logger

log = get_logger("nexus.models.anomaly")


def _rank01(x: np.ndarray) -> np.ndarray:
    """Map raw scores to [0,1] by empirical CDF (ties handled by rank)."""
    r = pd.Series(x).rank(method="average").to_numpy()
    return (r - 0.5) / max(len(r), 1)


class BaseDetector:
    name: str = "base"

    def fit(self, X: pd.DataFrame) -> "BaseDetector":
        raise NotImplementedError

    def score(self, X: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

    def get_params(self) -> dict[str, Any]:
        return {}


class RobustZScore(BaseDetector):
    """Statistical baseline: max robust z-score across features (MAD-scaled)."""

    name = "robust_zscore"

    def __init__(self) -> None:
        self.scaler = RobustScaler(quantile_range=(25.0, 75.0))
        self.median: np.ndarray | None = None
        self.iqr: np.ndarray | None = None

    def fit(self, X: pd.DataFrame) -> "RobustZScore":
        arr = X.to_numpy(float)
        self.median = np.median(arr, axis=0)
        q25, q75 = np.percentile(arr, [25, 75], axis=0)
        self.iqr = np.maximum(q75 - q25, 1e-9)
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        arr = X.to_numpy(float)
        z = np.abs((arr - self.median) / self.iqr)
        return _rank01(np.nanmax(np.where(np.isfinite(z), z, 0.0), axis=1))

    def get_params(self) -> dict[str, Any]:
        return {"type": "robust_zscore_mad"}


class IsolationForestDetector(BaseDetector):
    name = "iforest"

    def __init__(self, n_estimators: int = 200, contamination: float = 0.03,
                 random_state: int = 42) -> None:
        self.params = dict(n_estimators=n_estimators, contamination=contamination,
                           random_state=random_state)
        self.model = IsolationForest(**self.params)

    def fit(self, X: pd.DataFrame) -> "IsolationForestDetector":
        self.model.fit(X.to_numpy(float))
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        raw = -self.model.score_samples(X.to_numpy(float))  # higher = more anomalous
        return _rank01(raw)

    def get_params(self) -> dict[str, Any]:
        return dict(self.params)


class LOFDetector(BaseDetector):
    name = "lof"

    def __init__(self, n_neighbors: int = 20) -> None:
        self.n_neighbors = n_neighbors
        self.model = LocalOutlierFactor(n_neighbors=n_neighbors, novelty=True)

    def fit(self, X: pd.DataFrame) -> "LOFDetector":
        self.model.fit(X.to_numpy(float))
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        raw = -self.model.score_samples(X.to_numpy(float))
        return _rank01(raw)

    def get_params(self) -> dict[str, Any]:
        return {"n_neighbors": self.n_neighbors}


class AutoencoderDetector(BaseDetector):
    """PyTorch autoencoder if torch is installed; otherwise unavailable."""

    name = "autoencoder"
    available = True

    def __init__(self, epochs: int = 30, lr: float = 1e-3, random_state: int = 42) -> None:
        self.epochs = epochs
        self.lr = lr
        self.random_state = random_state
        try:
            import torch

            self.torch = torch
        except ImportError:
            self.available = False
            return
        from sklearn.preprocessing import MinMaxScaler

        self.scaler = MinMaxScaler()

    def _build(self, dim: int):
        torch = self.torch
        torch.manual_seed(self.random_state)

        class AE(torch.nn.Module):
            def __init__(self, d: int):
                super().__init__()
                self.enc = torch.nn.Sequential(
                    torch.nn.Linear(d, max(d // 2, 4)), torch.nn.ReLU(),
                    torch.nn.Linear(max(d // 2, 4), max(d // 4, 2)),
                )
                self.dec = torch.nn.Sequential(
                    torch.nn.Linear(max(d // 4, 2), max(d // 2, 4)), torch.nn.ReLU(),
                    torch.nn.Linear(max(d // 2, 4), d),
                )

            def forward(self, x):
                return self.dec(self.enc(x))

        return AE(dim)

    def fit(self, X: pd.DataFrame) -> "AutoencoderDetector":
        if not self.available:
            return self
        torch = self.torch
        arr = self.scaler.fit_transform(X.to_numpy(float))
        model = self._build(arr.shape[1])
        opt = torch.optim.Adam(model.parameters(), lr=self.lr)
        lossf = torch.nn.MSELoss()
        xt = torch.tensor(arr, dtype=torch.float32)
        model.train()
        for _ in range(self.epochs):
            opt.zero_grad()
            loss = lossf(model(xt), xt)
            loss.backward()
            opt.step()
        self.model = model.eval()
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        if not self.available:
            return np.zeros(len(X))
        torch = self.torch
        arr = self.scaler.transform(X.to_numpy(float))
        with torch.no_grad():
            recon = self.model(torch.tensor(arr, dtype=torch.float32)).numpy()
        err = ((arr - recon) ** 2).mean(axis=1)
        return _rank01(err)

    def get_params(self) -> dict[str, Any]:
        return {"epochs": self.epochs, "lr": self.lr, "available": self.available}


class AnomalyEnsemble(BaseDetector):
    """Rank-average of member detector scores; robust to single-model quirks."""

    name = "ensemble"

    def __init__(self, detectors: list[BaseDetector] | None = None) -> None:
        self.detectors = detectors or [
            RobustZScore(),
            IsolationForestDetector(),
            LOFDetector(),
            AutoencoderDetector(),
        ]
        self.active = [d for d in self.detectors if getattr(d, "available", True)]

    def fit(self, X: pd.DataFrame) -> "AnomalyEnsemble":
        for d in self.active:
            d.fit(X)
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        scores = [d.score(X) for d in self.active]
        return np.mean(np.vstack(scores), axis=0)

    def member_scores(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        return {d.name: d.score(X) for d in self.active}

    def get_params(self) -> dict[str, Any]:
        return {"members": [d.name for d in self.active]}
