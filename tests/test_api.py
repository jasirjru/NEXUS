"""API integration tests: exercise the FastAPI app end-to-end on a real DB."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(_db):
    from nexus.data.ingestion import run_ingestion
    from nexus.data.providers.demo import DemoEthereumProvider
    from nexus.db.session import SessionLocal
    from nexus.pipelines.intelligence import run_full_pipeline
    from nexus.api.app import app

    s = SessionLocal()
    run_ingestion(s, provider=DemoEthereumProvider(), event_batch=3000)
    run_full_pipeline(s, skip_ingest=True)
    s.close()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_overview(client):
    r = client.get("/api/v1/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["events"] > 0
    assert "risk_distribution" in data


def test_entities_list_and_profile(client):
    r = client.get("/api/v1/entities", params={"limit": 5})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items
    eid = items[0]["id"]
    r2 = client.get(f"/api/v1/entities/{eid}")
    assert r2.status_code == 200
    assert "scores" in r2.json()


def test_entity_not_found(client):
    r = client.get("/api/v1/entities/0xdoesnotexist")
    assert r.status_code == 404


def test_timeline_and_neighbors(client):
    r = client.get("/api/v1/entities", params={"limit": 1})
    eid = r.json()["items"][0]["id"]
    assert client.get(f"/api/v1/entities/{eid}/timeline").status_code == 200
    assert client.get(f"/api/v1/entities/{eid}/neighbors").status_code == 200
    ego = client.get(f"/api/v1/entities/{eid}/ego-graph")
    assert ego.status_code == 200
    assert ego.json()["nodes"]


def test_investigation_endpoint(client):
    r = client.get("/api/v1/entities", params={"q": "drainer_0"})
    items = r.json()["items"]
    assert items, "drainer_0 should exist in demo data"
    eid = items[0]["id"]
    resp = client.post("/api/v1/investigate", json={
        "entity_id": eid, "question": "Why is this wallet suspicious?",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"]
    assert data["tool_calls"]


def test_alert_rules_crud_and_evaluation(client):
    r = client.post("/api/v1/alerts/rules", json={
        "name": "very high risk", "metric": "risk", "operator": ">",
        "threshold": 0.99, "channels": ["dashboard"],
    })
    assert r.status_code == 200
    rule = r.json()
    ev = client.post("/api/v1/alerts/evaluate")
    assert ev.status_code == 200
    assert client.get("/api/v1/alerts").status_code == 200
    assert client.delete(f"/api/v1/alerts/rules/{rule['id']}").status_code == 200


def test_automation_run_and_approval(client):
    r = client.post("/api/v1/automations", json={
        "name": "test flow",
        "steps": [
            {"action": "investigate", "params": {}},
            {"action": "request_approval", "params": {}},
            {"action": "notify", "params": {}},
        ],
        "requires_approval": True,
    })
    auto = r.json()
    run = client.post(f"/api/v1/automations/{auto['id']}/run", json={
        "entity_id": "0x0000000000000000000000000000000000000001",
    }).json()
    assert run["status"] == "awaiting_approval"
    approved = client.post(f"/api/v1/workflow-runs/{run['id']}/approve",
                           params={"approve": True}).json()
    assert approved["status"] == "completed"


def test_evaluations_and_models(client):
    r = client.get("/api/v1/evaluations")
    assert r.status_code == 200
    assert r.json()["items"], "evaluation runs should exist after pipeline"
    m = client.get("/api/v1/models")
    assert m.status_code == 200
    assert any(x["name"] == "anomaly_ensemble" for x in m.json()["items"])


def test_system_and_drift(client):
    assert client.get("/api/v1/system").status_code == 200
    d = client.get("/api/v1/metrics/drift")
    assert d.status_code == 200
