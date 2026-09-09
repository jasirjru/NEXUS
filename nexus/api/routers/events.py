"""Event endpoints: filtered listing + temporal histogram."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus.db.schema import Event
from nexus.db.session import get_db

router = APIRouter(tags=["events"])


@router.get("/events")
def list_events(
    entity: str | None = None,
    type: str | None = None,
    min_value_eth: float | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(Event)
    if entity:
        q = q.filter(or_(Event.from_entity == entity, Event.to_entity == entity))
    if type:
        q = q.filter(Event.type == type)
    if min_value_eth is not None:
        q = q.filter(Event.value_wei >= int(min_value_eth * 1e18))
    if start:
        q = q.filter(Event.timestamp >= start)
    if end:
        q = q.filter(Event.timestamp <= end)
    total = q.count()
    rows = q.order_by(Event.timestamp.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [r.to_dict() for r in rows]}


@router.get("/events/histogram")
def event_histogram(bucket: str = Query("day", pattern="^(hour|day|week)$"),
                    db: Session = Depends(get_db)) -> dict:
    col = {
        "hour": func.strftime("%Y-%m-%dT%H:00:00", Event.timestamp),
        "day": func.strftime("%Y-%m-%d", Event.timestamp),
        "week": func.strftime("%Y-%W", Event.timestamp),
    }[bucket]
    rows = db.execute(
        select(col.label("bucket"), func.count(), func.sum(Event.value_wei))
        .group_by(col).order_by(col)
    ).all()
    return {
        "items": [
            {"bucket": b, "count": c, "value_eth": round((v or 0) / 1e18, 3)}
            for b, c, v in rows
        ]
    }
