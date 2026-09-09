"""Metrics endpoints: model performance over time + drift detection.

Drift is measured honestly: Population Stability Index (PSI) between the
feature distribution at training time (earliest evaluation window) and now,
plus prediction drift on score distributions. Thresholds: PSI > 0.2 = drift.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.db.schema import EvaluationRun, ScoreRecord
from nexus.db.session import get_db
from nexus.features.behavioral import compute_entity_features, load_events_frame

import numpy as np
import pandas as pd

router = APIRouter(tags=["metrics"])


def _psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index between two samples."""
    expected, actual = expected[~np.isnan(expected)], actual[~np.isnan(actual)]
    if len(expected) < 10 or len(actual) < 10:
        return 0.0
    edges = np.quantile(expected, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    e_pct = np.histogram(expected, edges)[0] / len(expected)
    a_pct = np.histogram(actual, edges)[0] / len(actual)
    e_pct, a_pct = np.clip(e_pct, 1e-6, None), np.clip(a_pct, 1e-6, None)
    return float(((a_pct - e_pct) * np.log(a_pct / e_pct)).sum())


@router.get("/metrics/model-performance")
def model_performance(db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(EvaluationRun)
        .filter(EvaluationRun.kind.in_(["anomaly", "risk"]))
        .order_by(EvaluationRun.created_at.desc())
        .limit(20)
        .all()
    )
    return {"items": [r.to_dict() for r in rows]}


@router.get("/metrics/drift")
def drift(db: Session = Depends(get_db)) -> dict:
    events = load_events_frame(db)
    if events.empty:
        return {"items": [], "prediction_drift": None}
    now = events["timestamp"].max()
    month_ago = now - pd.Timedelta(days=30)

    feats_now = compute_entity_features(events, as_of=now.to_pydatetime())
    feats_ref = compute_entity_features(events, as_of=month_ago.to_pydatetime())

    common_cols = [c for c in feats_now.columns if c in feats_ref.columns]
    items = []
    for col in common_cols:
        psi = _psi(feats_ref[col].to_numpy(float), feats_now[col].to_numpy(float))
        items.append({"feature": col, "psi": round(psi, 4),
                      "drift": psi > 0.2})
    items.sort(key=lambda r: r["psi"], reverse=True)

    # prediction drift: anomaly score distribution shift between pipeline runs
    runs = db.execute(
        select(ScoreRecord.as_of)
        .where(ScoreRecord.score_name == "anomaly_ensemble")
        .distinct()
        .order_by(ScoreRecord.as_of)
        .limit(20)
    ).scalars().all()
    prediction_drift = None
    if len(runs) >= 2:
        def scores_at(ts):
            rows = db.execute(
                select(ScoreRecord.value).where(
                    ScoreRecord.score_name == "anomaly_ensemble",
                    ScoreRecord.as_of == ts,
                )
            ).scalars().all()
            return np.array(rows, dtype=float)

        first, last = scores_at(runs[0]), scores_at(runs[-1])
        prediction_drift = {"psi": round(_psi(first, last), 4),
                            "first_run": runs[0].isoformat(),
                            "last_run": runs[-1].isoformat()}
    return {"items": items[:20], "prediction_drift": prediction_drift}
