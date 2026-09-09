"""Evaluation metrics. Only MEASURED results here - no invented numbers."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    ndcg_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def classification_metrics(y_true, scores) -> dict[str, float]:
    """Threshold-free + thresholded metrics at the best-F1 operating point."""
    y_true = np.asarray(y_true).astype(int)
    scores = np.asarray(scores, dtype=float)
    out: dict[str, float] = {}
    if len(np.unique(y_true)) < 2:
        # cannot compute classification metrics with a single class; ranking
        # metrics may still be meaningful (handled by caller)
        out["single_class"] = 1.0
        return out
    # choose threshold maximizing F1, restricted to rates <= ~2x the anomaly
    # prevalence so the degenerate "flag everyone" solution is excluded
    prevalence = float(y_true.mean())
    thresholds = np.quantile(scores, np.linspace(0.01, 0.99, 99))
    best_f1, best_t = -1.0, float(np.quantile(scores, 1 - prevalence))
    for t in thresholds:
        preds = (scores >= t).astype(int)
        if preds.mean() > 2 * max(prevalence, 0.01):
            continue
        f1 = f1_score(y_true, preds, zero_division=0)
        if f1 > best_f1:
            best_f1, best_t = f1, t
    preds = (scores >= best_t).astype(int)
    out.update(
        precision=float(precision_score(y_true, preds, zero_division=0)),
        recall=float(recall_score(y_true, preds, zero_division=0)),
        f1=float(best_f1),
        best_threshold=float(best_t),
        pr_auc=float(average_precision_score(y_true, scores)),
        roc_auc=float(roc_auc_score(y_true, scores)),
        false_positive_rate=float(((preds == 1) & (y_true == 0)).sum() / max((y_true == 0).sum(), 1)),
    )
    return out


def ranking_metrics(y_true, scores, k_values=(10, 25)) -> dict[str, float]:
    y_true = np.asarray(y_true).astype(int)
    scores = np.asarray(scores, dtype=float)
    out: dict[str, float] = {}
    order = np.argsort(-scores)
    sorted_true = y_true[order]
    total_pos = sorted_true.sum()
    for k in k_values:
        if k > len(y_true):
            continue
        top_k = sorted_true[:k]
        out[f"precision_at_{k}"] = float(top_k.mean()) if k else 0.0
        out[f"recall_at_{k}"] = float(top_k.sum() / total_pos) if total_pos else 0.0
    # NDCG with binary gains
    try:
        out["ndcg"] = float(ndcg_score([y_true], [scores]))
    except ValueError:
        out["ndcg"] = 0.0
    # MAP
    hits, sum_prec = 0, 0.0
    for i, rel in enumerate(sorted_true):
        if rel == 1:
            hits += 1
            sum_prec += hits / (i + 1)
    out["map"] = float(sum_prec / total_pos) if total_pos else 0.0
    return out


def calibration_metrics(y_true, probs) -> dict[str, any]:
    """Brier score + calibration curve data (bin structure for plotting)."""
    y_true = np.asarray(y_true).astype(int)
    probs = np.asarray(probs, dtype=float)
    out: dict[str, any] = {"brier": float(brier_score_loss(y_true, probs))}
    bins = np.linspace(0, 1, 11)
    digitized = np.digitize(probs, bins) - 1
    curve_x, curve_y, curve_n = [], [], []
    for b in range(len(bins) - 1):
        mask = digitized == b
        if mask.sum() > 0:
            curve_x.append(float(bins[b] + 0.05))
            curve_y.append(float(y_true[mask].mean()))
            curve_n.append(int(mask.sum()))
    out["calibration_curve"] = {"bins": curve_x, "empirical": curve_y, "counts": curve_n}
    return out


def combine_metrics(y_true, scores, probs=None) -> dict:
    out = {**classification_metrics(y_true, scores), **ranking_metrics(y_true, scores)}
    if probs is not None:
        out.update(calibration_metrics(y_true, probs))
    return out
