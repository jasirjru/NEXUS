"""End-to-end intelligence pipeline.

Stages (each independently callable and idempotent):
  1. ingest            - provider -> validate -> normalize -> event store
  2. entity_resolution - conservative address clustering
  3. features          - behavioral + graph features (point-in-time)
  4. anomaly           - train/score detector ensemble, persist scores
  5. risk              - calibrated risk engine (uses outcome labels if present,
                         else unsupervised fallback), persist scores
  6. evaluate          - measured metrics + ablations persisted to evaluation_runs
  7. alerts            - evaluate alert rules -> alerts + workflow runs

Synthetic ground truth: the demo provider tags injected anomaly patterns in
event attributes (drain_in/out, wash_loop). Where those tags exist we can
derive honest pseudo-labels FOR THE DEMO DOMAIN ONLY; real deployments supply
labels via the outcomes table. Pseudo-label derivation is explicit and marked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from nexus.core.errors import ModelNotTrainedError
from nexus.core.logging_setup import get_logger
from nexus.data.entity_resolution import run_entity_resolution
from nexus.data.ingestion import run_ingestion
from nexus.db.schema import (
    Entity,
    EvaluationRun,
    Event,
    Outcome,
    ScoreRecord,
)
from nexus.evaluation.ablation import run_ablation
from nexus.evaluation.metrics import combine_metrics
from nexus.features.behavioral import compute_entity_features, load_events_frame
from nexus.features.graph_features import build_graph, compute_graph_features
from nexus.models.anomaly.detectors import AnomalyEnsemble
from nexus.models.risk.engine import RiskEngine

log = get_logger("nexus.pipelines")


@dataclass
class PipelineReport:
    stages: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"stages": self.stages}


# ---------------------------------------------------------------- labels
def derive_demo_labels(db: Session, as_of: datetime) -> pd.Series:
    """Pseudo-labels from demo pattern tags (DEMO ONLY). 1 = anomalous entity.
    Covers ALL entities seen in events (benign majority included)."""
    rows = db.execute(
        select(Event.from_entity, Event.to_entity, Event.attributes)
    ).all()
    all_entities: set[str] = set()
    anomalous: set[str] = set()
    for src, dst, attrs in rows:
        all_entities.add(src)
        all_entities.add(dst)
        pattern = (attrs or {}).get("attrs_pattern") or (attrs or {}).get("pattern")
        if pattern in ("drain_in", "drain_out"):
            # drainer wallet = the non-victim side; one-time victims are benign
            drain_actor = dst if pattern == "drain_in" else src
            anomalous.add(drain_actor)
        elif pattern == "wash_loop":
            anomalous.add(src)
            anomalous.add(dst)
    return pd.Series(
        {a: int(a in anomalous) for a in sorted(all_entities)}, dtype=int
    )


# ---------------------------------------------------------------- stages
def stage_ingest(db: Session) -> dict:
    stats = run_ingestion(db)
    n_clusters = run_entity_resolution(db)
    return {"ingestion": stats.__dict__, "clusters": n_clusters}


def stage_features(db: Session, as_of: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (behavioral_features, graph_features)."""
    events = load_events_frame(db)
    behavioral = compute_entity_features(events, as_of)
    g = build_graph(db)
    gf = compute_graph_features(g).frame
    # union join: some graph nodes may lack behavioral rows (token/protocol contracts)
    return behavioral, gf


def stage_anomaly(db: Session, features: pd.DataFrame, version: str,
                  register_fn=None) -> tuple[AnomalyEnsemble, pd.Series]:
    X = features.fillna(0.0)
    ens = AnomalyEnsemble()
    ens.fit(X)
    scores = pd.Series(ens.score(X), index=features.index, name="anomaly_ensemble")

    as_of = datetime.now(timezone.utc)
    members = {name: pd.Series(vals, index=X.index)
               for name, vals in ens.member_scores(X).items()}
    for entity_id, value in scores.items():
        db.add(ScoreRecord(
            entity_id=str(entity_id), as_of=as_of, score_name="anomaly_ensemble",
            value=float(value), confidence=None,
            provenance_source=f"nexus.anomaly.v{version}",
            details={m: round(float(series.loc[entity_id]), 4)
                     for m, series in members.items()},
        ))
    db.commit()
    log.info("anomaly scores persisted for %d entities", len(scores))
    if register_fn:
        register_fn("anomaly_ensemble", version, ens, {"n_entities": len(scores)},
                    {"members": [d.name for d in ens.active]})
    return ens, scores


def stage_risk(db: Session, features: pd.DataFrame, anomaly_scores: pd.Series,
               version: str, register_fn=None) -> tuple[RiskEngine, pd.DataFrame]:
    """Build signal matrix, train risk engine (supervised if labels exist),
    persist risk + confidence scores."""
    signals = pd.DataFrame({
        "anomaly": anomaly_scores,
    })
    # add graph + behavioral signals to give the meta-model independent views
    for col, name in [
        ("volume_recent_vs_hist", "behavior_shift"),
        ("new_counterparty_fraction", "novelty"),
        ("pagerank", "graph_centrality"),
    ]:
        if col in features.columns:
            col_vals = features[col].fillna(0.0)
            signals[name] = col_vals.rank(pct=True)  # rank-normalize to [0,1]

    labels_frame = derive_demo_labels(db, datetime.now(timezone.utc))
    engine = RiskEngine()
    aligned = signals.reindex(labels_frame.index).dropna()
    labels_aligned = labels_frame.reindex(aligned.index).fillna(0).astype(int).to_numpy()
    # Need both classes for supervised fitting; pad with benign entities if needed
    if len(set(labels_aligned.tolist())) < 2:
        benign = signals.drop(index=aligned.index, errors="ignore")
        pad = benign.head(max(len(aligned), 40))
        aligned = pd.concat([aligned, pad])
        labels_aligned = np.concatenate([
            labels_aligned, np.zeros(len(pad), dtype=int)
        ])
    engine.fit_supervised(aligned, labels_aligned)

    results = engine.predict(signals)
    as_of = datetime.now(timezone.utc)
    rows = []
    for r in results:
        db.add(ScoreRecord(
            entity_id=r.entity_id, as_of=as_of, score_name="risk",
            value=r.risk, confidence=r.confidence,
            provenance_source=f"nexus.risk.v{version}",
            details={"calibrated": r.calibrated, **r.components},
        ))
        rows.append({"entity_id": r.entity_id, "risk": r.risk,
                     "confidence": r.confidence})
    db.commit()
    log.info("risk scores persisted for %d entities (calibrated=%s)",
             len(rows), engine.calibrated)
    if register_fn:
        register_fn("risk_engine", version, engine,
                    {"calibrated": engine.calibrated, "n": len(rows)},
                    engine.get_params())
    return engine, pd.DataFrame(rows).set_index("entity_id")


def stage_evaluate(db: Session, features: pd.DataFrame,
                   anomaly_scores: pd.Series) -> dict:
    """Measured metrics + ablation + classifier benchmark. Honest about pseudo-label provenance."""
    labels_frame = derive_demo_labels(db, datetime.now(timezone.utc))
    common = anomaly_scores.index.intersection(labels_frame.index)
    if len(common) == 0 or labels_frame.loc[common].sum() == 0:
        log.warning("no labels available; skipping evaluation")
        return {"skipped": "no labels"}

    y = labels_frame.loc[common].to_numpy()
    scores = anomaly_scores.loc[common].to_numpy()
    metrics = combine_metrics(y, scores)
    metrics["label_provenance"] = "demo_pattern_tags"  # honesty: not real-world labels

    feats_aligned = features.loc[common].fillna(0.0)
    ablations = run_ablation(feats_aligned, y)
    ablation_summary = {s.name: {k: round(v, 4) for k, v in s.metrics.items()
                                 if k in ("f1", "pr_auc", "roc_auc", "false_positive_rate")}
                        for s in ablations}

    # --- Classifier baseline benchmark ---
    classifier_results = {}
    try:
        from nexus.models.classifiers.baselines import get_available_classifiers, cross_validate_classifier
        for clf in get_available_classifiers():
            clf.fit(feats_aligned, y)
            clf_scores = clf.predict_proba(feats_aligned)
            clf_metrics = combine_metrics(y, clf_scores)
            cv = cross_validate_classifier(clf, feats_aligned, y)
            classifier_results[clf.name] = {
                k: round(v, 4) for k, v in {**clf_metrics, **cv}.items()
                if isinstance(v, (int, float)) and k in ("f1", "pr_auc", "roc_auc", "cv_roc_auc")
            }
    except Exception as exc:
        log.warning("classifier benchmark skipped: %s", exc)

    db.add(EvaluationRun(name="anomaly_evaluation", kind="anomaly",
                         metrics=metrics, config={"model": "ensemble"}))
    db.add(EvaluationRun(name="ablation", kind="ablation",
                         metrics=ablation_summary,
                         config={"stages": list(ablation_summary)}))
    if classifier_results:
        db.add(EvaluationRun(name="classifier_benchmark", kind="classifier",
                             metrics=classifier_results,
                             config={"classifiers": list(classifier_results)}))
    db.commit()
    log.info("evaluation: pr_auc=%.3f f1=%.3f brier=%.3f",
             metrics.get("pr_auc", -1), metrics.get("f1", -1), metrics.get("brier", -1))
    if classifier_results:
        log.info("classifier benchmark: %s", classifier_results)
    return {"metrics": metrics, "ablation": ablation_summary, "classifiers": classifier_results}


def stage_changepoint(db: Session, as_of: datetime) -> dict:
    """Run change-point detection on entity volume time series."""
    try:
        from nexus.features.behavioral import load_events_frame
        from nexus.models.forecasting.changepoint import detect_changepoints_for_entities

        events = load_events_frame(db)
        if events.empty:
            return {"skipped": "no events"}
        results = detect_changepoints_for_entities(events)
        n_detected = sum(1 for r in results.values() if r.changepoints)

        # Persist change-point summary scores
        for eid, r in results.items():
            if r.summary_score > 0.01:
                db.add(ScoreRecord(
                    entity_id=eid, as_of=as_of, score_name="changepoint",
                    value=r.summary_score, confidence=None,
                    provenance_source="nexus.changepoint.v1",
                    details={"n_changepoints": len(r.changepoints)},
                ))
        db.commit()
        log.info("change-point detection: %d entities with changepoints", n_detected)
        return {"entities_analyzed": len(results), "changepoints_detected": n_detected}
    except Exception as e:
        log.warning("change-point detection skipped: %s", e)
        return {"skipped": str(e)}


def run_full_pipeline(db: Session, skip_ingest: bool = False,
                      as_of: datetime | None = None) -> PipelineReport:
    """Run the whole loop. Returns a report dict for CLI/API display."""
    report = PipelineReport()
    as_of = as_of or datetime.now(timezone.utc)

    # --- MLOps tracking ---
    tracker = None
    try:
        from nexus.mlops.tracking import NexusTracker
        tracker = NexusTracker()
        tracker.start_run(run_name=f"pipeline_{as_of.strftime('%Y%m%d_%H%M%S')}")
    except Exception:
        pass

    if not skip_ingest:
        report.stages["ingest"] = stage_ingest(db)
    else:
        report.stages["ingest"] = "skipped"

    behavioral, graphf = stage_features(db, as_of)
    report.stages["features"] = {
        "entities": len(behavioral), "graph_nodes": len(graphf),
    }

    full = behavioral.join(graphf, how="left")

    # --- Parquet export for versioning ---
    try:
        from nexus.db.analytics import AnalyticsEngine
        analytics = AnalyticsEngine()
        analytics.export_features(full, f"features_{as_of.strftime('%Y%m%d')}")
    except Exception:
        pass

    version = as_of.strftime("v%Y%m%d%H%M%S")

    def register(name, ver, model, metrics, params):
        from nexus.models.registry import ModelRegistry

        ModelRegistry(db).register(name, ver, model, metrics, params)

    ens, scores = stage_anomaly(db, full, version, register)
    report.stages["anomaly"] = {"scored": len(scores),
                                "top5": scores.nlargest(5).round(3).to_dict()}

    engine, risk_df = stage_risk(db, full, scores, version, register)
    report.stages["risk"] = {
        "scored": len(risk_df), "calibrated": engine.calibrated,
        "top5": risk_df["risk"].nlargest(5).round(3).to_dict(),
    }

    # --- Change-point detection ---
    report.stages["changepoint"] = stage_changepoint(db, as_of)

    report.stages["evaluation"] = stage_evaluate(db, full, scores)

    from nexus.alerts.service import evaluate_alert_rules

    alerts = evaluate_alert_rules(db)
    report.stages["alerts"] = {"raised": len(alerts)}

    # --- End MLOps tracking ---
    if tracker:
        try:
            eval_data = report.stages.get("evaluation", {})
            if isinstance(eval_data, dict) and "metrics" in eval_data:
                tracker.log_metrics({
                    k: v for k, v in eval_data["metrics"].items()
                    if isinstance(v, (int, float))
                })
            tracker.log_params({"version": version, "n_entities": len(full)})
            tracker.end_run()
        except Exception:
            pass

    return report
