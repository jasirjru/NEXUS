"""Tests for domain adapters (Finance and Cybersecurity).

Verifies that NEXUS is domain-independent: the entity/event/relationship/time
contract applies to financial markets and network security just as well as Ethereum.
"""

from __future__ import annotations

from datetime import datetime
import pytest

from nexus.core.models import EntityType, EventType
from nexus.data.ingestion import run_ingestion
from nexus.data.providers.base import get_provider
from nexus.data.providers.cybersecurity import CybersecurityProvider
from nexus.data.providers.finance import FinanceProvider


class TestFinanceProvider:
    def test_factory_registration(self):
        provider = get_provider("finance")
        assert isinstance(provider, FinanceProvider)
        assert provider.name == "finance"

    def test_entities_generated(self):
        provider = FinanceProvider(n_accounts=15, seed=123)
        entities = list(provider.iter_entities())
        assert len(entities) == 15 + len(provider.tickers)

        # Check account entities
        accounts = [e for e in entities if e.id.startswith("acct:")]
        assert len(accounts) == 15
        assert all(e.attributes.get("domain") == "finance" for e in accounts)
        assert all(e.type == EntityType.WALLET for e in accounts)

        # Check ticker entities
        tickers = [e for e in entities if e.id.startswith("ticker:")]
        assert len(tickers) == len(provider.tickers)
        assert all(e.type == EntityType.TOKEN for e in tickers)

    def test_events_generated(self):
        provider = FinanceProvider(n_accounts=10, n_events=100, seed=42)
        events = list(provider.iter_events())
        assert len(events) == 100
        for ev in events:
            assert ev.id
            assert ev.timestamp
            assert ev.from_entity
            assert ev.to_entity
            assert ev.value_wei is not None
            assert ev.type in (EventType.TRANSACTION, EventType.CONTRACT_CALL, EventType.TRANSFER)

    def test_ingestion_into_db(self, db):
        provider = FinanceProvider(n_accounts=10, n_events=80, seed=42)
        stats = run_ingestion(db, provider=provider, event_batch=200)
        assert stats.entities_upserted > 0
        assert stats.events_inserted > 0


class TestCybersecurityProvider:
    def test_factory_registration(self):
        provider = get_provider("cybersecurity")
        assert isinstance(provider, CybersecurityProvider)
        assert provider.name == "cybersecurity"

    def test_entities_generated(self):
        provider = CybersecurityProvider(n_hosts=20, seed=99)
        entities = list(provider.iter_entities())
        assert len(entities) == 20 + len(provider.services)

        hosts = [e for e in entities if e.id.startswith("host:")]
        assert len(hosts) == 20
        assert all(e.attributes.get("domain") == "cybersecurity" for e in hosts)
        assert all("ip" in e.attributes for e in hosts)

        services = [e for e in entities if e.id.startswith("service:")]
        assert len(services) == len(provider.services)

    def test_events_generated(self):
        provider = CybersecurityProvider(n_hosts=15, n_events=120, seed=42)
        events = list(provider.iter_events())
        assert len(events) == 120
        for ev in events:
            assert ev.id
            assert ev.timestamp
            assert ev.from_entity
            assert ev.to_entity
            assert ev.type in (EventType.TRANSACTION, EventType.CONTRACT_CALL, EventType.TRANSFER)
            assert "domain" in ev.attributes

    def test_ingestion_into_db(self, db):
        provider = CybersecurityProvider(n_hosts=15, n_events=90, seed=42)
        stats = run_ingestion(db, provider=provider, event_batch=200)
        assert stats.entities_upserted > 0
        assert stats.events_inserted > 0
