"""System endpoints: health, storage stats, configuration (secrets redacted)."""

from __future__ import annotations

import platform

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus.config import settings
from nexus.db.schema import Alert, Automation, Event, Investigation, ScoreRecord
from nexus.db.session import check_db, get_db

router = APIRouter(tags=["system"])


@router.get("/system")
def system_info(db: Session = Depends(get_db)) -> dict:
    def count(model):
        return db.scalar(select(func.count()).select_from(model)) or 0

    return {
        "status": "ok" if check_db() else "degraded",
        "python": platform.python_version(),
        "database": settings.database_url.split("://")[0],
        "data_provider": settings.data_provider,
        "llm_provider": settings.llm_provider,
        "tables": {
            "entities": count(__import__("nexus.db.schema", fromlist=["Entity"]).Entity),
            "events": count(Event),
            "scores": count(ScoreRecord),
            "alerts": count(Alert),
            "investigations": count(Investigation),
            "automations": count(Automation),
        },
    }
