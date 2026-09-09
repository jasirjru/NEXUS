"""Entity endpoints: profiles, features, neighbors, timeline, ego graph."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus.core.errors import NotFoundError
from nexus.db.schema import Entity, Event, ScoreRecord
from nexus.db.session import get_db
from nexus.features.behavioral import compute_entity_features, load_events_frame
from sqlalchemy import cast, String

router = APIRouter(tags=["entities"])


def _latest_scores(db: Session, entity_id: str) -> dict:
    rows = (
        db.query(ScoreRecord)
        .filter(ScoreRecord.entity_id == entity_id)
        .order_by(ScoreRecord.as_of.desc())
        .limit(12)
        .all()
    )
    latest: dict[str, ScoreRecord] = {}
    for r in rows:
        latest.setdefault(r.score_name, r)
    return {
        name: {
            "value": round(r.value, 4),
            "confidence": round(r.confidence, 4) if r.confidence is not None else None,
            "as_of": r.as_of.isoformat(),
            "source": r.provenance_source,
            "details": r.details,
        }
        for name, r in latest.items()
    }


@router.get("/entities")
def list_entities(
    type: str | None = None,
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Entity)
    if type:
        query = query.filter(Entity.type == type)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            or_(func.lower(Entity.id).like(like), func.lower(func.coalesce(Entity.label, "")).like(like))
        )
    total = query.count()
    rows = query.order_by(Entity.id).offset(offset).limit(limit).all()
    return {"total": total, "items": [r.to_dict() for r in rows]}


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(Entity, entity_id)
    if row is None:
        raise NotFoundError(f"entity {entity_id} not found")
    n_tx = db.scalar(
        select(func.count()).select_from(Event).where(
            or_(Event.from_entity == entity_id, Event.to_entity == entity_id)
        )
    ) or 0
    return {
        **row.to_dict(),
        "total_events": n_tx,
        "scores": _latest_scores(db, entity_id),
    }


@router.get("/entities/{entity_id}/timeline")
def entity_timeline(
    entity_id: str, limit: int = Query(100, le=500), db: Session = Depends(get_db)
) -> dict:
    rows = (
        db.query(Event)
        .filter(or_(Event.from_entity == entity_id, Event.to_entity == entity_id))
        .order_by(Event.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {"items": [r.to_dict() for r in rows]}


@router.get("/entities/{entity_id}/neighbors")
def entity_neighbors(entity_id: str, limit: int = Query(20, le=100),
                     db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(Event.from_entity, Event.to_entity, func.count(), func.sum(Event.value_wei))
        .where(or_(Event.from_entity == entity_id, Event.to_entity == entity_id))
        .group_by(Event.from_entity, Event.to_entity)
    ).all()
    agg: dict[str, dict] = {}
    for src, dst, cnt, total in rows:
        other = dst if src == entity_id else src
        rec = agg.setdefault(other, {"entity_id": other, "count": 0, "value_wei": 0})
        rec["count"] += cnt
        rec["value_wei"] += int(total or 0)
    items = sorted(agg.values(), key=lambda r: r["count"], reverse=True)[:limit]
    labels = {
        e.id: e.label
        for e in db.query(Entity).filter(Entity.id.in_([i["entity_id"] for i in items])).all()
    }
    for i in items:
        i["label"] = labels.get(i["entity_id"])
    return {"items": items}


@router.get("/entities/{entity_id}/features")
def entity_features(entity_id: str, db: Session = Depends(get_db)) -> dict:
    events = load_events_frame(db)
    feats = compute_entity_features(events, as_of=events["timestamp"].max().to_pydatetime(),
                                    entities=[entity_id])
    if entity_id not in feats.index:
        raise NotFoundError(f"no features for {entity_id}")
    return {"entity_id": entity_id,
            "features": {k: round(float(v), 6) for k, v in feats.loc[entity_id].items()}}


@router.get("/entities/{entity_id}/ego-graph")
def ego_graph(entity_id: str, depth: int = Query(1, ge=1, le=2),
              limit: int = Query(30, le=100), db: Session = Depends(get_db)) -> dict:
    """Small graph for visualization: entity + strongest neighbors."""
    neighbors = entity_neighbors(entity_id, limit=limit, db=db)["items"]
    nodes = [{"id": entity_id, "label": None, "center": True}]
    edges = []
    ids = {entity_id}
    for n in neighbors:
        ids.add(n["entity_id"])
        nodes.append({"id": n["entity_id"], "label": n.get("label"), "center": False})
    rows = db.execute(
        select(Event.from_entity, Event.to_entity, func.count(), func.sum(Event.value_wei))
        .where(or_(Event.from_entity.in_(ids), Event.to_entity.in_(ids)))
        .group_by(Event.from_entity, Event.to_entity)
        .limit(500)
    ).all()
    for src, dst, cnt, total in rows:
        if src in ids and dst in ids:
            edges.append({
                "source": src, "target": dst, "weight": cnt,
                "value_wei": int(total or 0),
            })
    return {"nodes": nodes, "edges": edges}


@router.get("/graph")
def full_graph(limit: int = Query(60, le=200), db: Session = Depends(get_db)) -> dict:
    """Aggregate graph view for the Graph Explorer (strongest edges only)."""
    rows = db.execute(
        select(Event.from_entity, Event.to_entity, func.count(), func.sum(Event.value_wei))
        .group_by(Event.from_entity, Event.to_entity)
        .order_by(func.count().desc())
        .limit(limit * 3)
    ).all()
    degree: dict[str, int] = {}
    edges = []
    for src, dst, cnt, total in rows:
        edges.append({"source": src, "target": dst, "weight": int(cnt),
                      "value_wei": int(total or 0)})
        degree[src] = degree.get(src, 0) + cnt
        degree[dst] = degree.get(dst, 0) + cnt
    top = sorted(degree, key=degree.get, reverse=True)[:limit]
    top_set = set(top)
    labels = {e.id: e.label for e in db.query(Entity).filter(Entity.id.in_(top)).all()}
    nodes = [{"id": n, "label": labels.get(n), "degree": degree[n]} for n in top]
    edges = [e for e in edges if e["source"] in top_set and e["target"] in top_set][:limit * 2]
    return {"nodes": nodes, "edges": edges}
