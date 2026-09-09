"""SQLAlchemy ORM schema for the NEXUS event store and operational tables."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- entities
class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "attributes": self.attributes,
        }


# ---------------------------------------------------------------- events
class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    tx_hash: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    from_entity: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    to_entity: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    # wei values exceed 64-bit range; stored as float (ETH-precision preserved via /1e18 in features)
    value_wei: Mapped[float] = mapped_column(Float, default=0.0)
    gas_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gas_price_gwei: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    token_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_events_entity_time", "from_entity", "timestamp"),
        Index("ix_events_to_time", "to_entity", "timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "block_number": self.block_number,
            "tx_hash": self.tx_hash,
            "timestamp": self.timestamp.isoformat(),
            "from_entity": self.from_entity,
            "to_entity": self.to_entity,
            "value_wei": self.value_wei,
            "gas_used": self.gas_used,
            "gas_price_gwei": self.gas_price_gwei,
            "token_symbol": self.token_symbol,
            "token_amount": self.token_amount,
            "attributes": self.attributes,
        }


# ---------------------------------------------------------------- scores
class ScoreRecord(Base):
    """Persisted output of any ML component (anomaly scores, risk, etc.)."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    score_name: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    provenance_source: Mapped[str] = mapped_column(String(128))
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "as_of": self.as_of.isoformat(),
            "score_name": self.score_name,
            "value": self.value,
            "confidence": self.confidence,
            "provenance_source": self.provenance_source,
            "details": self.details,
        }


# ---------------------------------------------------------------- investigations
class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    report_json: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_calls: Mapped[dict] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "question": self.question,
            "answer": self.answer,
            "report_json": self.report_json,
            "tool_calls": self.tool_calls,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------- alerts
class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    metric: Mapped[str] = mapped_column(String(64))  # risk | anomaly | confidence | ...
    operator: Mapped[str] = mapped_column(String(8))  # > | < | >= | <= | ==
    threshold: Mapped[float] = mapped_column(Float)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    channels: Mapped[list] = mapped_column(JSON, default=list)  # ["dashboard","email","webhook","slack"]
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
            "entity_id": self.entity_id,
            "channels": self.channels,
            "webhook_url": self.webhook_url,
            "enabled": self.enabled,
        }


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "entity_id": self.entity_id,
            "severity": self.severity,
            "title": self.title,
            "body": self.body,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
            "acknowledged": self.acknowledged,
        }


# ---------------------------------------------------------------- automations
class Automation(Base):
    __tablename__ = "automations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    trigger_metric: Mapped[str] = mapped_column(String(64))
    trigger_operator: Mapped[str] = mapped_column(String(8))
    trigger_threshold: Mapped[float] = mapped_column(Float)
    steps: Mapped[list] = mapped_column(JSON, default=list)  # ordered workflow steps
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "trigger_metric": self.trigger_metric,
            "trigger_operator": self.trigger_operator,
            "trigger_threshold": self.trigger_threshold,
            "steps": self.steps,
            "requires_approval": self.requires_approval,
            "enabled": self.enabled,
        }


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    automation_id: Mapped[int] = mapped_column(Integer, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running")  # running|awaiting_approval|completed|failed
    step_results: Mapped[dict] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "automation_id": self.automation_id,
            "entity_id": self.entity_id,
            "status": self.status,
            "step_results": self.step_results,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


# ---------------------------------------------------------------- evaluations
class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # anomaly | risk | ablation | llm
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "metrics": self.metrics,
            "config": self.config,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------- feedback loop
class Outcome(Base):
    """Ground-truth labels / outcomes used to close the intelligence loop."""

    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    label: Mapped[int] = mapped_column(Integer)  # 1 = confirmed anomalous/malicious, 0 = benign
    source: Mapped[str] = mapped_column(String(128), default="analyst")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "as_of": self.as_of.isoformat(),
            "label": self.label,
            "source": self.source,
            "notes": self.notes,
        }


# ---------------------------------------------------------------- mlops
class ModelRecord(Base):
    """Model registry entry."""

    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(24), default="development")  # development|staging|production|archived
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "stage": self.stage,
            "metrics": self.metrics,
            "params": self.params,
            "artifact_path": self.artifact_path,
            "created_at": self.created_at.isoformat(),
        }
