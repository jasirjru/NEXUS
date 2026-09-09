"""Tests for LLM evaluation metrics and evaluation suite."""

from __future__ import annotations

import pytest

from nexus.agents.llm_client import EchoClient
from nexus.agents.investigator import Investigator
from nexus.data.ingestion import run_ingestion
from nexus.data.providers.demo import DemoEthereumProvider
from nexus.evaluation.llm_eval import (
    LLMEvalResult,
    LLMEvalSuite,
    evaluate_groundedness,
    evaluate_tool_accuracy,
    run_llm_evaluation,
)


class TestGroundednessEvaluation:
    def test_perfect_groundedness(self):
        answer = (
            "Evidence shows entity transferred value [E1].\n"
            "Transaction risk score is high [E2].\n"
        )
        res = evaluate_groundedness(answer, evidence_count=2)
        assert res["groundedness"] == 1.0
        assert res["evidence_coverage"] == 1.0
        assert res["hallucination_rate"] == 0.0

    def test_hallucinated_citation(self):
        answer = (
            "Evidence shows high risk [E1].\n"
            "Transaction volume is abnormal [E99].\n"  # 99 > evidence_count=2
        )
        res = evaluate_groundedness(answer, evidence_count=2)
        assert res["hallucination_rate"] > 0.0
        assert res["invalid_citations"] == 1

    def test_uncited_claims(self):
        answer = (
            "Evidence shows high risk.\n"
            "Transaction volume is abnormal.\n"
        )
        res = evaluate_groundedness(answer, evidence_count=5)
        assert res["groundedness"] == 0.0
        assert res["evidence_coverage"] == 0.0


class TestToolAccuracyEvaluation:
    def test_perfect_match(self):
        acc = evaluate_tool_accuracy(
            actual_tools=["get_entity_history", "compare_behavior", "retrieve_evidence"],
            expected_tools=["get_entity_history", "compare_behavior"],
        )
        assert acc == 1.0

    def test_partial_match(self):
        acc = evaluate_tool_accuracy(
            actual_tools=["get_entity_history"],
            expected_tools=["get_entity_history", "compare_behavior"],
        )
        assert acc == 0.5

    def test_no_expected_tools(self):
        assert evaluate_tool_accuracy(["foo"], []) == 1.0


class TestLLMEvalSuite:
    def test_suite_aggregations(self):
        suite = LLMEvalSuite(
            results=[
                LLMEvalResult("q1", groundedness=1.0, evidence_coverage=0.8, hallucination_rate=0.0, tool_accuracy=1.0),
                LLMEvalResult("q2", groundedness=0.6, evidence_coverage=0.4, hallucination_rate=0.2, tool_accuracy=0.5),
            ]
        )
        assert suite.mean_groundedness == pytest.approx(0.8)
        assert suite.mean_evidence_coverage == pytest.approx(0.6)
        assert suite.mean_hallucination_rate == pytest.approx(0.1)
        assert suite.mean_tool_accuracy == pytest.approx(0.75)

        d = suite.to_dict()
        assert d["n_evaluations"] == 2
        assert len(d["results"]) == 2

    def test_empty_suite(self):
        suite = LLMEvalSuite()
        assert suite.mean_groundedness == 0.0
        assert suite.mean_tool_accuracy == 0.0


class TestEndToEndEvaluation:
    def test_run_llm_evaluation_with_investigator(self, db):
        run_ingestion(db, provider=DemoEthereumProvider(), event_batch=500)
        client = EchoClient()
        investigator = Investigator(db, llm=client)

        custom_test_set = [
            {
                "question": "Why is this wallet suspicious?",
                "expected_tools": ["get_entity_history", "compare_behavior"],
                "category": "investigation",
            }
        ]

        # Use an existing entity from DB
        from nexus.db.schema import Entity
        from sqlalchemy import select
        entity = db.scalar(select(Entity).limit(1))
        assert entity is not None

        suite = run_llm_evaluation(investigator, entity_id=entity.id, test_set=custom_test_set)
        assert len(suite.results) == 1
        res = suite.results[0]
        assert res.question == "Why is this wallet suspicious?"
        assert res.groundedness >= 0.0
        assert res.tool_accuracy >= 0.0
