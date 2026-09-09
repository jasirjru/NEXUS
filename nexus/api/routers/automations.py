"""Automation endpoints: workflows, runs, human approval."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nexus.alerts.service import approve_run, run_automation
from nexus.core.errors import NotFoundError
from nexus.db.schema import Automation, WorkflowRun
from nexus.db.session import get_db

router = APIRouter(tags=["automations"])


class AutomationCreate(BaseModel):
    name: str
    trigger_metric: str = "risk"
    trigger_operator: str = ">"
    trigger_threshold: float = 0.8
    steps: list[dict]
    requires_approval: bool = True


@router.post("/automations")
def create_automation(data: AutomationCreate, db: Session = Depends(get_db)) -> dict:
    row = Automation(**data.model_dump())
    db.add(row)
    db.commit()
    return row.to_dict()


@router.get("/automations")
def list_automations(db: Session = Depends(get_db)) -> dict:
    rows = db.query(Automation).order_by(Automation.id.desc()).all()
    return {"items": [r.to_dict() for r in rows]}


class RunRequest(BaseModel):
    entity_id: str


@router.post("/automations/{automation_id}/run")
def run(automation_id: int, req: RunRequest, db: Session = Depends(get_db)) -> dict:
    auto = db.get(Automation, automation_id)
    if auto is None:
        raise NotFoundError(f"automation {automation_id} not found")
    run = run_automation(db, auto, req.entity_id)
    return run.to_dict()


@router.post("/workflow-runs/{run_id}/approve")
def approve(run_id: int, approve: bool = True,
            db: Session = Depends(get_db)) -> dict:
    return approve_run(db, run_id, approve=approve).to_dict()


@router.get("/workflow-runs")
def list_runs(limit: int = Query(50, le=200), db: Session = Depends(get_db)) -> dict:
    rows = db.query(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(limit).all()
    return {"items": [r.to_dict() for r in rows]}
