# NEXUS — Autonomous Intelligence & Decision Engine

**An Ethereum intelligence platform built around a full intelligence loop — not a chatbot, dashboard, or single model.**

```
OBSERVE → LEARN → DETECT → PREDICT → INVESTIGATE → EXPLAIN → RECOMMEND → ACT → MEASURE → IMPROVE
```

NEXUS ingests Ethereum activity, builds entity/event/relationship models with full
temporal fidelity, detects anomalous behavior with validated ML, predicts **calibrated**
risk, investigates findings with an evidence-grounded LLM agent, explains its reasoning
with strict provenance, triggers human-approved workflows, and measures outcomes to
improve. The core is **domain-independent**: Ethereum is the first adapter; finance and
cybersecurity follow the same contracts (entity + event + relationship + time).

---

## Quick Start (local, no external services required)

```bash
# 1. Backend (Python 3.11+)
pip install -e ".[dev]"
python -m nexus.cli init-db
python -m nexus.cli pipeline        # full intelligence loop on the deterministic demo dataset
python -m nexus.cli runserver       # API on http://127.0.0.1:8000  (docs at /docs)

# 2. Dashboard (Node 18+)
cd apps/web
npm install
npm run dev                         # UI on http://localhost:3000 (proxies /api to :8000)
```

Or with Docker:

```bash
docker compose up --build           # postgres + API (auto-seeds demo pipeline) + web
```

### CLI

```bash
python -m nexus.cli pipeline                      # ingest → features → anomaly → risk → evaluate → alerts
python -m nexus.cli pipeline --skip-ingest        # re-run ML stages only
python -m nexus.cli investigate 0xabc… "Why is this wallet suspicious?"
python -m nexus.cli alert-rule add "critical risk" --metric risk --op ">" --threshold 0.9 --channels dashboard,email
python -m nexus.cli automation seed               # canonical high-confidence-anomaly workflow
python -m nexus.cli automation run --id 1 --entity 0xabc…
python -m nexus.cli automation approve --run-id 3   # human approval gate
```

## What makes it different

| Principle | Implementation |
|---|---|
| **Evidence, not vibes** | The LLM never invents blockchain facts. Tools (`get_transactions`, `expand_graph`, `compare_behavior`, …) return provenance-tagged evidence; reports must cite it (`[E3]`), and a groundedness checker flags uncited claims. |
| **Epistemic honesty** | Every claim is typed: `observed_fact` / `ml_inference` / `llm_hypothesis` / `unknown` — in the DB, the API, and the UI. |
| **Calibrated risk** | Risk = meta-model over ML signals with learned weights + sigmoid/isotonic calibration. UI distinguishes HIGH RISK·HIGH CONFIDENCE from HIGH RISK·LOW CONFIDENCE. |
| **Baselines first** | Robust z-score → Isolation Forest → LOF → (optional) autoencoder → ensemble. GNNs are deliberately absent until they measurably beat these. |
| **Ablations, measured** | Every pipeline run records the ablation ladder: behavioral → +graph → +temporal → all features. See `/models` in the dashboard. |
| **No invented numbers** | The dashboard only renders metrics from actual evaluation runs stored in the DB. |

## Measured demo results

From the deterministic demo dataset (injected patterns: wallet drainers, wash-trading loops,
a volume-spike wallet — all labeled honestly; drainer *victims* are labeled benign):

```
ablation (ROC-AUC):   baseline_behavioral 0.914 → +graph 0.950 → +temporal 0.982 → ensemble 0.985
ensemble:             F1 0.714 · PR-AUC 0.606 · FPR 0.028
```

Reproduce: `python -m nexus.cli pipeline` — the numbers print from the run; nothing is hard-coded.

## Architecture

```
Data Provider (demo | JSON-RPC)      ← swap domains here
  → Ingestion (validate → normalize → idempotent upsert)
  → Entity Resolution (same-funder clustering, conservative)
  → Event Store (PostgreSQL/SQLite, temporal indices)
  → Feature Engine (point-in-time: activity, value, diversity, temporal, behavioral change)
  → Graph Intelligence (NetworkX: PageRank, betweenness, communities, SVD embeddings)
  → Anomaly Ensemble (zscore + iForest + LOF + AE, rank-normalized)
  → Risk Engine (learned + calibrated meta-model; risk + confidence)
  → Investigator Agent (planner → allowlisted tools → grounded LLM report)
  → Alerts (rules → dashboard/email/webhook/Slack)
  → Automations (workflow engine with human approval gates)
  → API (FastAPI) → Dashboard (Next.js)
  → Evaluation (metrics, calibration, ablations) → Model Registry → drift monitoring
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the deep dive.

## Configuration

Copy `.env.example` → `.env`. Highlights:

| Variable | Purpose |
|---|---|
| `NEXUS_DATABASE_URL` | SQLite (dev) or PostgreSQL (`postgresql+psycopg2://…`) |
| `NEXUS_DATA_PROVIDER` | `demo` (deterministic) or `rpc` (real Ethereum via `NEXUS_RPC_URL`) |
| `NEXUS_LLM_PROVIDER` | `echo` (offline, evidence-only), `openai`, `anthropic`, `ollama` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | read from env only, never hard-coded |
| `NEXUS_SMTP_*`, `NEXUS_SLACK_WEBHOOK_URL` | alert delivery (gracefully no-op if unset) |

## Testing

```bash
python -m pytest tests/ -v           # 73 tests: unit, integration, classifiers, forecasting, GNN, MLOps, LLM eval
cd apps/web && npx tsc --noEmit      # type-safe dashboard with zero TypeScript errors
```

## Repository layout

```
nexus/                  core platform (Python)
  core/                 provenance, domain models, errors, config, logging
  data/                 providers (demo/rpc/finance/cybersecurity), ingestion, entity resolution, schemas, processing
  features/             behavioral + graph feature engines
  models/               anomaly detectors, classifiers (RF, GBDT, XGB, LGBM), forecasting (CUSUM, Bayesian, EWMA), graph (GNN, GraphSAGE, GAT), risk engine, registry
  agents/               LLM clients, investigator (ReAct loop), planner, tool registry
  alerts/               channels (dashboard/email/webhook/slack) + automation engine
  pipelines/            end-to-end intelligence loop
  evaluation/           metrics, calibration, ablations, LLM evaluation suite
  mlops/                experiment tracking (MLflow / internal), drift-triggered retraining
  db/                   schema, sessions, migrations, DuckDB/Parquet analytics
  api/                  FastAPI app + routers
apps/web/               Next.js dashboard (12 sections, interactive force-directed graph)
infrastructure/         Dockerfiles, alembic
notebooks/              Exploratory analysis and documentation
tests/                  unit + integration test suite (11 test modules)
docs/                   architecture deep-dive
```

## Roadmap

- **100% Complete**:
  - Full intelligence loop: OBSERVE → LEARN → DETECT → PREDICT → INVESTIGATE → EXPLAIN → RECOMMEND → ACT → MEASURE → IMPROVE
  - Multi-detector anomaly ensemble + calibrated risk scoring
  - Classical ML baselines (Random Forest, Gradient Boosting, XGBoost, LightGBM)
  - Change-point detection (CUSUM, Bayesian, Ensemble) & EWMA volume forecasting
  - Graph Neural Networks (GraphSAGE, GAT) with graceful fallback
  - Domain-independent adapters: Ethereum (demo + RPC), Financial Markets, Cybersecurity
  - ReAct multi-step Investigator agent with groundedness validation and LLM evaluation suite
  - MLOps experiment tracking (MLflow / internal) & drift-triggered automated retraining
  - DuckDB analytical layer with Parquet export
  - Interactive force-directed graph visualization in dashboard with pan, zoom, drag, and risk styling
  - 73 comprehensive automated tests with full CI coverage

## Honest limitations

- Demo labels derive from injected pattern tags — real deployments supply analyst outcomes (the `outcomes` table + feedback loop exist for this).
- The `rpc` provider ingests native transfers and event logs; token transfer logs use `eth_getLogs` filters.
- LLM investigator defaults to the deterministic `echo` client so the system runs without external keys; configure OpenAI/Anthropic/Ollama for live LLM reasoning.
