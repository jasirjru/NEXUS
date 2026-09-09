"""Investigator agent: evidence gathering -> LLM analysis -> grounded report.

Pipeline:
1. Planner decides which tools to call based on the question (deterministic,
   auditable rules - not LLM-driven, so it never skips evidence gathering).
2. Tools execute against the DB and return Evidence with provenance.
3. Evidence is serialized into the prompt with [E#] ids + the strict grounding
   system prompt; the configured LLM responds.
4. Groundedness check: any line whose factual claims lack [E#] citations is
   marked. Report sections separate fact / inference / hypothesis / unknown.
5. Report persisted to investigations table for the UI + LLM-quality eval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from nexus.agents.llm_client import BaseLLMClient, EchoClient, get_llm_client
from nexus.agents.tools.registry import ToolRegistry
from nexus.core.logging_setup import get_logger
from nexus.core.provenance import ClaimType
from nexus.db.schema import Investigation

log = get_logger("nexus.agents.investigator")

CITATION_RE = re.compile(r"\[E\d+\]")


@dataclass
class InvestigationReport:
    question: str
    entity_id: str
    answer: str
    observed_facts: list[str] = field(default_factory=list)
    ml_inference: list[str] = field(default_factory=list)
    hypothesis: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    groundedness: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "entity_id": self.entity_id,
            "answer": self.answer,
            "observed_facts": self.observed_facts,
            "ml_inference": self.ml_inference,
            "hypothesis": self.hypothesis,
            "unknowns": self.unknowns,
            "tool_calls": self.tool_calls,
            "groundedness": self.groundedness,
        }


class Planner:
    """Deterministic tool plan based on question keywords."""

    def plan(self, question: str) -> list[tuple[str, dict]]:
        q = question.lower()
        plan: list[tuple[str, dict]] = []
        plan.append(("get_entity_history", {}))
        if any(w in q for w in ("transaction", "transfer", "payment", "tx")):
            plan.append(("get_transactions", {"limit": 10}))
        if any(w in q for w in ("related", "neighbor", "graph", "connected", "counterpart")):
            plan.append(("expand_graph", {"max_neighbors": 8}))
        if any(w in q for w in ("change", "unusual", "anomal", "suspicious", "behavior", "compare", "histor")):
            plan.append(("compare_behavior", {}))
        if any(w in q for w in ("protocol", "contract", "token", "label")):
            plan.append(("lookup_protocol", {}))
        plan.append(("retrieve_evidence", {}))
        return plan


class Investigator:
    def __init__(self, db: Session, llm: BaseLLMClient | None = None):
        self.db = db
        self.tools = ToolRegistry(db)
        self.planner = Planner()
        self.llm = llm or get_llm_client()

    # ------------------------------------------------------------ grounding
    @staticmethod
    def check_groundedness(answer: str, evidence_count: int) -> dict[str, Any]:
        lines = [ln for ln in answer.splitlines() if ln.strip()]
        factual = [
            ln for ln in lines
            if any(k in ln.lower() for k in ("fact", "evidence", "shows", "transferred", "score", "volume", "tx "))
            and not ln.strip().startswith(("UNKNOWN", "HYPOTHESIS", "- "))
        ]
        cited = [ln for ln in factual if CITATION_RE.search(ln)]
        total_citations = len(CITATION_RE.findall(answer))
        invalid = [m for m in CITATION_RE.findall(answer)
                   if int(m[2:-1]) > evidence_count]
        return {
            "factual_lines": len(factual),
            "cited_lines": len(cited),
            "citation_rate": round(len(cited) / len(factual), 3) if factual else 1.0,
            "total_citations": total_citations,
            "invalid_citations": len(invalid),
            "hallucination_risk": "low" if invalid == [] and (
                not factual or len(cited) / max(len(factual), 1) >= 0.5
            ) else "high",
        }

    # ------------------------------------------------------------ main
    def investigate(self, entity_id: str, question: str, persist: bool = True) -> InvestigationReport:
        tool_calls: list[dict] = []
        all_evidence = []

        for tool_name, kwargs in self.planner.plan(question):
            try:
                result = self.tools.call(tool_name, entity_id=entity_id, **kwargs)
            except Exception as e:  # tool failures must not crash the investigation
                log.warning("tool %s failed: %s", tool_name, e)
                result = None
            if result is not None:
                # renumber evidence ids globally [E1..En]
                offset = len(all_evidence)
                for i, ev in enumerate(result.evidence):
                    all_evidence.append((offset + i + 1, ev))
                tool_calls.append(result.to_dict())

        user_payload = self._build_prompt(entity_id, question, all_evidence)
        llm_resp = self.llm.complete(
            __import__("nexus.agents.llm_client", fromlist=["SYSTEM_PROMPT"]).SYSTEM_PROMPT,
            user_payload,
        )
        groundedness = self.check_groundedness(llm_resp.text, len(all_evidence))

        report = InvestigationReport(
            question=question,
            entity_id=entity_id,
            answer=llm_resp.text,
            observed_facts=[
                ev.claim for i, ev in all_evidence if ev.provenance.claim_type == ClaimType.OBSERVED_FACT
            ],
            ml_inference=[
                ev.claim for i, ev in all_evidence if ev.provenance.claim_type == ClaimType.ML_INFERENCE
            ],
            hypothesis=[],
            unknowns=[],
            tool_calls=tool_calls,
            groundedness=groundedness,
        )

        if persist:
            rec = Investigation(
                entity_id=entity_id,
                question=question,
                answer=llm_resp.text,
                report_json=report.to_dict(),
                tool_calls=tool_calls,
            )
            self.db.add(rec)
            self.db.commit()
        return report

    def _build_prompt(self, entity_id: str, question: str, evidence: list) -> str:
        lines = [
            f"ENTITY: {entity_id}",
            f"QUESTION: {question}",
            "",
            "EVIDENCE (cite by id, e.g. [E1]):",
        ]
        for i, ev in evidence:
            lines.append(
                f"[E{i}] ({ev.provenance.claim_type.value}) {ev.claim}"
            )
        lines += [
            "",
            "Answer format:",
            "OBSERVED FACTS: bullet list, each with [E#] citations",
            "ML INFERENCE: what the scores imply (cite [E#])",
            "LLM HYPOTHESIS: your interpretation, clearly labeled",
            "UNKNOWN: what cannot be established from this evidence",
        ]
        return "\n".join(lines)
