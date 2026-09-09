"""Planner: deterministic multi-step workflow plans (used by automations).

Given an intelligence event (e.g., high-confidence anomaly), produce an
ordered, auditable workflow plan. Not LLM-driven: plans must be predictable
and reviewable. LLM involvement happens inside specific steps (investigate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowStep:
    action: str  # investigate | gather_evidence | generate_report | notify | webhook | create_ticket | request_approval
    params: dict[str, Any] = field(default_factory=dict)


def plan_high_confidence_anomaly(entity_id: str, risk: float, confidence: float) -> list[WorkflowStep]:
    """Blueprint's canonical workflow for a high-confidence anomaly."""
    steps = [
        WorkflowStep("investigate", {"entity_id": entity_id,
                                     "question": "Why is this entity unusual?"}),
        WorkflowStep("gather_evidence", {"entity_id": entity_id}),
        WorkflowStep("generate_report", {"entity_id": entity_id}),
        WorkflowStep("notify", {"severity": "critical" if risk > 0.8 else "warning",
                                "title": f"High-confidence anomaly on {entity_id}"}),
    ]
    if confidence >= 0.6:
        steps.append(WorkflowStep("webhook", {"event": "anomaly.confirmed"}))
        steps.append(WorkflowStep("create_ticket", {"priority": "high"}))
        steps.append(WorkflowStep("request_approval", {"action": "external_report",
                                                       "reason": "sharing intelligence externally"}))
    return steps


def plan_from_automation(automation_steps: list[dict], entity_id: str,
                         context: dict) -> list[WorkflowStep]:
    return [WorkflowStep(s["action"], {**s.get("params", {}), "entity_id": entity_id, **context})
            for s in automation_steps]
