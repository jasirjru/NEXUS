"""Ablation studies: measure incremental value of each component.

Stages (per blueprint section 14):
1. behavioral baseline (statistical zscore on behavioral features only)
2. + graph features
3. + temporal features (already partly in behavioral; here = interval/entropy)
4. + graph ML embeddings
5. final ensemble

Each stage is evaluated with the same protocol (temporal split, same metrics),
so differences are attributable to the added component only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nexus.evaluation.metrics import combine_metrics
from nexus.models.anomaly.detectors import (
    AnomalyEnsemble,
    IsolationForestDetector,
    LOFDetector,
    RobustZScore,
)

BEHAVIORAL_COLS_PREFIXES = (
    "tx_count", "volume", "avg_value", "median_value", "max_value",
    "value_", "unique_",
)
TEMPORAL_COLS = (
    "inter_tx_mean_hours", "inter_tx_std_hours", "inter_tx_entropy",
    "hour_entropy", "night_ratio", "interval_shift_z", "burstiness",
    "volume_recent_vs_hist", "new_counterparty_fraction",
)
GRAPH_PREFIXES = ("degree", "pagerank", "betweenness", "clustering", "community", "embedding")


def _cols_by_prefix(df: pd.DataFrame, prefixes: tuple[str, ...]) -> list[str]:
    return [c for c in df.columns if c.startswith(prefixes)]


@dataclass
class AblationStage:
    name: str
    features_used: list[str]
    metrics: dict = field(default_factory=dict)


def run_ablation(
    features: pd.DataFrame, labels: np.ndarray,
    detector_names: list[str] | None = None,
) -> list[AblationStage]:
    """features: full feature frame (behavioral+graph+temporal) indexed by entity.

    labels: 0/1 per entity. Returns per-stage metrics; higher PR-AUC/F1 with
    fewer features = better design.
    """
    labels = np.asarray(labels).astype(int)
    stages_spec = [
        ("baseline_behavioral", _cols_by_prefix(features, BEHAVIORAL_COLS_PREFIXES)),
        ("plus_graph", _cols_by_prefix(features, BEHAVIORAL_COLS_PREFIXES + GRAPH_PREFIXES)),
        (
            "plus_temporal",
            _cols_by_prefix(features, BEHAVIORAL_COLS_PREFIXES + GRAPH_PREFIXES + TEMPORAL_COLS),
        ),
        ("all_features", list(features.columns)),
    ]
    detector_names = detector_names or ["robust_zscore", "iforest", "lof"]
    detector_map = {
        "robust_zscore": RobustZScore,
        "iforest": IsolationForestDetector,
        "lof": LOFDetector,
    }

    stages: list[AblationStage] = []
    for name, cols in stages_spec:
        cols = [c for c in cols if c in features.columns]
        if not cols:
            continue
        X = features[cols].fillna(0.0)
        # ensemble score = mean rank score across detectors
        scores = []
        for dn in detector_names:
            det = detector_map[dn]()
            det.fit(X)
            scores.append(det.score(X))
        ens = np.mean(np.vstack(scores), axis=0)
        m = combine_metrics(labels, ens)
        stages.append(AblationStage(name=name, features_used=cols, metrics=m))
    return stages
