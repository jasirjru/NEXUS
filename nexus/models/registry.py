"""Model registry: versioned artifacts + DB records + promotion workflow.

Keeps things simple and auditable: every trained model is serialized to the
artifacts dir with a version, and registered in the model_registry table with
metrics and params. Promotion to production is explicit.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
from sqlalchemy.orm import Session

from nexus.config import settings
from nexus.core.logging_setup import get_logger
from nexus.db.schema import ModelRecord

log = get_logger("nexus.models.registry")


class ModelRegistry:
    def __init__(self, db: Session):
        self.db = db
        self.artifacts = settings.artifacts_path / "models"
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def register(
        self, name: str, version: str, model: object, metrics: dict,
        params: dict | None = None, stage: str = "development",
    ) -> ModelRecord:
        path = self.artifacts / f"{name}__{version}.joblib"
        joblib.dump(model, path)
        rec = ModelRecord(
            name=name, version=version, stage=stage, metrics=metrics,
            params=params or {}, artifact_path=str(path),
        )
        existing = (
            self.db.query(ModelRecord)
            .filter(ModelRecord.name == name, ModelRecord.version == version)
            .one_or_none()
        )
        if existing:
            existing.metrics = metrics
            existing.params = params or {}
            existing.stage = stage
            existing.artifact_path = str(path)
            rec = existing
        else:
            self.db.add(rec)
        self.db.commit()
        log.info("registered model %s v%s stage=%s metrics=%s", name, version, stage, metrics)
        return rec

    def get_production(self, name: str) -> ModelRecord | None:
        return (
            self.db.query(ModelRecord)
            .filter(ModelRecord.name == name, ModelRecord.stage == "production")
            .order_by(ModelRecord.created_at.desc())
            .first()
        )

    def promote(self, name: str, version: str, stage: str = "production") -> ModelRecord | None:
        rec = (
            self.db.query(ModelRecord)
            .filter(ModelRecord.name == name, ModelRecord.version == version)
            .one_or_none()
        )
        if rec is None:
            return None
        # demote any other production versions
        for other in self.db.query(ModelRecord).filter(
            ModelRecord.name == name, ModelRecord.stage == "production"
        ):
            other.stage = "archived"
        rec.stage = stage
        self.db.commit()
        log.info("promoted %s v%s -> %s", name, version, stage)
        return rec

    def load(self, name: str, version: str | None = None):
        q = self.db.query(ModelRecord).filter(ModelRecord.name == name)
        if version:
            rec = q.filter(ModelRecord.version == version).one_or_none()
        else:
            rec = q.order_by(ModelRecord.created_at.desc()).first()
        if rec is None or rec.artifact_path is None:
            return None
        return joblib.load(rec.artifact_path)

    def list_models(self) -> list[dict]:
        return [r.to_dict() for r in self.db.query(ModelRecord).order_by(ModelRecord.name).all()]
