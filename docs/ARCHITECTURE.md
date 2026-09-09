# NEXUS Architecture

## 1. Design philosophy

NEXUS is built around one loop and one epistemic contract.

**The loop** (every stage independently runnable, observable, and testable):

```
OBSERVE → LEARN → DETECT → PREDICT → INVESTIGATE → EXPLAIN → RECOMMEND → ACT → MEASURE → IMPROVE
```

**The contract**: claims are typed at the data-model level (`ClaimType`):
`observed_fact`, `ml_inference`, `llm_hypothesis`, `unknown`. Provenance
(source system + record references + timestamp) rides along with every claim,
from the event store to the LLM report to the dashboard badge.

## 2. Layer map

```
┌──────────────────────────────────────────────────────────────────┐
│ apps/web            Next.js dashboard (12 sections)              │
├──────────────────────────────────────────────────────────────────┤
│ api/                FastAPI: 10 routers, typed errors, CORS      │
├──────────────────────────────────────────────────────────────────┤
│ agents/             Investigator: planner → tools → grounded LLM │
│ alerts/             Rules engine + workflow automation + approval│
├──────────────────────────────────────────────────────────────────┤
│ pipelines/          Intelligence loop orchestration              │
├──────────────────────────────────────────────────────────────────┤
│ models/             Anomaly ensemble · Risk engine · Registry    │
│ features/           Point-in-time behavioral · graph features    │
│ evaluation/         Classification/ranking/calibration · abl.    │
├──────────────────────────────────────────────────────────────────┤
│ data/               Providers (demo/rpc) · ingestion · ER        │
│ db/                 SQLAlchemy schema · sessions · migrations    │
├──────────────────────────────────────────────────────────────────┤
│ core/               Provenance · domain models · config · errors │
└──────────────────────────────────────────────────────────────────┘
```

## 3. Data model

Entities (`wallet`, `contract`, `token`, `protocol`, `cluster`) and `events`
(transfer/call/creation/protocol interaction) with `value_wei`, gas, and
**timestamp** on every row. Relationships are derived (aggregated edges with
count/value/first/last-seen) — every important edge preserves *when* and *how
often*. Indices on `(from_entity, timestamp)` and `(to_entity, timestamp)` keep
point-in-time feature queries fast.

**Entity resolution** is deliberately conservative: same-funder-within-window
clustering only, persisted as separate `cluster` entities (never merged into
wallet identity) with the method recorded for auditability.

## 4. Point-in-time feature discipline

`compute_entity_features(events, as_of)` uses **only** events with
`timestamp <= as_of`. This single function powers:

- training data generation (loop it over historical cutoffs → no leakage),
- live scoring (`as_of = now`),
- the entity page's behavioral profile.

Tested explicitly (`test_features_point_in_time`): future values can never
appear in earlier windows.

Feature families: activity (counts 1h/24h/7d/30d), value (volume/mean/median/
volatility + recent-vs-historical shift), diversity (counterparty/contract
novelty), temporal (inter-tx interval stats, hour entropy, burstiness,
interval-shift z-score), plus graph features (degree, PageRank, betweenness,
clustering, community size, SVD embedding dims).

## 5. Anomaly detection

Order of adoption = order of evidence:

1. `RobustZScore` — median/IQR baseline, interpretable.
2. `IsolationForestDetector` — strong general-purpose unsupervised.
3. `LOFDetector` — local-density anomalies (novelty mode for scoring).
4. `AutoencoderDetector` — PyTorch if available; silently skipped otherwise.
5. `AnomalyEnsemble` — mean of per-model rank-normalized scores → [0,1].

Every score persisted to `scores` with per-model breakdown in `details`,
provenance source, and registry version. GNNs are intentionally **not**
included until they beat this ensemble in the ablation harness.

## 6. Risk engine

A **meta-model**: signals (ensemble anomaly score, behavioral-shift rank,
novelty rank, PageRank rank) feed a logistic regression whose weights are
learned from `outcomes` labels — never hand-set. Calibration via
`CalibratedClassifierCV` (sigmoid at this data scale; isotonic with more data).
Confidence combines calibration status with inter-signal agreement so

```
HIGH RISK + HIGH CONFIDENCE   → act (automation triggers)
HIGH RISK + LOW CONFIDENCE    → investigate more (never auto-act)
```

Without labels the engine runs unsupervised (anomaly score as risk) and marks
`calibrated=false` — surfaced in the UI.

## 7. Investigator agent

```
question → Planner (deterministic tool plan, keyword-routed)
        → ToolRegistry (6 allowlisted, DB-backed tools, bounded outputs)
        → Evidence list (typed provenance, global [E#] ids)
        → LLM (strict system prompt: cite or say UNKNOWN)
        → Groundedness check (citation rate, invalid refs, hallucination risk)
        → Investigation row (persisted for audit + LLM-quality eval)
```

The planner is *not* LLM-driven on purpose: evidence collection must be
deterministic and auditable; the LLM's job is synthesis within an evidence
budget (max 20 rows per tool). `EchoClient` answers with structured evidence
only — used in CI and key-less deployments; OpenAI/Anthropic/Ollama clients
share the identical contract.

## 8. Automation with human gates

The workflow engine executes ordered steps (`investigate → gather_evidence →
generate_report → notify → webhook → create_ticket → request_approval`).
Steps marked as approval gates **pause the run** (`awaiting_approval`) until
`POST /workflow-runs/{id}/approve` — the run resumes from where it stopped,
and rejected runs are retained for audit. Alert channels degrade gracefully:
unconfigured email/Slack log-and-continue, dashboard alerts always persist.

## 9. Evaluation & MLOps

- Metrics: precision/recall/F1 (prevalence-capped threshold search), PR-AUC,
  ROC-AUC, FPR, Precision@K/Recall@K/NDCG/MAP, Brier, calibration curves.
- Ablations run every pipeline pass: behavioral → +graph → +temporal → all.
- Registry: versioned artifacts (joblib) + DB rows + promote/demote stages.
- Drift: feature PSI (30-day reference window) + prediction PSI between runs,
  threshold 0.2, exposed at `/api/v1/metrics/drift` and the Temporal page.
- Feedback: `outcomes` table is the label source for supervised risk training
  and retraining triggers (drift → train → evaluate → approve → deploy is the
  documented, partially-automated path).

## 10. Demo data honesty

The demo provider is seeded and deterministic (seed 20260909). Injected
patterns (drainer bursts, wash loops, volume spike) are tagged in event
attributes; label derivation is explicit and marked
(`label_provenance: demo_pattern_tags`) in every evaluation record. One-time
drain victims are labeled **benign** — only actors are anomalous. The system
never presents demo data as chain data (`demo: true` on every event).

## 11. Extension: new domains

Implement `DataProvider` (iter_entities/iter_events) for the new domain —
that is the entire integration surface. Feature families, anomaly ensemble,
risk engine, investigator tools, alerts, and dashboard are domain-agnostic
(entity + event + relationship + time). Finance and cybersecurity adapters
follow the same contract.
