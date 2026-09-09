"""Ethereum-specific data schemas and validation rules.

These schemas define the canonical shape of Ethereum domain data
before it enters the domain-independent NEXUS pipeline. Other domains
(finance, cybersecurity) would define their own schema modules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class EthereumTransactionSchema(BaseModel):
    """Schema for a raw Ethereum transaction before normalization."""

    tx_hash: str = Field(..., min_length=64, max_length=66)
    block_number: int = Field(..., ge=0)
    timestamp: datetime
    from_address: str = Field(..., min_length=40, max_length=42)
    to_address: str | None = Field(None, min_length=40, max_length=42)
    value_wei: int = Field(0, ge=0)
    gas_used: int = Field(0, ge=0)
    gas_price_gwei: float = Field(0.0, ge=0.0)
    input_data: str | None = None
    status: int = Field(1, ge=0, le=1)  # 0=failed, 1=success

    @field_validator("from_address", "to_address", mode="before")
    @classmethod
    def lowercase_address(cls, v: str | None) -> str | None:
        return v.lower() if v else v

    @field_validator("tx_hash", mode="before")
    @classmethod
    def lowercase_hash(cls, v: str) -> str:
        return v.lower()


class EthereumTokenTransferSchema(BaseModel):
    """Schema for an ERC-20/ERC-721 token transfer (decoded from logs)."""

    tx_hash: str
    log_index: int = Field(..., ge=0)
    block_number: int = Field(..., ge=0)
    timestamp: datetime
    contract_address: str  # token contract
    from_address: str
    to_address: str
    token_symbol: str | None = None
    amount: float = 0.0  # decoded token amount
    token_id: int | None = None  # for ERC-721

    @field_validator("from_address", "to_address", "contract_address", mode="before")
    @classmethod
    def lowercase_address(cls, v: str) -> str:
        return v.lower()


class EthereumBlockSchema(BaseModel):
    """Schema for an Ethereum block header."""

    number: int = Field(..., ge=0)
    hash: str
    timestamp: datetime
    miner: str
    gas_used: int = 0
    gas_limit: int = 0
    transaction_count: int = 0
    base_fee_gwei: float | None = None

    @field_validator("miner", mode="before")
    @classmethod
    def lowercase_address(cls, v: str) -> str:
        return v.lower()


# ---------------------------------------------------------------- Validation helpers

def validate_ethereum_address(address: str) -> bool:
    """Check if a string is a valid Ethereum address (0x + 40 hex chars)."""
    if not address:
        return False
    addr = address.lower().strip()
    if addr.startswith("0x"):
        addr = addr[2:]
    return len(addr) == 40 and all(c in "0123456789abcdef" for c in addr)


def validate_tx_hash(tx_hash: str) -> bool:
    """Check if a string is a valid Ethereum transaction hash."""
    if not tx_hash:
        return False
    h = tx_hash.lower().strip()
    if h.startswith("0x"):
        h = h[2:]
    return len(h) == 64 and all(c in "0123456789abcdef" for c in h)
