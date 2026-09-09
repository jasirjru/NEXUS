"""Controlled tools for the LLM investigator.

Every tool:
- is DB-backed and deterministic (no free web access, no invented data),
- returns structured evidence items with provenance and evidence ids [E#],
- is registered in an allowlist the agent may call; nothing else executes.

Tools: get_transactions, get_entity_history, expand_graph, compare_behavior,
lookup_protocol, retrieve_evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.core.errors import NotFoundError, ToolDeniedError
from nexus.core.provenance import ClaimType, Evidence, Provenance
from nexus.db.schema import Entity, Event, ScoreRecord
from nexus.features.behavioral import compute_entity_features, load_events_frame

MAX_ROWS = 20  # context discipline: bounded tool outputs


@dataclass
class ToolResult:
    tool: str
    args: dict[str, Any]
    summary: str
    evidence: list[Evidence] = field(default_factory=list)
    data: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "args": self.args,
            "summary": self.summary,
            "evidence": [e.to_dict() for e in self.evidence],
            "data": self.data,
        }


class ToolRegistry:
    def __init__(self, db: Session):
        self.db = db
        self._tools: dict[str, Callable[..., ToolResult]] = {
            "get_transactions": self.get_transactions,
            "get_entity_history": self.get_entity_history,
            "expand_graph": self.expand_graph,
            "compare_behavior": self.compare_behavior,
            "lookup_protocol": self.lookup_protocol,
            "retrieve_evidence": self.retrieve_evidence,
        }

    def allowlist(self) -> list[str]:
        return sorted(self._tools)

    def call(self, name: str, **kwargs) -> ToolResult:
        fn = self._tools.get(name)
        if fn is None:
            raise ToolDeniedError(f"tool {name!r} not in allowlist")
        return fn(**kwargs)

    # ------------------------------------------------------------ tools
    def get_transactions(self, entity_id: str, limit: int = 10,
                         direction: str = "both") -> ToolResult:
        q = select(Event).order_by(Event.timestamp.desc())
        rows = self.db.execute(q).scalars().all()
        rows = [r for r in rows if entity_id in (r.from_entity, r.to_entity)]
        if direction == "outgoing":
            rows = [r for r in rows if r.from_entity == entity_id]
        elif direction == "incoming":
            rows = [r for r in rows if r.to_entity == entity_id]
        rows = rows[: max(1, min(limit, MAX_ROWS))]
        ev = []
        data = []
        for i, r in enumerate(rows):
            eid = f"E{len(ev) + 1}"
            ev.append(Evidence(
                claim=f"tx {r.tx_hash or r.id}: {r.from_entity[:10]}.. -> {r.to_entity[:10]}.. "
                      f"value={r.value_wei / 1e18:.4f} ETH at {r.timestamp.isoformat()}",
                provenance=Provenance(
                    claim_type=ClaimType.OBSERVED_FACT, source="event_store",
                    references=[r.id],
                ),
            ))
            data.append(r.to_dict())
        return ToolResult(
            tool="get_transactions",
            args={"entity_id": entity_id, "limit": limit, "direction": direction},
            summary=f"{len(rows)} transactions for {entity_id}",
            evidence=ev, data=data,
        )

    def get_entity_history(self, entity_id: str) -> ToolResult:
        row = self.db.get(Entity, entity_id)
        if row is None:
            raise NotFoundError(f"entity {entity_id} not found")
        scores = (
            self.db.query(ScoreRecord)
            .filter(ScoreRecord.entity_id == entity_id)
            .order_by(ScoreRecord.as_of.desc())
            .limit(5)
            .all()
        )
        ev = [
            Evidence(
                claim=f"entity {entity_id} first seen {row.first_seen}, last seen {row.last_seen}, type={row.type}",
                provenance=Provenance(ClaimType.OBSERVED_FACT, "event_store", [entity_id]),
            )
        ]
        for s in scores:
            ev.append(Evidence(
                claim=f"score {s.score_name}={s.value:.3f}"
                      + (f" confidence={s.confidence:.3f}" if s.confidence is not None else "")
                      + f" as of {s.as_of.date()}",
                provenance=Provenance(
                    ClaimType.ML_INFERENCE, s.provenance_source, [f"score:{s.id}"]
                ),
            ))
        return ToolResult(
            tool="get_entity_history",
            args={"entity_id": entity_id},
            summary=f"profile + last {len(scores)} scores for {entity_id}",
            evidence=ev,
            data=[row.to_dict(), *[s.to_dict() for s in scores]],
        )

    def expand_graph(self, entity_id: str, max_neighbors: int = 8) -> ToolResult:
        rows = self.db.execute(
            select(Event.from_entity, Event.to_entity, Event.value_wei, Event.timestamp)
            .order_by(Event.timestamp.desc())
        ).all()
        neighbors: dict[str, dict] = {}
        for src, dst, val, ts in rows:
            other = None
            if src == entity_id:
                other = dst
            elif dst == entity_id:
                other = src
            if other is None:
                continue
            n = neighbors.setdefault(other, {"count": 0, "value_wei": 0, "last": ts})
            n["count"] += 1
            n["value_wei"] += val
            n["last"] = max(n["last"], ts)
            if len(neighbors) >= max_neighbors * 4:
                break
        top = sorted(neighbors.items(), key=lambda kv: kv[1]["count"], reverse=True)[:max_neighbors]
        ev = []
        data = []
        for i, (other, info) in enumerate(top):
            eid = f"E{len(ev) + 1}"
            ev.append(Evidence(
                claim=f"interacted with {other} {info['count']}x, total {info['value_wei'] / 1e18:.3f} ETH, last {info['last'].date()}",
                provenance=Provenance(ClaimType.OBSERVED_FACT, "event_store", [entity_id, other]),
            ))
            data.append({"neighbor": other, **{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in info.items()}})
        return ToolResult(
            tool="expand_graph",
            args={"entity_id": entity_id, "max_neighbors": max_neighbors},
            summary=f"{len(top)} strongest neighbors of {entity_id}",
            evidence=ev, data=data,
        )

    def compare_behavior(self, entity_id: str, recent_days: int = 7) -> ToolResult:
        events = load_events_frame(self.db)
        now = events["timestamp"].max()
        feats = compute_entity_features(events, as_of=now.to_pydatetime(), entities=[entity_id])
        row = feats.loc[entity_id].to_dict() if entity_id in feats.index else {}
        ev = []
        interesting = [
            "tx_count_24h", "tx_count_7d", "tx_count_30d", "volume_7d_eth",
            "volume_30d_eth", "unique_counterparties_30d", "volume_recent_vs_hist",
            "new_counterparty_fraction", "inter_tx_mean_hours", "burstiness",
        ]
        for k in interesting:
            if k in row:
                ev.append(Evidence(
                    claim=f"feature {k} = {row[k]:.4g}",
                    provenance=Provenance(
                        ClaimType.ML_INFERENCE, "feature_engine", [f"feature:{k}"]
                    ),
                ))
        return ToolResult(
            tool="compare_behavior",
            args={"entity_id": entity_id, "recent_days": recent_days},
            summary=f"behavioral feature snapshot for {entity_id} ({len(ev)} features)",
            evidence=ev,
            data=[{k: float(v) for k, v in row.items()}],
        )

    def lookup_protocol(self, entity_id: str) -> ToolResult:
        row = self.db.get(Entity, entity_id)
        if row is None:
            raise NotFoundError(f"entity {entity_id} not found")
        label = row.label or ""
        ev = [
            Evidence(
                claim=f"entity {entity_id} labeled '{label}' (type={row.type})",
                provenance=Provenance(ClaimType.OBSERVED_FACT, "entity_store", [entity_id]),
            )
        ]
        protocols = (
            self.db.query(Entity).filter(Entity.type == "protocol").all()
        )
        return ToolResult(
            tool="lookup_protocol",
            args={"entity_id": entity_id},
            summary=f"entity lookup for {entity_id}: {label or 'unlabeled'}",
            evidence=ev,
            data=[p.to_dict() for p in protocols],
        )

    def retrieve_evidence(self, entity_id: str) -> ToolResult:
        scores = (
            self.db.query(ScoreRecord)
            .filter(ScoreRecord.entity_id == entity_id)
            .order_by(ScoreRecord.as_of.desc())
            .limit(10)
            .all()
        )
        ev = [
            Evidence(
                claim=f"{s.score_name}={s.value:.3f}"
                      + (f" confidence={s.confidence:.3f}" if s.confidence is not None else ""),
                provenance=Provenance(
                    ClaimType.ML_INFERENCE, s.provenance_source, [f"score:{s.id}"]
                ),
            )
            for s in scores
        ]
        return ToolResult(
            tool="retrieve_evidence",
            args={"entity_id": entity_id},
            summary=f"{len(scores)} stored scores for {entity_id}",
            evidence=ev,
            data=[s.to_dict() for s in scores],
        )
