"""MLOps endpoints: model registry + pipeline trigger + monitoring."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from nexus.db.session import get_db
from nexus.models.registry import ModelRegistry

router = APIRouter(tags=["mlops"])


@router.get("/models")
def list_models(db: Session = Depends(get_db)) -> dict:
    return {"items": ModelRegistry(db).list_models()}


@router.post("/models/{name}/{version}/promote")
def promote(name: str, version: str, stage: str = "production",
            db: Session = Depends(get_db)) -> dict:
    rec = ModelRegistry(db).promote(name, version, stage)
    if rec is None:
        from nexus.core.errors import NotFoundError

        raise NotFoundError(f"model {name} v{version} not found")
    return rec.to_dict()


class PipelineRequest(BaseModel := __import__("pydantic").BaseModel):
    skip_ingest: bool = False


@router.post("/pipeline/run")
def run_pipeline(req: PipelineRequest, db: Session = Depends(get_db)) -> dict:
    from nexus.pipelines.intelligence import run_full_pipeline

    report = run_full_pipeline(db, skip_ingest=req.skip_ingest)
    return report.to_dict()
