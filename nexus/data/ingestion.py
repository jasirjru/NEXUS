"""Ingestion pipeline: validate -> normalize -> entity resolution -> event store.

Idempotent by design: re-running ingestion upserts entities and skips events
whose ids already exist, so the demo dataset can be refreshed safely.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus.core.errors import ValidationError
from nexus.core.logging_setup import get_logger
from nexus.core.models import EntityModel, EventModel
from nexus.data.providers.base import DataProvider
from nexus.db.schema import Entity, Event

log = get_logger("nexus.data.ingestion")

WEI_EPS = 10**18
MIN_TS = 1438269973  # Ethereum genesis minus margin; catches nonsense dates


@dataclass
class IngestionStats:
    entities_upserted: int = 0
    events_seen: int = 0
    events_inserted: int = 0
    events_invalid: int = 0


def _validate(ev: EventModel) -> None:
    """Reject malformed events early with precise errors."""
    if ev.id is None or len(ev.id) > 80:
        raise ValidationError(f"bad event id: {ev.id!r}")
    if ev.from_entity == ev.to_entity:
        raise ValidationError(f"self-loop event {ev.id}")
    if ev.value_wei < 0 or ev.value_wei > 10**25:
        raise ValidationError(f"implausible value on {ev.id}: {ev.value_wei}")
    epoch = ev.timestamp.timestamp() if ev.timestamp.tzinfo else ev.timestamp.replace(tzinfo=None).timestamp()
    if epoch < MIN_TS:
        raise ValidationError(f"implausible timestamp on {ev.id}: {ev.timestamp}")


def normalize(ev: EventModel) -> EventModel:
    """Canonical form: lowercase addresses, trimmed hashes, tz-aware UTC."""
    ev.from_entity = ev.from_entity.lower().strip()
    ev.to_entity = ev.to_entity.lower().strip()
    if ev.tx_hash:
        ev.tx_hash = ev.tx_hash.lower().strip()
    if ev.timestamp.tzinfo is None:
        from datetime import timezone

        ev.timestamp = ev.timestamp.replace(tzinfo=timezone.utc)
    return ev


def upsert_entity(db: Session, em: EntityModel) -> bool:
    row = db.get(Entity, em.id)
    if row is None:
        row = Entity(
            id=em.id,
            type=em.type.value,
            label=em.label,
            first_seen=None,
            last_seen=None,
            attributes=dict(em.attributes),
        )
        db.add(row)
        return True
    changed = False
    if em.label and row.label != em.label:
        row.label = em.label
        changed = True
    for k, v in em.attributes.items():
        if row.attributes.get(k) != v:
            row.attributes = {**row.attributes, k: v}
            changed = True
    return changed


def insert_event(db: Session, ev: EventModel) -> bool:
    if db.get(Event, ev.id) is not None:
        return False
    db.add(
        Event(
            id=ev.id,
            type=ev.type.value,
            block_number=ev.block_number,
            tx_hash=ev.tx_hash,
            timestamp=ev.timestamp,
            from_entity=ev.from_entity,
            to_entity=ev.to_entity,
            value_wei=ev.value_wei,
            gas_used=ev.gas_used,
            gas_price_gwei=ev.gas_price_gwei,
            token_symbol=ev.token_symbol,
            token_amount=ev.token_amount,
            attributes=ev.attributes,
        )
    )
    return True


def run_ingestion(db: Session, provider: DataProvider | None = None,
                  entity_batch: int = 2000, event_batch: int = 2000) -> IngestionStats:
    """Full ingestion run. Commits in batches; returns stats for logging/tests."""
    from nexus.data.providers.base import get_provider

    provider = provider or get_provider()
    stats = IngestionStats()

    existing_entities = set(db.execute(select(Entity.id)).scalars())
    buffer: list[EntityModel] = []
    for em in provider.iter_entities():
        buffer.append(em)
        if len(buffer) >= entity_batch:
            stats.entities_upserted += _flush_entities(db, buffer, existing_entities)
            buffer = []
    stats.entities_upserted += _flush_entities(db, buffer, existing_entities)
    db.commit()

    existing_events = set(db.execute(select(Event.id)).scalars())
    ev_buffer: list[EventModel] = []
    for ev in provider.iter_events():
        stats.events_seen += 1
        ev_buffer.append(ev)
        if len(ev_buffer) >= event_batch:
            stats.events_inserted += _flush_events(db, ev_buffer, existing_events, stats)
            ev_buffer = []
            db.commit()
    stats.events_inserted += _flush_events(db, ev_buffer, existing_events, stats)
    db.commit()

    log.info(
        "ingestion complete: entities=%d events_seen=%d inserted=%d invalid=%d",
        stats.entities_upserted, stats.events_seen, stats.events_inserted, stats.events_invalid,
    )
    provider.close()
    return stats


def _flush_entities(db: Session, buffer: list[EntityModel], existing: set[str]) -> int:
    changed = 0
    for em in buffer:
        if em.id not in existing:
            existing.add(em.id)
        if upsert_entity(db, em):
            changed += 1
    db.flush()
    return changed


def _flush_events(db: Session, buffer: list[EventModel], seen: set[str], stats: IngestionStats) -> int:
    inserted = 0
    new_events: list[EventModel] = []
    for ev in buffer:
        if ev.id in seen:
            continue
        try:
            ev = normalize(ev)
            _validate(ev)
        except ValidationError as e:
            stats.events_invalid += 1
            log.warning("skipping invalid event: %s", e)
            continue
        try:
            if insert_event(db, ev):
                seen.add(ev.id)
                inserted += 1
                new_events.append(ev)
        except IntegrityError:
            # Already inserted within the current unflushed batch; keep the
            # existing row and continue (ingestion stays idempotent).
            db.rollback()
            seen.add(ev.id)
    if not inserted:
        return 0
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        inserted = 0
        new_events = []
        for ev in buffer:
            if ev.id in seen:
                continue
            try:
                ev = normalize(ev)
                _validate(ev)
                if insert_event(db, ev):
                    db.flush()
                    seen.add(ev.id)
                    inserted += 1
                    new_events.append(ev)
            except IntegrityError:
                db.rollback()
                seen.add(ev.id)

    # update entity first/last seen from event timestamps
    from datetime import datetime as _datetime
    from datetime import timezone as _tz

    def _as_utc(v):
        if v is None:
            return None
        if isinstance(v, str):
            v = _datetime.fromisoformat(v)
        return v if v.tzinfo else v.replace(tzinfo=_tz.utc)

    touched: dict[str, Entity] = {}
    for ev in new_events:
        ts = _as_utc(ev.timestamp)
        for ent_id in (ev.from_entity, ev.to_entity):
            row = touched.get(ent_id) or db.get(Entity, ent_id)
            if row is None:
                row = Entity(id=ent_id, type="wallet")
                db.add(row)
                touched[ent_id] = row
            else:
                touched[ent_id] = row
            row_first = _as_utc(row.first_seen)
            row_last = _as_utc(row.last_seen)
            if row_first is None or ts < row_first:
                row.first_seen = ts
            if row_last is None or ts > row_last:
                row.last_seen = ts
    db.flush()
    return inserted
