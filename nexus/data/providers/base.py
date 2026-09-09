"""Data provider abstraction: the single interface NEXUS uses to obtain domain data.

Real providers (JSON-RPC, Etherscan-style APIs) and the deterministic demo
provider both implement this. The rest of the system never talks to a chain
directly, so any domain can be swapped by writing a new provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from nexus.core.models import EntityModel, EventModel


class DataProvider(ABC):
    """Boundary for external data. Implementations must be deterministic OR
    explicitly resumable (cursor-based); NEXUS ingests in bounded batches."""

    name: str = "base"

    @abstractmethod
    def iter_entities(self, batch: int = 500) -> Iterator[EntityModel]:
        """Yield entities to upsert."""

    @abstractmethod
    def iter_events(self, batch: int = 500) -> Iterator[EventModel]:
        """Yield events in chronological order."""

    def close(self) -> None:  # optional cleanup
        return None


def get_provider(name: str | None = None) -> DataProvider:
    """Factory resolving a provider by settings/config name."""
    from nexus.config import settings

    name = (name or settings.data_provider).lower()
    if name == "demo":
        from nexus.data.providers.demo import DemoEthereumProvider

        return DemoEthereumProvider()
    if name == "rpc":
        from nexus.data.providers.rpc import RpcProvider

        return RpcProvider()
    if name == "finance":
        from nexus.data.providers.finance import FinanceProvider

        return FinanceProvider()
    if name == "cybersecurity":
        from nexus.data.providers.cybersecurity import CybersecurityProvider

        return CybersecurityProvider()
    raise ValueError(f"Unknown data provider: {name!r} (available: demo, rpc, finance, cybersecurity)")
