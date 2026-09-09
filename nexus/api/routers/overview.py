"""Overview: headline stats for the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus.db.schema import Alert, Entity, Event, Investigation, ScoreRecord
from nexus.db.session import get_db

router = APIRouter(tags=["overview"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    n_entities = db.scalar(select(func.count()).select_from(Entity)) or 0
    n_events = db.scalar(select(func.count()).select_from(Event)) or 0
    n_alerts_open = (
        db.scalar(select(func.count()).select_from(Alert).where(Alert.acknowledged.is_(False))) or 0
    )
    n_investigations = db.scalar(select(func.count()).select_from(Investigation)) or 0

    # latest risk scores: top risky + distribution buckets
    latest_ts = db.scalar(select(func.max(ScoreRecord.as_of)).where(ScoreRecord.score_name == "risk"))
    top_risk: list[dict] = []
    buckets = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    if latest_ts:
        from sqlalchemy import cast, Float, String

        rows = db.execute(
            select(ScoreRecord).where(
                ScoreRecord.score_name == "risk", ScoreRecord.as_of == latest_ts
            )
        ).scalars().all()
        by_risk = sorted(rows, key=lambda r: r.value, reverse=True)
        for r in by_risk:
            v = r.value
            b = "low" if v < 0.25 else "medium" if v < 0.5 else "high" if v < 0.8 else "critical"
            buckets[b] += 1
        top_risk = [
            {
                "entity_id": r.entity_id,
                "risk": round(r.value, 4),
                "confidence": round(r.confidence, 4) if r.confidence is not None else None,
            }
            for r in by_risk[:10]
        ]

    latest_anom = db.scalar(
        select(func.max(ScoreRecord.as_of)).where(ScoreRecord.score_name == "anomaly_ensemble")
    )
    active_anomalies = 0
    if latest_anom:
        active_anomalies = (
            db.scalar(
                select(func.count()).select_from(ScoreRecord).where(
                    ScoreRecord.score_name == "anomaly_ensemble",
                    ScoreRecord.as_of == latest_anom,
                    ScoreRecord.value > 0.8,
                )
            ) or 0
        )

    return {
        "entities": n_entities,
        "events": n_events,
        "open_alerts": n_alerts_open,
        "investigations": n_investigations,
        "active_anomalies": active_anomalies,
        "risk_distribution": buckets,
        "top_risk": top_risk,
    }
