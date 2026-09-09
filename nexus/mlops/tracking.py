"""Experiment tracking abstraction with optional MLflow backend.

Design:
- NexusTracker wraps either MLflow (if installed and configured) or a
  lightweight internal JSON-file logger (always available).
- The pipeline calls tracker.log_params/log_metrics/log_artifact without
  knowing which backend is active.
- This avoids a hard dependency on MLflow while supporting it when available.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexus.config import settings
from nexus.core.logging_setup import get_logger

log = get_logger("nexus.mlops.tracking")

# Check for MLflow
_MLFLOW_AVAILABLE = False
try:
    import mlflow
    _MLFLOW_AVAILABLE = True
except ImportError:
    pass


class NexusTracker:
    """Experiment tracking abstraction.

    Uses MLflow if installed and NEXUS_MLFLOW_URI is set;
    otherwise falls back to a JSON-file log in artifacts/mlops/.
    """

    def __init__(self, experiment_name: str = "nexus") -> None:
        self.experiment_name = experiment_name
        self.backend: str = "internal"
        self._run_id: str | None = None
        self._log_dir = settings.artifacts_path / "mlops" / "runs"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._current_log: dict[str, Any] = {}

        if _MLFLOW_AVAILABLE:
            mlflow_uri = getattr(settings, "mlflow_uri", None)
            if mlflow_uri:
                try:
                    mlflow.set_tracking_uri(mlflow_uri)
                    mlflow.set_experiment(experiment_name)
                    self.backend = "mlflow"
                    log.info("MLflow tracking enabled at %s", mlflow_uri)
                except Exception as e:
                    log.warning("MLflow setup failed, falling back to internal: %s", e)

    def start_run(self, run_name: str | None = None) -> str:
        """Start a tracking run. Returns a run ID."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._run_id = f"{run_name or 'run'}_{ts}"
        self._current_log = {
            "run_id": self._run_id,
            "run_name": run_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "params": {},
            "metrics": {},
            "artifacts": [],
            "tags": {},
        }

        if self.backend == "mlflow":
            run = mlflow.start_run(run_name=run_name)
            self._run_id = run.info.run_id

        log.info("started tracking run %s (backend=%s)", self._run_id, self.backend)
        return self._run_id

    def log_params(self, params: dict[str, Any]) -> None:
        """Log hyperparameters."""
        self._current_log.setdefault("params", {}).update(
            {k: str(v) for k, v in params.items()}
        )
        if self.backend == "mlflow":
            # MLflow limits param value to 500 chars
            for k, v in params.items():
                try:
                    mlflow.log_param(k, str(v)[:500])
                except Exception:
                    pass

    def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None:
        """Log numeric metrics."""
        self._current_log.setdefault("metrics", {}).update(
            {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        )
        if self.backend == "mlflow":
            try:
                mlflow.log_metrics(
                    {k: v for k, v in metrics.items() if isinstance(v, (int, float))},
                    step=step,
                )
            except Exception:
                pass

    def log_artifact(self, path: str | Path, artifact_name: str | None = None) -> None:
        """Log an artifact file."""
        self._current_log.setdefault("artifacts", []).append(
            {"path": str(path), "name": artifact_name}
        )
        if self.backend == "mlflow":
            try:
                mlflow.log_artifact(str(path))
            except Exception:
                pass

    def set_tag(self, key: str, value: str) -> None:
        self._current_log.setdefault("tags", {})[key] = value
        if self.backend == "mlflow":
            try:
                mlflow.set_tag(key, value)
            except Exception:
                pass

    def end_run(self, status: str = "FINISHED") -> None:
        """End the current run and persist the log."""
        self._current_log["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._current_log["status"] = status

        # Always persist to internal JSON log
        log_file = self._log_dir / f"{self._run_id}.json"
        log_file.write_text(json.dumps(self._current_log, indent=2, default=str))

        if self.backend == "mlflow":
            try:
                mlflow.end_run(status=status)
            except Exception:
                pass

        log.info("ended tracking run %s status=%s", self._run_id, status)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent runs from internal storage."""
        runs = []
        for f in sorted(self._log_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                runs.append(json.loads(f.read_text()))
            except Exception:
                pass
        return runs

    @property
    def mlflow_available(self) -> bool:
        return _MLFLOW_AVAILABLE and self.backend == "mlflow"
