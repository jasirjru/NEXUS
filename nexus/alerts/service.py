"""Alert service + automation engine.

Alert rules evaluate over the latest ScoreRecords (risk/anomaly/confidence).
Automations trigger workflows built by the planner; steps execute in order,
with human-approval gates that pause the run (status=awaiting_approval) until
approved via the API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.agents import planner as planner_mod
from nexus.agents.investigator import Investigator
from nexus.alerts.channels import CHANNELS, OutgoingAlert
from nexus.core.errors import NotFoundError
from nexus.core.logging_setup import get_logger
from nexus.db.schema import (
    Alert,
    AlertRule,
    Automation,
    ScoreRecord,
    WorkflowRun,
)

log = get_logger("nexus.alerts.service")

_OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: abs(a - b) < 1e-9,
}


def latest_scores(db: Session) -> dict[str, dict[str, ScoreRecord]]:
    """entity_id -> {score_name: latest ScoreRecord}."""
    out: dict[str, dict[str, ScoreRecord]] = {}
    rows = db.execute(
        select(ScoreRecord).order_by(ScoreRecord.as_of.desc())
    ).scalars().all()
    for r in rows:
        out.setdefault(r.entity_id, {}).setdefault(r.score_name, r)
    return out


def evaluate_alert_rules(db: Session) -> list[Alert]:
    """Evaluate all enabled rules against the latest scores; persist new alerts."""
    rules = db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all()
    scores = latest_scores(db)
    created: list[Alert] = []
    for rule in rules:
        op = _OPS.get(rule.operator)
        if op is None:
            continue
        for entity_id, by_name in scores.items():
            if rule.entity_id and entity_id != rule.entity_id:
                continue
            rec = by_name.get(rule.metric)
            if rec is None:
                continue
            if op(rec.value, rule.threshold):
                alert = Alert(
                    rule_id=rule.id,
                    entity_id=entity_id,
                    severity="critical" if rec.value >= rule.threshold + 0.1 else "warning",
                    title=f"{rule.name}: {rule.metric}={rec.value:.2f} on {entity_id[:14]}..",
                    body=f"{rule.metric} is {rec.value:.3f} (threshold {rule.operator} {rule.threshold}) "
                         f"as of {rec.as_of.isoformat()}",
                    payload={"score_id": rec.id, "rule_id": rule.id},
                )
                db.add(alert)
                created.append(alert)
                for ch in rule.channels or ["dashboard"]:
                    channel = CHANNELS.get(ch)
                    if channel:
                        try:
                            if ch == "webhook":
                                channel.send(
                                    OutgoingAlert(title=alert.title, body=alert.body,
                                                  severity=alert.severity, entity_id=entity_id),
                                    url=rule.webhook_url,
                                )
                            else:
                                channel.send(
                                    OutgoingAlert(title=alert.title, body=alert.body,
                                                  severity=alert.severity, entity_id=entity_id)
                                )
                        except Exception as e:
                            log.error("alert channel %s failed: %s", ch, e)
    db.commit()
    if created:
        log.info("raised %d alerts", len(created))
    return created


# ---------------------------------------------------------------- automation
STEP_HANDLERS: dict[str, Any] = {}


def step(action: str):
    def deco(fn):
        STEP_HANDLERS[action] = fn
        return fn

    return deco


@step("investigate")
def _step_investigate(db: Session, run: WorkflowRun, params: dict) -> dict:
    inv = Investigator(db)
    report = inv.investigate(
        params["entity_id"],
        params.get("question", "Why is this entity unusual?"),
        persist=False,
    )
    return {"action": "investigate", "ok": True,
            "detail": report.answer[:500], "report": report.to_dict()}


@step("gather_evidence")
def _step_evidence(db: Session, run: WorkflowRun, params: dict) -> dict:
    inv = Investigator(db, llm=EchoClient())
    report = inv.investigate(params["entity_id"], "Show all evidence", persist=False)
    return {"action": "gather_evidence", "ok": True,
            "facts": len(report.observed_facts), "inference": len(report.ml_inference)}


@step("generate_report")
def _step_report(db: Session, run: WorkflowRun, params: dict) -> dict:
    return {"action": "generate_report", "ok": True,
            "detail": f"report for {params['entity_id']} attached to run {run.id}"}


@step("notify")
def _step_notify(db: Session, run: WorkflowRun, params: dict) -> dict:
    alert = Alert(
        entity_id=params["entity_id"],
        severity=params.get("severity", "warning"),
        title=params.get("title", f"Automation alert on {params['entity_id']}"),
        body=f"Raised by workflow run {run.id}",
        payload=params,
    )
    db.add(alert)
    return {"action": "notify", "ok": True}


@step("webhook")
def _step_webhook(db: Session, run: WorkflowRun, params: dict) -> dict:
    ch: WebhookChannel = CHANNELS["webhook"]
    ok = ch.send(
        OutgoingAlert(
            title=params.get("event", "nexus.workflow"),
            body=f"entity {params['entity_id']} run {run.id}",
            entity_id=params["entity_id"],
        ),
        url=params.get("url"),
    )
    return {"action": "webhook", "ok": ok}


@step("create_ticket")
def _step_ticket(db: Session, run: WorkflowRun, params: dict) -> dict:
    # integration point: external ticketing (Jira/GitHub). Persisted as a
    # high-severity dashboard alert with the ticket payload for now.
    alert = Alert(
        entity_id=params["entity_id"],
        severity="critical",
        title=f"TICKET: investigate {params['entity_id'][:14]}..",
        body=f"priority={params.get('priority', 'normal')} run={run.id}",
        payload={"kind": "ticket", **params},
    )
    db.add(alert)
    return {"action": "create_ticket", "ok": True}


@step("request_approval")
def _step_approval(db: Session, run: WorkflowRun, params: dict) -> dict:
    return {"action": "request_approval", "ok": True, "awaiting": True,
            "params": params}


APPROVAL_REQUIRED = {"request_approval"}


def run_automation(db: Session, automation: Automation, entity_id: str) -> WorkflowRun:
    run = WorkflowRun(automation_id=automation.id, entity_id=entity_id, status="running")
    db.add(run)
    db.commit()

    steps = planner_mod.plan_from_automation(automation.steps, entity_id,
                                             {"risk_context": automation.trigger_metric})
    results = []
    status = "completed"
    for s in steps:
        handler = STEP_HANDLERS.get(s.action)
        if handler is None:
            results.append({"action": s.action, "ok": False, "detail": "no handler"})
            continue
        try:
            res = handler(db, run, dict(s.params))
        except Exception as e:
            log.exception("step %s failed", s.action)
            res = {"action": s.action, "ok": False, "detail": str(e)}
        results.append(res)
        if s.action in APPROVAL_REQUIRED and res.get("awaiting"):
            status = "awaiting_approval"
            break  # pause until human approval

    run.step_results = results
    run.status = status
    if status == "completed":
        run.finished_at = datetime.now(timezone.utc)
    db.commit()
    log.info("automation %s run %d -> %s", automation.name, run.id, status)
    return run


def approve_run(db: Session, run_id: int, approve: bool = True) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError(f"workflow run {run_id} not found")
    if run.status != "awaiting_approval":
        raise NotFoundError(f"run {run_id} is not awaiting approval")
    if approve:
        automation = db.get(Automation, run.automation_id)
        results = list(run.step_results or [])
        done = {r.get("action") for r in results}
        steps = planner_mod.plan_from_automation(automation.steps, run.entity_id, {})
        status = "completed"
        for s in steps:
            if s.action in done:
                continue
            handler = STEP_HANDLERS.get(s.action)
            if handler is None:
                continue
            try:
                res = handler(db, run, dict(s.params))
            except Exception as e:
                res = {"action": s.action, "ok": False, "detail": str(e)}
            results.append(res)
            if s.action in APPROVAL_REQUIRED and res.get("awaiting"):
                status = "awaiting_approval"
                break
        run.step_results = results
        run.status = status
        if status == "completed":
            run.finished_at = datetime.now(timezone.utc)
    else:
        run.status = "rejected"
        run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return run
