"""Data layer tests: demo provider determinism, validation, entity resolution."""

from __future__ import annotations

from nexus.data.entity_resolution import run_entity_resolution
from nexus.data.ingestion import normalize, run_ingestion
from nexus.data.providers.base import get_provider
from nexus.data.providers.demo import DemoEthereumProvider
from nexus.core.models import EventModel, EventType
from datetime import datetime, timezone


def test_demo_provider_is_deterministic():
    p1 = [e.id for e in DemoEthereumProvider().iter_entities()]
    p2 = [e.id for e in DemoEthereumProvider().iter_entities()]
    assert p1 == p2


def test_demo_provider_yields_events():
    events = list(DemoEthereumProvider().iter_events())
    assert len(events) > 1000
    assert all(e.from_entity and e.to_entity for e in events)


def test_get_provider_factory():
    assert get_provider("demo").name == "demo"


def test_normalize_lowercases():
    ev = EventModel(
        id="x1", type=EventType.TRANSACTION, timestamp=datetime(2026, 1, 1),
        from_entity="0xABC", to_entity="0xDEF ", value_wei=5,
    )
    out = normalize(ev)
    assert out.from_entity == "0xabc" and out.to_entity == "0xdef"


def test_ingestion_is_idempotent(db):
    # capture pre-existing event count so this test is order-independent
    from sqlalchemy import func, select

    from nexus.db.schema import Event

    before = db.scalar(select(func.count()).select_from(Event)) or 0
    s1 = run_ingestion(db, provider=DemoEthereumProvider(), event_batch=3000)
    s2 = run_ingestion(db, provider=DemoEthereumProvider(), event_batch=3000)
    after = db.scalar(select(func.count()).select_from(Event)) or 0
    assert after == before + s1.events_inserted
    assert s2.events_inserted == 0  # second run inserts nothing new


def test_entity_resolution(db):
    run_ingestion(db, provider=DemoEthereumProvider(), event_batch=3000)
    n = run_entity_resolution(db)
    assert n >= 0  # clusters may or may not exist; must not crash
