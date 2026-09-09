"""Investigation endpoints: the AI investigator panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nexus.agents.investigator import Investigator
from nexus.core.errors import NotFoundError
from nexus.db.schema import Investigation
from nexus.db.session import get_db

router = APIRouter(tags=["investigations"])


class AskRequest(BaseModel):
    entity_id: str
    question: str


@router.post("/investigate")
def investigate(req: AskRequest, db: Session = Depends(get_db)) -> dict:
    report = Investigator(db).investigate(req.entity_id, req.question)
    return report.to_dict()


@router.get("/investigations")
def list_investigations(entity_id: str | None = None,
                        limit: int = Query(50, le=200),
                        db: Session = Depends(get_db)) -> dict:
    q = db.query(Investigation)
    if entity_id:
        q = q.filter(Investigation.entity_id == entity_id)
    rows = q.order_by(Investigation.created_at.desc()).limit(limit).all()
    return {"items": [r.to_dict() for r in rows]}


@router.get("/investigations/{inv_id}")
def get_investigation(inv_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Investigation, inv_id)
    if row is None:
        raise NotFoundError(f"investigation {inv_id} not found")
    return row.to_dict()
