"""Domain models (Pydantic) for the Ethereum intelligence domain.

The shapes here are deliberately generic: entity + event + relationship + time.
A future domain adapter (finance, cybersecurity) can reuse these contracts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    WALLET = "wallet"
    CONTRACT = "contract"
    TOKEN = "token"
    PROTOCOL = "protocol"
    BLOCK = "block"
    CLUSTER = "cluster"


class EventType(str, Enum):
    TRANSFER = "transfer"
    CONTRACT_CALL = "contract_call"
    CONTRACT_CREATION = "contract_creation"
    TRANSACTION = "transaction"
    PROTOCOL_INTERACTION = "protocol_interaction"


class RelationshipType(str, Enum):
    WALLET_WALLET = "wallet_to_wallet"
    WALLET_CONTRACT = "wallet_to_contract"
    CONTRACT_PROTOCOL = "contract_to_protocol"
    WALLET_TOKEN = "wallet_to_token"
    TOKEN_WALLET = "token_to_wallet"
    PROTOCOL_WALLET = "protocol_to_wallet"


class EntityModel(BaseModel):
    id: str
    type: EntityType
    label: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class EventModel(BaseModel):
    id: str
    type: EventType
    block_number: int | None = None
    tx_hash: str | None = None
    timestamp: datetime
    from_entity: str
    to_entity: str
    value_wei: int = 0
    gas_used: int | None = None
    gas_price_gwei: float | None = None
    token_symbol: str | None = None
    token_amount: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class RelationshipModel(BaseModel):
    src: str
    dst: str
    type: RelationshipType
    first_seen: datetime
    last_seen: datetime
    interaction_count: int = 1
    total_value_wei: int = 0


class ScoreModel(BaseModel):
    """Any numeric output of an ML component, always with provenance."""

    entity_id: str
    as_of: datetime
    score_name: str  # e.g. "anomaly_iforest", "risk_probability"
    value: float
    confidence: float | None = None
    provenance_source: str
    details: dict[str, Any] = Field(default_factory=dict)
