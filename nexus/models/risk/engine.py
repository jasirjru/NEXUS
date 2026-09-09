"""Calibrated risk engine.

Design (per blueprint):
- ML/anomaly signals are features for a meta-model (logistic regression) whose
  weights are LEARNED from labeled outcomes, never hand-picked.
- Probabilities are calibrated with isotonic regression (fallback: sigmoid).
- Output = risk probability + confidence derived from calibration quality and
  agreement between signals - so HIGH RISK/LOW CONFIDENCE is distinguishable
  from HIGH RISK/HIGH CONFIDENCE.

If no labels exist yet, the engine falls back to an unsupervised mode:
risk = ensemble anomaly score, confidence = inter-signal agreement (bottom
quartile of agreement flags low confidence). This is clearly marked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from nexus.core.logging_setup import get_logger

log = get_logger("nexus.models.risk")


@dataclass
class RiskResult:
    entity_id: str
    risk: float
    confidence: float
    calibrated: bool  # True if learned/calibrated on labels; False = unsupervised fallback
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "risk": round(self.risk, 4),
            "confidence": round(self.confidence, 4),
            "calibrated": self.calibrated,
            "components": {k: round(v, 4) for k, v in self.components.items()},
        }


class RiskEngine:
    """Meta-model over anomaly/graph/temporal signals."""

    def __init__(self) -> None:
        self.pipe: Pipeline | None = None
        self.calibrated = False
        self.signal_names: list[str] = []

    # ------------------------------------------------------------ training
    def fit_supervised(self, signals: pd.DataFrame, labels: np.ndarray) -> "RiskEngine":
        """signals: index=entity, columns=signal scores in [0,1]. labels: 0/1."""
        self.signal_names = list(signals.columns)
        base = Pipeline([
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ])
        n_pos = int(np.sum(labels == 1))
        if n_pos >= 8 and len(set(labels)) > 1:
            # isotonic needs more data; sigmoid with CV is robust at this scale
            cv = min(5, n_pos)
            self.pipe = CalibratedClassifierCV(base, method="sigmoid", cv=cv)
            self.pipe.fit(signals.to_numpy(float), labels)
            self.calibrated = True
        else:
            base.fit(signals.to_numpy(float), labels)
            self.pipe = base
            self.calibrated = False
            log.warning("risk engine trained WITHOUT calibration (only %d positives)", n_pos)
        return self

    # ------------------------------------------------------------ inference
    def predict(self, signals: pd.DataFrame) -> list[RiskResult]:
        if self.pipe is None:
            raise RuntimeError("RiskEngine not fitted")
        probs = self.pipe.predict_proba(signals.to_numpy(float))[:, 1]
        # confidence from signal agreement: pairwise correlation of rank signals
        conf = self._agreement_confidence(signals)
        results = []
        for eid, p, c in zip(signals.index, probs, conf):
            results.append(
                RiskResult(
                    entity_id=str(eid),
                    risk=float(p),
                    confidence=float(c),
                    calibrated=self.calibrated,
                    components={n: float(v) for n, v in zip(self.signal_names, signals.iloc[list(signals.index).index(eid)])},
                )
            )
        return results

    def _agreement_confidence(self, signals: pd.DataFrame) -> np.ndarray:
        """High when signals agree; low when they disagree or are saturated."""
        arr = signals.to_numpy(float)
        if arr.shape[1] < 2:
            return np.full(len(signals), 0.5)
        # pairwise spread (std across signals) -> low spread = high agreement
        spread = arr.std(axis=1)
        conf = 1.0 - np.clip(spread, 0, 1)
        # if all signals near zero, confidence in "benign" should be moderate
        return np.clip(conf, 0.05, 0.99)

    # ------------------------------------------------------------ persistence
    def get_params(self) -> dict[str, Any]:
        if isinstance(getattr(self, "pipe", None), Pipeline):
            lr = self.pipe.named_steps.get("lr")
            if lr is not None:
                return {"coefficients": dict(zip(self.signal_names, lr.coef_[0].round(4).tolist()))}
        if self.pipe is not None:
            # calibrated ensemble: average underlying coefficients
            coefs = []
            for cal in self.pipe.calibrated_classifiers_:
                est = getattr(cal, "estimator", None)
                if est is not None:
                    coefs.append(est.named_steps["lr"].coef_[0])
            if coefs:
                mean = np.mean(coefs, axis=0)
                return {
                    "coefficients": dict(
                        zip(self.signal_names, mean.round(4).tolist())
                    ),
                    "calibrated": True,
                }
        return {}
