"""Provenance types: observed facts, ML inference, LLM hypothesis, unknown.

This is the epistemic backbone of NEXUS. Every claim produced anywhere in the
system carries one of these types so the UI and reports never blur the line
between measured data and interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ClaimType(str, Enum):
    OBSERVED_FACT = "observed_fact"  # directly measured data
    ML_INFERENCE = "ml_inference"  # anomaly score / probability / model output
    LLM_HYPOTHESIS = "llm_hypothesis"  # interpretation based on evidence
    UNKNOWN = "unknown"  # information that cannot currently be established


@dataclass
class Provenance:
    """Where a claim came from: source system + identifiers + timestamp."""

    claim_type: ClaimType
    source: str  # e.g. "event_store", "iforest_v1", "investigator"
    references: list[str] = field(default_factory=list)  # ids of backing records
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_type": self.claim_type.value,
            "source": self.source,
            "references": self.references,
            "created_at": self.created_at.isoformat(),
            "notes": self.notes,
        }


@dataclass
class Evidence:
    """A single evidence item attached to a finding, report, or answer."""

    claim: str
    provenance: Provenance
    weight: float = 1.0  # relative importance, 0..1

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "provenance": self.provenance.to_dict(),
            "weight": self.weight,
        }
