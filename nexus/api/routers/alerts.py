"""Alert endpoints: rules CRUD + alert listing/acknowledgement."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nexus.alerts.service import evaluate_alert_rules
from nexus.core.errors import NotFoundError
from nexus.db.schema import Alert, AlertRule
from nexus.db.session import get_db

router = APIRouter(tags=["alerts"])


class RuleCreate(BaseModel):
    name: str
    metric: str = "risk"
    operator: str = ">"
    threshold: float
    entity_id: str | None = None
    channels: list[str] = ["dashboard"]
    webhook_url: str | None = None


@router.post("/alerts/rules")
def create_rule(rule: RuleCreate, db: Session = Depends(get_db)) -> dict:
    if rule.operator not in (">", ">=", "<", "<=", "=="):
        raise NotFoundError("invalid operator")
    row = AlertRule(**rule.model_dump())
    db.add(row)
    db.commit()
    return row.to_dict()


@router.get("/alerts/rules")
def list_rules(db: Session = Depends(get_db)) -> dict:
    rows = db.query(AlertRule).order_by(AlertRule.id.desc()).all()
    return {"items": [r.to_dict() for r in rows]}


@router.delete("/alerts/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(AlertRule, rule_id)
    if row is None:
        raise NotFoundError(f"rule {rule_id} not found")
    db.delete(row)
    db.commit()
    return {"deleted": rule_id}


@router.get("/alerts")
def list_alerts(acknowledged: bool | None = None,
                limit: int = Query(100, le=500),
                db: Session = Depends(get_db)) -> dict:
    q = db.query(Alert)
    if acknowledged is not None:
        q = q.filter(Alert.acknowledged == acknowledged)
    rows = q.order_by(Alert.created_at.desc()).limit(limit).all()
    return {"items": [r.to_dict() for r in rows]}


@router.post("/alerts/evaluate")
def evaluate(db: Session = Depends(get_db)) -> dict:
    created = evaluate_alert_rules(db)
    return {"raised": len(created), "alerts": [a.to_dict() for a in created]}


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Alert, alert_id)
    if row is None:
        raise NotFoundError(f"alert {alert_id} not found")
    row.acknowledged = True
    db.commit()
    return row.to_dict()
