"""Change-point detection for temporal behavioral shifts.

Algorithms:
- CUSUM (Cumulative Sum): classic statistical method that detects shifts in
  the mean of a time series by accumulating deviations from a target level.
- Bayesian Online Change-Point Detection (simplified): maintains a run-length
  distribution and detects when the posterior probability of a changepoint
  exceeds a threshold.

Both algorithms are streaming-friendly and work on per-entity time series
(e.g. inter-transaction intervals, rolling volume).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from nexus.core.logging_setup import get_logger

log = get_logger("nexus.models.forecasting.changepoint")


@dataclass
class ChangePoint:
    """A detected change-point in a time series."""
    index: int
    timestamp: datetime | None
    score: float  # severity of the change
    direction: str  # "increase" | "decrease"
    method: str  # "cusum" | "bayesian"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "score": round(self.score, 4),
            "direction": self.direction,
            "method": self.method,
        }


@dataclass
class ChangePointResult:
    """Result of change-point detection on an entity's time series."""
    entity_id: str
    changepoints: list[ChangePoint] = field(default_factory=list)
    summary_score: float = 0.0  # aggregate score: 0 = no change, 1 = major change

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "changepoints": [cp.to_dict() for cp in self.changepoints],
            "summary_score": round(self.summary_score, 4),
        }


# ---------------------------------------------------------------- CUSUM
class CUSUMDetector:
    """Cumulative Sum (CUSUM) change-point detector.

    Monitors cumulative deviation from a reference mean. When the cumulative
    sum exceeds a threshold, a change-point is flagged.

    Parameters:
        drift: allowance parameter (slack before alarm), default 0.5 std
        threshold: detection threshold in standard deviation units
    """

    def __init__(self, drift: float = 0.5, threshold: float = 4.0) -> None:
        self.drift = drift
        self.threshold = threshold

    def detect(
        self,
        values: np.ndarray,
        timestamps: list[datetime] | None = None,
    ) -> list[ChangePoint]:
        if len(values) < 5:
            return []

        # Standardize series
        mean = np.mean(values)
        std = max(np.std(values), 1e-9)
        x = (values - mean) / std

        # CUSUM for positive and negative shifts
        s_pos = np.zeros(len(x))
        s_neg = np.zeros(len(x))
        changepoints: list[ChangePoint] = []

        for i in range(1, len(x)):
            s_pos[i] = max(0, s_pos[i - 1] + x[i] - self.drift)
            s_neg[i] = max(0, s_neg[i - 1] - x[i] - self.drift)

            ts = timestamps[i] if timestamps else None

            if s_pos[i] > self.threshold:
                changepoints.append(ChangePoint(
                    index=i, timestamp=ts,
                    score=float(s_pos[i] / self.threshold),
                    direction="increase", method="cusum",
                ))
                s_pos[i] = 0  # reset after detection

            if s_neg[i] > self.threshold:
                changepoints.append(ChangePoint(
                    index=i, timestamp=ts,
                    score=float(s_neg[i] / self.threshold),
                    direction="decrease", method="cusum",
                ))
                s_neg[i] = 0  # reset after detection

        return changepoints


# ---------------------------------------------------------------- Bayesian
class BayesianChangePointDetector:
    """Simplified Bayesian Online Change-Point Detection.

    Based on the Adams & MacKay (2007) algorithm. Maintains a run-length
    distribution and signals a change-point when the posterior probability
    of a new run exceeds a threshold.

    Parameters:
        hazard_rate: expected rate of change-points (1/expected_run_length)
        threshold: posterior probability threshold for detection
    """

    def __init__(self, hazard_rate: float = 1 / 50, threshold: float = 0.5) -> None:
        self.hazard_rate = hazard_rate
        self.threshold = threshold

    def detect(
        self,
        values: np.ndarray,
        timestamps: list[datetime] | None = None,
    ) -> list[ChangePoint]:
        n = len(values)
        if n < 5:
            return []

        # Online Bayesian approach with Gaussian conjugate prior
        changepoints: list[ChangePoint] = []

        # Running statistics
        mu_prior = float(np.mean(values[:3]))
        var_prior = max(float(np.var(values[:3])), 1e-9)

        # Simplified: track run length probability
        run_length = 0
        run_sum = 0.0
        run_sq_sum = 0.0

        for i in range(len(values)):
            run_length += 1
            run_sum += values[i]
            run_sq_sum += values[i] ** 2

            run_mean = run_sum / run_length
            run_var = max(run_sq_sum / run_length - run_mean**2, 1e-9)

            # Predictive probability under current run
            deviation = abs(values[i] - run_mean)
            run_std = max(np.sqrt(run_var), 1e-9)
            z = deviation / run_std

            # Probability of changepoint: hazard * evidence of deviation
            cp_prob = self.hazard_rate * min(1.0, z / 3.0)

            if cp_prob > self.threshold and run_length > 3:
                direction = "increase" if values[i] > run_mean else "decrease"
                ts = timestamps[i] if timestamps else None
                changepoints.append(ChangePoint(
                    index=i, timestamp=ts,
                    score=float(cp_prob),
                    direction=direction, method="bayesian",
                ))
                # Reset run
                run_length = 1
                run_sum = values[i]
                run_sq_sum = values[i] ** 2

        return changepoints


# ---------------------------------------------------------------- Ensemble
class ChangePointEnsemble:
    """Runs both CUSUM and Bayesian detectors and merges results."""

    def __init__(self) -> None:
        self.cusum = CUSUMDetector()
        self.bayesian = BayesianChangePointDetector()

    def detect(
        self,
        values: np.ndarray,
        timestamps: list[datetime] | None = None,
    ) -> list[ChangePoint]:
        """Returns all detected change-points, deduplicated by proximity."""
        cps_cusum = self.cusum.detect(values, timestamps)
        cps_bayes = self.bayesian.detect(values, timestamps)
        all_cps = cps_cusum + cps_bayes
        if not all_cps:
            return []
        # Deduplicate: merge change-points within 3 indices of each other
        all_cps.sort(key=lambda cp: cp.index)
        merged: list[ChangePoint] = [all_cps[0]]
        for cp in all_cps[1:]:
            if cp.index - merged[-1].index <= 3:
                # Keep the higher-scoring one
                if cp.score > merged[-1].score:
                    merged[-1] = cp
            else:
                merged.append(cp)
        return merged

    def detect_entity(
        self,
        entity_id: str,
        values: np.ndarray,
        timestamps: list[datetime] | None = None,
    ) -> ChangePointResult:
        cps = self.detect(values, timestamps)
        summary = min(1.0, sum(cp.score for cp in cps) / max(len(values) / 20, 1))
        return ChangePointResult(
            entity_id=entity_id,
            changepoints=cps,
            summary_score=summary,
        )


def detect_changepoints_for_entities(
    events: pd.DataFrame,
    entities: list[str] | None = None,
) -> dict[str, ChangePointResult]:
    """Run change-point detection on volume time series for each entity.

    Args:
        events: DataFrame with 'timestamp', 'from_entity', 'to_entity', 'value_eth'
        entities: optional subset of entities to analyze

    Returns:
        dict mapping entity_id -> ChangePointResult
    """
    detector = ChangePointEnsemble()
    results: dict[str, ChangePointResult] = {}

    if entities is None:
        entities = sorted(set(events["from_entity"]) | set(events["to_entity"]))

    for ent in entities:
        e = events[
            (events["from_entity"] == ent) | (events["to_entity"] == ent)
        ].sort_values("timestamp")
        if len(e) < 5:
            results[ent] = ChangePointResult(entity_id=ent)
            continue

        # Detect on value series
        values = e["value_eth"].to_numpy().astype(float)
        timestamps = e["timestamp"].tolist()
        results[ent] = detector.detect_entity(ent, values, timestamps)

    return results
