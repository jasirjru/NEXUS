"""Score endpoints: latest anomaly/risk scores for dashboard tables."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.db.schema import ScoreRecord
from nexus.db.session import get_db

router = APIRouter(tags=["scores"])


def _latest_by_entity(db: Session, score_name: str, limit: int, order_desc: bool):
    latest = db.scalar(
        select(func_max()).where(ScoreRecord.score_name == score_name)
    )
    if latest is None:
        return []
    rows = db.execute(
        select(ScoreRecord).where(
            ScoreRecord.score_name == score_name, ScoreRecord.as_of == latest
        )
    ).scalars().all()
    rows.sort(key=lambda r: r.value, reverse=order_desc)
    return rows[:limit]


def func_max():
    from sqlalchemy import func

    return func.max(ScoreRecord.as_of)


@router.get("/anomaly-scores")
def anomaly_scores(limit: int = Query(100, le=500), db: Session = Depends(get_db)) -> dict:
    rows = _latest_by_entity(db, "anomaly_ensemble", limit, True)
    return {
        "items": [
            {
                "entity_id": r.entity_id,
                "value": round(r.value, 4),
                "details": r.details,
                "as_of": r.as_of.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/risk-scores")
def risk_scores(limit: int = Query(100, le=500), db: Session = Depends(get_db)) -> dict:
    rows = _latest_by_entity(db, "risk", limit, True)
    return {
        "items": [
            {
                "entity_id": r.entity_id,
                "value": round(r.value, 4),
                "confidence": round(r.confidence, 4) if r.confidence is not None else None,
                "details": r.details,
                "as_of": r.as_of.isoformat(),
            }
            for r in rows
        ]
    }
