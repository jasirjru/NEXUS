"""Tests for MLOps tracking, drift detection, and automated retraining."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexus.mlops.retraining import (
    DriftReport,
    RetrainingResult,
    check_drift,
    compute_psi,
)
from nexus.mlops.tracking import NexusTracker


class TestDriftDetection:
    def test_compute_psi_identical(self):
        rng = np.random.RandomState(42)
        ref = rng.normal(0, 1, 1000)
        cur = rng.normal(0, 1, 1000)
        psi = compute_psi(ref, cur)
        assert psi < 0.1  # Minimal drift

    def test_compute_psi_shifted(self):
        ref = np.random.normal(0, 1, 1000)
        cur = np.random.normal(3, 1, 1000)  # Significant shift
        psi = compute_psi(ref, cur)
        assert psi > 0.25  # High drift detected

    def test_compute_psi_short_arrays(self):
        assert compute_psi(np.array([1, 2]), np.array([1, 2])) == 0.0

    def test_check_drift_features(self):
        ref_df = pd.DataFrame({
            "feat_a": np.random.normal(0, 1, 500),
            "feat_b": np.random.uniform(0, 10, 500),
        })
        # feat_a has drifted, feat_b is similar
        cur_df = pd.DataFrame({
            "feat_a": np.random.normal(4, 1, 500),
            "feat_b": np.random.uniform(0, 10, 500),
        })

        report = check_drift(ref_df, cur_df, threshold=0.2)
        assert isinstance(report, DriftReport)
        assert report.drift_detected is True
        assert report.feature_psi["feat_a"] > 0.2
        d = report.to_dict()
        assert "feature_psi" in d
        assert d["drift_detected"] is True

    def test_check_drift_predictions(self):
        ref_preds = np.random.beta(2, 5, 500)
        cur_preds = np.random.beta(5, 2, 500)  # Distribution inverted
        ref_df = pd.DataFrame({"dummy": [1.0] * 500})
        cur_df = pd.DataFrame({"dummy": [1.0] * 500})

        report = check_drift(
            ref_df,
            cur_df,
            reference_predictions=ref_preds,
            current_predictions=cur_preds,
            threshold=0.15,
        )
        assert report.prediction_psi > 0.15
        assert report.drift_detected is True


class TestNexusTracker:
    def test_tracker_lifecycle(self, tmp_path, monkeypatch):
        # Point settings to tmp_path
        from nexus.config import settings
        monkeypatch.setattr(settings, "artifacts_dir", str(tmp_path))

        tracker = NexusTracker(experiment_name="test_experiment")
        run_id = tracker.start_run(run_name="unit_test_run")
        assert run_id is not None

        tracker.log_params({"model_type": "isolation_forest", "n_estimators": 100})
        tracker.log_metrics({"pr_auc": 0.88, "roc_auc": 0.94})

        # Artifact logging
        dummy_file = tmp_path / "weights.bin"
        dummy_file.write_text("sample weights")
        tracker.log_artifact(str(dummy_file))

        tracker.end_run()
        runs = tracker.list_runs()
        assert len(runs) >= 1
        summary = runs[0]
        assert summary["status"] == "FINISHED"
        assert summary["params"]["model_type"] == "isolation_forest"
        assert summary["metrics"]["pr_auc"] == 0.88
        assert len(summary["artifacts"]) == 1


class TestRetrainingResult:
    def test_retraining_result_to_dict(self):
        res = RetrainingResult(
            triggered=True,
            reason="feature drift in tx_volume (PSI=0.34)",
            new_version="v2.0.0",
            old_metrics={"pr_auc": 0.72},
            new_metrics={"pr_auc": 0.85},
            improvement={"pr_auc": 0.13},
            action="staged",
        )
        d = res.to_dict()
        assert d["triggered"] is True
        assert d["new_version"] == "v2.0.0"
        assert d["action"] == "staged"
        assert d["improvement"]["pr_auc"] == 0.13
