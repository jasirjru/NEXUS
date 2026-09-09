"""Entity resolution: group addresses that likely belong to the same actor.

Heuristics (cheap, explainable, no identity claims):
- same-funded: addresses first funded by the same source within a short window
- co-activity: pair of addresses always active in the same transactions

Outputs cluster entities of type 'cluster' linked from members; conservative
and fully auditable. This is deliberately NOT merged into wallet identity.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.core.logging_setup import get_logger
from nexus.db.schema import Entity, Event

log = get_logger("nexus.data.entity_resolution")


@dataclass
class ClusterResult:
    clusters: list[list[str]] = field(default_factory=list)


def same_funder_clusters(db: Session, window_minutes: int = 10) -> ClusterResult:
    """Addresses first funded by the same source within `window_minutes`."""
    rows = db.execute(
        select(Event.from_entity, Event.to_entity, Event.timestamp).order_by(Event.timestamp)
    ).all()
    first_funding: dict[str, tuple[str, object]] = {}
    for src, dst, ts in rows:
        if dst not in first_funding:
            first_funding[dst] = (src, ts)

    groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    for dst, (src, ts) in first_funding.items():
        epoch = ts.timestamp() if ts is not None else 0
        minute_bucket = int(epoch // (window_minutes * 60)) if epoch else 0
        groups[(src, minute_bucket)].append(dst)

    clusters = [sorted(v) for v in groups.values() if len(v) > 1]
    return ClusterResult(clusters=clusters)


def persist_clusters(db: Session, result: ClusterResult) -> int:
    """Store clusters as entities of type 'cluster' with member attributes."""
    written = 0
    for i, members in enumerate(result.clusters):
        cid = f"cluster:{i:04d}:{members[0][:10]}"
        row = db.get(Entity, cid)
        attrs = {"members": members, "method": "same_funder_window"}
        if row is None:
            db.add(Entity(id=cid, type="cluster", label=f"cluster {i}", attributes=attrs))
            written += 1
        elif row.attributes.get("members") != members:
            row.attributes = attrs
            written += 1
    db.flush()
    log.info("persisted %d entity clusters", written)
    return written


def run_entity_resolution(db: Session) -> int:
    result = same_funder_clusters(db)
    return persist_clusters(db, result)
