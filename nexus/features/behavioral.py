"""Behavioral + temporal features per entity, computed with strict point-in-time
semantics: features as of time T use ONLY events with timestamp <= T.

Feature families (per blueprint):
- activity: tx counts over 1h/24h/7d/30d + all-time rate
- value: volume, mean, median, recent-vs-historical volume ratio
- diversity: unique counterparties/contracts/tokens over recent window
- temporal: inter-transaction interval stats, entropy of hour-of-day
- behavioral change: new-counterparty fraction, volume shift z-score
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.db.schema import Event

FEATURE_NAMES: list[str] = [
    # activity
    "tx_count_1h", "tx_count_24h", "tx_count_7d", "tx_count_30d",
    "tx_rate_per_day",
    # value
    "volume_24h_eth", "volume_7d_eth", "volume_30d_eth",
    "avg_value_eth", "median_value_eth", "max_value_eth",
    "value_volatility",
    # diversity
    "unique_counterparties_30d", "unique_counterparties_ratio",
    "unique_contracts_30d",
    # temporal
    "inter_tx_mean_hours", "inter_tx_std_hours", "inter_tx_entropy",
    "hour_entropy", "night_ratio",
    # behavioral change
    "volume_recent_vs_hist", "new_counterparty_fraction",
    "interval_shift_z", "burstiness",
]

FEATURE_NAMES_SET = set(FEATURE_NAMES)


def load_events_frame(db: Session) -> pd.DataFrame:
    rows = db.execute(
        select(
            Event.id, Event.type, Event.timestamp, Event.from_entity,
            Event.to_entity, Event.value_wei, Event.gas_used, Event.gas_price_gwei,
        ).order_by(Event.timestamp)
    ).all()
    df = pd.DataFrame(
        rows,
        columns=["id", "type", "timestamp", "from_entity", "to_entity",
                 "value_wei", "gas_used", "gas_price_gwei"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["value_eth"] = df["value_wei"].astype("float64") / 1e18
    return df


def _entropy(counts: np.ndarray) -> float:
    counts = counts[counts > 0].astype(float)
    if counts.size == 0:
        return 0.0
    p = counts / counts.sum()
    return float(-(p * np.log2(p)).sum())


@dataclass
class FeatureWindow:
    as_of: datetime
    frame: pd.DataFrame  # one row per entity


def compute_entity_features(
    events: pd.DataFrame, as_of: datetime, entities: list[str] | None = None,
) -> pd.DataFrame:
    """Point-in-time features for each entity (both directions) as of `as_of`.

    `events` must contain column 'timestamp' as tz-aware datetime and columns
    from_entity/to_entity/value_eth/type.
    """
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    hist = events[events["timestamp"] <= as_of]
    rows: list[dict] = []

    if entities is None:
        entities = sorted(set(hist["from_entity"]) | set(hist["to_entity"]))

    out_index = []
    for ent in entities:
        # events where entity is sender OR receiver (address activity, both directions)
        e = hist[(hist["from_entity"] == ent) | (hist["to_entity"] == ent)]
        out_index.append(ent)
        row: dict[str, float | int] = {name: 0.0 for name in FEATURE_NAMES}

        if e.empty:
            rows.append(row)
            continue

        ts = e["timestamp"]
        now = as_of
        last_1h = now - timedelta(hours=1)
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)

        # ---------------- activity
        row["tx_count_1h"] = int((ts >= last_1h).sum())
        row["tx_count_24h"] = int((ts >= last_24h).sum())
        row["tx_count_7d"] = int((ts >= last_7d).sum())
        row["tx_count_30d"] = int((ts >= last_30d).sum())
        span_days = max((ts.max() - ts.min()).total_seconds() / 86400, 1 / 24)
        row["tx_rate_per_day"] = len(e) / span_days

        # ---------------- value
        val = e["value_eth"].astype(float)
        row["volume_24h_eth"] = float(e.loc[ts >= last_24h, "value_eth"].sum())
        row["volume_7d_eth"] = float(e.loc[ts >= last_7d, "value_eth"].sum())
        row["volume_30d_eth"] = float(e.loc[ts >= last_30d, "value_eth"].sum())
        row["avg_value_eth"] = float(val.mean())
        row["median_value_eth"] = float(val.median())
        row["max_value_eth"] = float(val.max())
        row["value_volatility"] = float(val.std() / val.mean()) if val.mean() > 0 else 0.0

        # ---------------- diversity (last 30d, counterparties on either side)
        recent = e[ts >= last_30d]
        if not recent.empty:
            counterparties = pd.concat([
                recent.loc[recent["from_entity"] == ent, "to_entity"],
                recent.loc[recent["to_entity"] == ent, "from_entity"],
            ])
            row["unique_counterparties_30d"] = int(counterparties.nunique())
            row["unique_counterparties_ratio"] = (
                counterparties.nunique() / len(recent) if len(recent) else 0.0
            )
            row["unique_contracts_30d"] = int(
                recent.loc[recent["type"] == "contract_call", "to_entity"].nunique()
            )

        # ---------------- temporal
        tsorted = ts.sort_values()
        gaps = tsorted.diff().dt.total_seconds().dropna() / 3600.0
        if len(gaps):
            row["inter_tx_mean_hours"] = float(gaps.mean())
            row["inter_tx_std_hours"] = float(gaps.std())
            row["inter_tx_entropy"] = _entropy(np.histogram(gaps, bins=12)[0])
        hours = ts.dt.hour.to_numpy()
        row["hour_entropy"] = _entropy(np.bincount(hours, minlength=24))
        row["night_ratio"] = float(((hours < 6) | (hours >= 22)).mean())

        # ---------------- behavioral change
        window_start = last_7d - timedelta(days=30)  # 7d..37d ago = prior baseline
        prior = e[(ts < last_7d) & (ts >= window_start)]
        recent_vol = float(e.loc[ts >= last_7d, "value_eth"].sum())
        prior_vol = float(prior["value_eth"].sum())
        row["volume_recent_vs_hist"] = (
            recent_vol / prior_vol if prior_vol > 0 else (5.0 if recent_vol > 0 else 0.0)
        )
        # new counterparties in last 7d not seen before
        prev = e[ts < last_7d]
        if not prev.empty and not recent.empty:
            prev_cp = set(prev.loc[prev["from_entity"] == ent, "to_entity"]) | set(
                prev.loc[prev["to_entity"] == ent, "from_entity"]
            )
            recent_cp = set(recent.loc[recent["from_entity"] == ent, "to_entity"]) | set(
                recent.loc[recent["to_entity"] == ent, "from_entity"]
            )
            row["new_counterparty_fraction"] = (
                len(recent_cp - prev_cp) / len(recent_cp) if recent_cp else 0.0
            )
        if len(gaps) > 4:
            old_gaps = gaps.iloc[: len(gaps) // 2]
            new_gaps = gaps.iloc[len(gaps) // 2:]
            row["interval_shift_z"] = float(
                (new_gaps.mean() - old_gaps.mean()) / (old_gaps.std() + 1e-9)
            )
        # burstiness: Fano-factor-like coefficient of counts per day
        per_day = e.set_index("timestamp").resample("1D").size()
        if len(per_day) > 1:
            mu, var = per_day.mean(), per_day.var()
            row["burstiness"] = float((var - mu) / (var + mu)) if (var + mu) > 0 else 0.0

        rows.append(row)

    frame = pd.DataFrame(rows, index=out_index)
    return frame.astype(float)


def compute_features(
    db: Session, as_of: datetime, entities: list[str] | None = None
) -> pd.DataFrame:
    events = load_events_frame(db)
    return compute_entity_features(events, as_of, entities)
