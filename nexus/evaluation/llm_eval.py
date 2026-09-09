"""LLM quality evaluation framework.

Metrics (per blueprint section 13):
- Groundedness: fraction of factual claims that cite evidence [E#]
- Evidence coverage: fraction of available evidence cited in the answer
- Hallucination rate: fraction of claims with invalid or absent citations
- Tool-call accuracy: whether the planner selected the correct tools for
  each question category

These metrics are computed on a fixed test set of questions with known
expected tool calls and evidence requirements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import re

from nexus.core.logging_setup import get_logger

log = get_logger("nexus.evaluation.llm_eval")

CITATION_RE = re.compile(r"\[E(\d+)\]")


@dataclass
class LLMEvalResult:
    """Evaluation result for a single LLM investigation."""
    question: str
    groundedness: float  # cited_factual_lines / total_factual_lines
    evidence_coverage: float  # cited_evidence_count / total_evidence_count
    hallucination_rate: float  # invalid_citations / total_citations
    tool_accuracy: float  # correct_tools / expected_tools
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "groundedness": round(self.groundedness, 4),
            "evidence_coverage": round(self.evidence_coverage, 4),
            "hallucination_rate": round(self.hallucination_rate, 4),
            "tool_accuracy": round(self.tool_accuracy, 4),
            "details": self.details,
        }


@dataclass
class LLMEvalSuite:
    """Aggregate evaluation over a test set."""
    results: list[LLMEvalResult] = field(default_factory=list)

    @property
    def mean_groundedness(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.groundedness for r in self.results) / len(self.results)

    @property
    def mean_evidence_coverage(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.evidence_coverage for r in self.results) / len(self.results)

    @property
    def mean_hallucination_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.hallucination_rate for r in self.results) / len(self.results)

    @property
    def mean_tool_accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.tool_accuracy for r in self.results) / len(self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_evaluations": len(self.results),
            "mean_groundedness": round(self.mean_groundedness, 4),
            "mean_evidence_coverage": round(self.mean_evidence_coverage, 4),
            "mean_hallucination_rate": round(self.mean_hallucination_rate, 4),
            "mean_tool_accuracy": round(self.mean_tool_accuracy, 4),
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------- Evaluation functions

def evaluate_groundedness(
    answer: str,
    evidence_count: int,
) -> dict[str, float]:
    """Measure groundedness of an LLM answer.

    Returns:
        groundedness: fraction of factual lines with citations
        evidence_coverage: fraction of evidence items cited
        hallucination_rate: fraction of invalid citations
    """
    lines = [ln for ln in answer.splitlines() if ln.strip()]

    # Identify factual lines (contain data-like claims)
    factual_keywords = (
        "fact", "evidence", "shows", "transferred", "score", "volume",
        "tx ", "transaction", "value", "entity", "wallet", "contract",
        "risk", "anomaly", "pagerank", "degree",
    )
    factual_lines = [
        ln for ln in lines
        if any(k in ln.lower() for k in factual_keywords)
        and not ln.strip().startswith(("UNKNOWN", "HYPOTHESIS", "- "))
    ]

    # Count citations
    all_citations = CITATION_RE.findall(answer)
    cited_evidence_ids = set(int(m) for m in all_citations)
    cited_factual = [ln for ln in factual_lines if CITATION_RE.search(ln)]

    # Invalid citations (reference beyond available evidence)
    invalid = [int(m) for m in all_citations if int(m) > evidence_count]

    groundedness = len(cited_factual) / max(len(factual_lines), 1)
    evidence_coverage = len(cited_evidence_ids) / max(evidence_count, 1)
    hallucination_rate = len(invalid) / max(len(all_citations), 1)

    return {
        "groundedness": groundedness,
        "evidence_coverage": min(evidence_coverage, 1.0),
        "hallucination_rate": hallucination_rate,
        "factual_lines": len(factual_lines),
        "cited_lines": len(cited_factual),
        "total_citations": len(all_citations),
        "invalid_citations": len(invalid),
    }


def evaluate_tool_accuracy(
    actual_tools: list[str],
    expected_tools: list[str],
) -> float:
    """Measure whether the correct tools were called.

    Returns fraction of expected tools that were actually called.
    """
    if not expected_tools:
        return 1.0
    hits = sum(1 for t in expected_tools if t in actual_tools)
    return hits / len(expected_tools)


# ---------------------------------------------------------------- Test set

# Fixed test questions with expected tool calls for evaluation
EVAL_TEST_SET: list[dict[str, Any]] = [
    {
        "question": "Why is this wallet suspicious?",
        "expected_tools": ["get_entity_history", "compare_behavior", "retrieve_evidence"],
        "category": "investigation",
    },
    {
        "question": "What changed in the last 24 hours?",
        "expected_tools": ["get_entity_history", "get_transactions", "compare_behavior"],
        "category": "temporal",
    },
    {
        "question": "Show related entities and graph connections.",
        "expected_tools": ["get_entity_history", "expand_graph", "retrieve_evidence"],
        "category": "graph",
    },
    {
        "question": "Compare this wallet with its historical behavior.",
        "expected_tools": ["get_entity_history", "compare_behavior", "retrieve_evidence"],
        "category": "comparison",
    },
    {
        "question": "What protocol does this contract interact with?",
        "expected_tools": ["get_entity_history", "lookup_protocol", "retrieve_evidence"],
        "category": "protocol",
    },
    {
        "question": "Show me the recent transactions for this entity.",
        "expected_tools": ["get_entity_history", "get_transactions", "retrieve_evidence"],
        "category": "transactions",
    },
]


def run_llm_evaluation(
    investigator,
    entity_id: str,
    test_set: list[dict] | None = None,
) -> LLMEvalSuite:
    """Run the full LLM evaluation suite against a test set of questions.

    Args:
        investigator: Investigator instance
        entity_id: entity to investigate
        test_set: optional custom test set; defaults to EVAL_TEST_SET

    Returns:
        LLMEvalSuite with per-question and aggregate metrics
    """
    test_set = test_set or EVAL_TEST_SET
    suite = LLMEvalSuite()

    for test_case in test_set:
        question = test_case["question"]
        expected_tools = test_case["expected_tools"]

        try:
            report = investigator.investigate(entity_id, question)

            # Extract actual tool calls
            actual_tools = [tc.get("tool", "") for tc in report.tool_calls]

            # Evaluate groundedness
            evidence_count = sum(
                len(tc.get("evidence", [])) for tc in report.tool_calls
            )
            ground_metrics = evaluate_groundedness(report.answer, evidence_count)

            # Evaluate tool accuracy
            tool_acc = evaluate_tool_accuracy(actual_tools, expected_tools)

            result = LLMEvalResult(
                question=question,
                groundedness=ground_metrics["groundedness"],
                evidence_coverage=ground_metrics["evidence_coverage"],
                hallucination_rate=ground_metrics["hallucination_rate"],
                tool_accuracy=tool_acc,
                details={
                    "category": test_case.get("category", ""),
                    "actual_tools": actual_tools,
                    "expected_tools": expected_tools,
                    **ground_metrics,
                },
            )
        except Exception as e:
            log.error("LLM eval failed for question '%s': %s", question, e)
            result = LLMEvalResult(
                question=question,
                groundedness=0.0,
                evidence_coverage=0.0,
                hallucination_rate=1.0,
                tool_accuracy=0.0,
                details={"error": str(e)},
            )

        suite.results.append(result)

    log.info(
        "LLM eval complete: groundedness=%.2f coverage=%.2f hallucination=%.2f tool_acc=%.2f",
        suite.mean_groundedness, suite.mean_evidence_coverage,
        suite.mean_hallucination_rate, suite.mean_tool_accuracy,
    )
    return suite
