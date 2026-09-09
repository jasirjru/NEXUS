"""Evaluation endpoints: run/inspect measured evaluations + ablations."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from nexus.db.schema import EvaluationRun
from nexus.db.session import get_db
from nexus.pipelines.intelligence import (
    derive_demo_labels,
    stage_features,
    stage_evaluate,
)

router = APIRouter(tags=["evaluations"])


@router.get("/evaluations")
def list_evaluations(kind: str | None = None, db: Session = Depends(get_db)) -> dict:
    q = db.query(EvaluationRun)
    if kind:
        q = q.filter(EvaluationRun.kind == kind)
    rows = q.order_by(EvaluationRun.created_at.desc()).limit(50).all()
    return {"items": [r.to_dict() for r in rows]}


@router.post("/evaluations/run")
def run_evaluation(db: Session = Depends(get_db)) -> dict:
    from datetime import datetime, timezone

    behavioral, graphf = stage_features(db, datetime.now(timezone.utc))
    full = behavioral.join(graphf, how="left")

    # reuse anomaly scores if present; recompute quickly otherwise
    from sqlalchemy import select
    from nexus.db.schema import ScoreRecord

    latest = db.scalar(select(func_max()).where(ScoreRecord.score_name == "anomaly_ensemble"))
    if latest is None:
        return {"error": "run the pipeline first (no anomaly scores)"}
    rows = db.execute(
        select(ScoreRecord.entity_id, ScoreRecord.value).where(
            ScoreRecord.score_name == "anomaly_ensemble", ScoreRecord.as_of == latest
        )
    ).all()
    import pandas as pd

    scores = pd.Series({e: v for e, v in rows}, name="anomaly_ensemble")
    result = stage_evaluate(db, full, scores)
    return result


def func_max():
    from sqlalchemy import func

    return func.max(ScoreRecord.as_of)
