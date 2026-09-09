"""Automated retraining pipeline triggered by drift detection.

Implements the documented lifecycle:
    DRIFT DETECTED → RETRAIN → EVALUATE → APPROVE → DEPLOY

The retraining decision is driven by PSI (Population Stability Index) on
features and predictions. When drift exceeds a threshold, the pipeline:
1. Retrains the anomaly ensemble and risk engine on recent data
2. Evaluates against the current production model
3. Registers the new model as 'staging'
4. Requires human approval to promote to 'production'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from nexus.core.logging_setup import get_logger
from nexus.db.schema import EvaluationRun, ModelRecord
from nexus.models.registry import ModelRegistry

log = get_logger("nexus.mlops.retraining")


@dataclass
class DriftReport:
    """Report on feature/prediction drift."""
    feature_psi: dict[str, float] = field(default_factory=dict)
    prediction_psi: float = 0.0
    drift_detected: bool = False
    threshold: float = 0.2

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_psi": {k: round(v, 4) for k, v in self.feature_psi.items()},
            "prediction_psi": round(self.prediction_psi, 4),
            "drift_detected": self.drift_detected,
            "threshold": self.threshold,
        }


@dataclass
class RetrainingResult:
    """Result of a retraining cycle."""
    triggered: bool
    reason: str
    new_version: str | None = None
    old_metrics: dict[str, float] = field(default_factory=dict)
    new_metrics: dict[str, float] = field(default_factory=dict)
    improvement: dict[str, float] = field(default_factory=dict)
    action: str = "none"  # "none" | "staged" | "promoted" | "rejected"

    def to_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "reason": self.reason,
            "new_version": self.new_version,
            "old_metrics": {k: round(v, 4) for k, v in self.old_metrics.items()},
            "new_metrics": {k: round(v, 4) for k, v in self.new_metrics.items()},
            "improvement": {k: round(v, 4) for k, v in self.improvement.items()},
            "action": self.action,
        }


def compute_psi(
    reference: np.ndarray, current: np.ndarray, n_bins: int = 10,
) -> float:
    """Population Stability Index between two distributions.

    PSI < 0.1: no significant change
    0.1 <= PSI < 0.2: moderate change (monitor)
    PSI >= 0.2: significant change (retrain)
    """
    reference = np.asarray(reference, dtype=float)
    current = np.asarray(current, dtype=float)

    if len(reference) < 5 or len(current) < 5:
        return 0.0

    # Create bins from reference distribution
    edges = np.percentile(reference, np.linspace(0, 100, n_bins + 1))
    edges[0] = -np.inf
    edges[-1] = np.inf

    ref_counts = np.histogram(reference, bins=edges)[0].astype(float)
    cur_counts = np.histogram(current, bins=edges)[0].astype(float)

    # Add small epsilon to avoid division by zero
    eps = 1e-6
    ref_pct = (ref_counts + eps) / (len(reference) + eps * n_bins)
    cur_pct = (cur_counts + eps) / (len(current) + eps * n_bins)

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return max(psi, 0.0)


def check_drift(
    reference_features: pd.DataFrame,
    current_features: pd.DataFrame,
    reference_predictions: np.ndarray | None = None,
    current_predictions: np.ndarray | None = None,
    threshold: float = 0.2,
) -> DriftReport:
    """Check for feature and prediction drift using PSI."""
    report = DriftReport(threshold=threshold)

    # Feature-level PSI
    common_cols = [c for c in reference_features.columns if c in current_features.columns]
    for col in common_cols:
        ref_vals = reference_features[col].dropna().to_numpy()
        cur_vals = current_features[col].dropna().to_numpy()
        if len(ref_vals) >= 5 and len(cur_vals) >= 5:
            psi = compute_psi(ref_vals, cur_vals)
            report.feature_psi[col] = psi

    # Prediction-level PSI
    if reference_predictions is not None and current_predictions is not None:
        report.prediction_psi = compute_psi(reference_predictions, current_predictions)

    # Drift detected if any feature PSI or prediction PSI exceeds threshold
    max_feature_psi = max(report.feature_psi.values()) if report.feature_psi else 0.0
    report.drift_detected = max_feature_psi > threshold or report.prediction_psi > threshold

    if report.drift_detected:
        drifted = [k for k, v in report.feature_psi.items() if v > threshold]
        log.warning(
            "drift detected: pred_psi=%.3f, drifted_features=%s",
            report.prediction_psi, drifted,
        )

    return report


def evaluate_retraining_candidate(
    old_metrics: dict[str, float],
    new_metrics: dict[str, float],
    improvement_threshold: float = 0.0,
) -> tuple[bool, dict[str, float]]:
    """Compare new model metrics against old; returns (should_promote, improvements)."""
    improvements: dict[str, float] = {}
    key_metrics = ["roc_auc", "pr_auc", "f1"]

    for m in key_metrics:
        if m in old_metrics and m in new_metrics:
            improvements[m] = new_metrics[m] - old_metrics[m]

    # Promote if no regression on any key metric
    should_promote = all(v >= -improvement_threshold for v in improvements.values())
    return should_promote, improvements


class RetrainingPipeline:
    """Orchestrates the drift → retrain → evaluate → approve → deploy cycle."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.registry = ModelRegistry(db)

    def check_and_retrain(
        self,
        reference_features: pd.DataFrame,
        current_features: pd.DataFrame,
        current_labels: np.ndarray,
        reference_predictions: np.ndarray | None = None,
        current_predictions: np.ndarray | None = None,
        threshold: float = 0.2,
    ) -> RetrainingResult:
        """Check drift and retrain if needed.

        Returns a RetrainingResult describing what happened. The new model
        is registered as 'staging' — promotion to 'production' requires
        explicit approval via the registry.
        """
        drift = check_drift(
            reference_features, current_features,
            reference_predictions, current_predictions,
            threshold=threshold,
        )

        if not drift.drift_detected:
            return RetrainingResult(
                triggered=False,
                reason="no drift detected (all PSI < threshold)",
            )

        # Get current production metrics
        prod = self.registry.get_production("anomaly_ensemble")
        old_metrics = prod.metrics if prod else {}

        # Retrain
        from nexus.models.anomaly.detectors import AnomalyEnsemble
        from nexus.evaluation.metrics import combine_metrics

        ens = AnomalyEnsemble()
        X = current_features.fillna(0.0)
        ens.fit(X)
        scores = ens.score(X)
        new_metrics = combine_metrics(current_labels, scores)

        version = datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S")

        # Compare
        should_promote, improvements = evaluate_retraining_candidate(
            old_metrics, new_metrics,
        )

        # Register as staging
        self.registry.register(
            "anomaly_ensemble", version, ens, new_metrics,
            {"retrained": True, "drift_triggered": True}, stage="staging",
        )

        # Log evaluation
        self.db.add(EvaluationRun(
            name=f"retraining_{version}",
            kind="retraining",
            metrics={
                "old": old_metrics,
                "new": {k: round(v, 4) for k, v in new_metrics.items() if isinstance(v, (int, float))},
                "improvements": improvements,
                "drift": drift.to_dict(),
            },
            config={"threshold": threshold, "should_promote": should_promote},
        ))
        self.db.commit()

        action = "staged"
        if should_promote:
            log.info("new model %s shows improvement; staged for approval", version)
        else:
            log.warning("new model %s shows regression; staged but not recommended", version)

        return RetrainingResult(
            triggered=True,
            reason="drift detected, model retrained",
            new_version=version,
            old_metrics={k: v for k, v in old_metrics.items() if isinstance(v, (int, float))},
            new_metrics={k: round(v, 4) for k, v in new_metrics.items() if isinstance(v, (int, float))},
            improvement=improvements,
            action=action,
        )
