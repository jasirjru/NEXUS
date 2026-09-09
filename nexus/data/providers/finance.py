"""Finance domain adapter: maps financial entities/events to the NEXUS contract.

Entities: accounts, tickers, exchanges, funds
Events: trades, orders, transfers, dividends
Relationships: account→ticker (holdings), account→account (transfers)

This adapter demonstrates that the core NEXUS architecture is domain-independent:
the same feature engine, anomaly detection, risk scoring, and investigation
pipeline works on any entity+event+relationship+time domain.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from nexus.core.models import EntityModel, EntityType, EventModel, EventType
from nexus.data.providers.base import DataProvider


class FinanceProvider(DataProvider):
    """Demo finance provider generating synthetic market activity.

    In production, this would connect to market data APIs (e.g., Alpaca,
    Interactive Brokers, Bloomberg) or read from a trade database.
    """

    name = "finance"

    def __init__(self, n_accounts: int = 30, n_events: int = 500, seed: int = 42) -> None:
        self.n_accounts = n_accounts
        self.n_events = n_events
        self.rng = np.random.RandomState(seed)
        self.tickers = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "NVDA", "JPM", "GS", "BRK"]

    def iter_entities(self, batch: int = 500) -> Iterator[EntityModel]:
        for i in range(self.n_accounts):
            yield EntityModel(
                id=f"acct:{i:04d}",
                type=EntityType.WALLET,  # reuse wallet type for accounts
                label=f"Account {i}",
                attributes={"domain": "finance", "account_type": self.rng.choice(["retail", "institutional", "hft"])},
            )
        for ticker in self.tickers:
            yield EntityModel(
                id=f"ticker:{ticker}",
                type=EntityType.TOKEN,  # reuse token type for tickers
                label=ticker,
                attributes={"domain": "finance", "asset_class": "equity"},
            )

    def iter_events(self, batch: int = 500) -> Iterator[EventModel]:
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        accounts = [f"acct:{i:04d}" for i in range(self.n_accounts)]

        for seq in range(self.n_events):
            acct = self.rng.choice(accounts)
            ticker = f"ticker:{self.rng.choice(self.tickers)}"
            ts = base_time + timedelta(hours=seq * 0.5 + self.rng.uniform(0, 0.5))
            trade_value = float(self.rng.lognormal(mean=8, sigma=1.5))  # $ value
            event_id = hashlib.md5(f"fin:{seq}:{acct}".encode()).hexdigest()[:16]

            yield EventModel(
                id=f"fin:{event_id}",
                type=EventType.TRANSACTION,
                timestamp=ts,
                from_entity=acct,
                to_entity=ticker,
                value_wei=int(trade_value * 1e18),  # reuse value_wei field
                attributes={
                    "domain": "finance",
                    "trade_type": self.rng.choice(["buy", "sell"]),
                    "quantity": int(self.rng.lognormal(3, 1)),
                    "source": "finance_demo",
                },
            )

    def close(self) -> None:
        pass
