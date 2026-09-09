"""Data processing: normalization, deduplication, enrichment.

Centralizes the transformation logic that was previously inline in the
ingestion module. Separated for testability and reuse across domains.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nexus.core.logging_setup import get_logger
from nexus.core.models import EntityModel, EventModel

log = get_logger("nexus.data.processing")


def normalize_address(address: str) -> str:
    """Normalize an Ethereum address (or any entity ID) to lowercase, stripped."""
    return address.lower().strip()


def normalize_event(event: EventModel) -> EventModel:
    """Apply standard normalization to an event model."""
    event.from_entity = normalize_address(event.from_entity)
    event.to_entity = normalize_address(event.to_entity)
    if event.tx_hash:
        event.tx_hash = event.tx_hash.lower().strip()
    # Ensure timezone-aware timestamp
    if event.timestamp.tzinfo is None:
        event.timestamp = event.timestamp.replace(tzinfo=timezone.utc)
    return event


def normalize_entity(entity: EntityModel) -> EntityModel:
    """Apply standard normalization to an entity model."""
    entity.id = normalize_address(entity.id)
    if entity.first_seen and entity.first_seen.tzinfo is None:
        entity.first_seen = entity.first_seen.replace(tzinfo=timezone.utc)
    if entity.last_seen and entity.last_seen.tzinfo is None:
        entity.last_seen = entity.last_seen.replace(tzinfo=timezone.utc)
    return entity


def deduplicate_events(events: list[EventModel]) -> list[EventModel]:
    """Remove duplicate events by ID, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[EventModel] = []
    for e in events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    return unique


def compute_value_eth(value_wei: int) -> float:
    """Convert Wei to ETH."""
    return value_wei / 1e18


def enrich_event_attributes(event: EventModel) -> EventModel:
    """Add computed attributes to an event."""
    attrs = dict(event.attributes)
    attrs["value_eth"] = compute_value_eth(event.value_wei)
    if event.gas_used and event.gas_price_gwei:
        attrs["gas_cost_eth"] = (event.gas_used * event.gas_price_gwei) / 1e9
    event.attributes = attrs
    return event
