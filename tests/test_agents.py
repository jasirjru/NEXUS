"""Agent tests: tool allowlist, evidence provenance, groundedness checking."""

from __future__ import annotations

import pytest

from nexus.agents.investigator import Investigator
from nexus.agents.llm_client import EchoClient
from nexus.agents.tools.registry import ToolRegistry
from nexus.core.errors import ToolDeniedError
from nexus.data.ingestion import run_ingestion
from nexus.data.providers.demo import DemoEthereumProvider


@pytest.fixture(scope="module")
def ingested_db(_db):
    from nexus.db.session import SessionLocal

    s = SessionLocal()
    run_ingestion(s, provider=DemoEthereumProvider(), event_batch=3000)
    yield s
    s.close()


def test_tool_allowlist_denies_unknown(ingested_db):
    reg = ToolRegistry(ingested_db)
    with pytest.raises(ToolDeniedError):
        reg.call("delete_everything", entity_id="x")


def test_get_transactions_returns_evidence(ingested_db):
    from nexus.db.schema import Entity

    ent = ingested_db.query(Entity).filter(Entity.type == "wallet").first()
    reg = ToolRegistry(ingested_db)
    res = reg.call("get_transactions", entity_id=ent.id, limit=5)
    assert res.summary
    assert len(res.evidence) > 0
    for ev in res.evidence:
        assert ev.provenance.claim_type.value in (
            "observed_fact", "ml_inference", "llm_hypothesis", "unknown"
        )
        assert ev.provenance.source  # provenance always names its source


def test_echo_client_never_fabricates():
    resp = EchoClient().complete(
        "system", "QUESTION: why?\n\n[E1] (observed_fact) 3 txs seen"
    )
    assert "3 txs seen" in resp.text  # echoes evidence verbatim
    assert "[E1]" in resp.text or "3 txs" in resp.text


def test_investigator_produces_grounded_report(ingested_db):
    from nexus.db.schema import Entity

    ent = ingested_db.query(Entity).filter(Entity.label == "drainer_0").first()
    inv = Investigator(ingested_db, llm=EchoClient())
    report = inv.investigate(ent.id, "Why is this wallet suspicious?", persist=False)
    assert report.answer
    assert report.observed_facts or report.ml_inference
    assert report.groundedness["hallucination_risk"] in ("low", "high")
    assert len(report.tool_calls) >= 2
