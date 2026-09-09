"""Volume forecasting using exponentially weighted moving average (EWMA).

Provides:
- Rolling EWMA forecast for entity transaction volume
- Deviation detection: flag when actual volume deviates significantly from
  the EWMA prediction (rolling Z-score)
- Forecast results stored with provenance for the risk engine

This is a deliberately simple baseline — the blueprint mandates strong baselines
before any complex models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from nexus.core.logging_setup import get_logger

log = get_logger("nexus.models.forecasting.volume")


@dataclass
class ForecastResult:
    """Forecast for a single entity."""
    entity_id: str
    predicted_volume: float  # EWMA predicted next-period volume
    actual_volume: float | None  # latest actual (if available)
    deviation_z: float  # z-score of actual vs prediction
    trend: str  # "increasing" | "decreasing" | "stable"
    forecast_values: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "predicted_volume": round(self.predicted_volume, 6),
            "actual_volume": round(self.actual_volume, 6) if self.actual_volume is not None else None,
            "deviation_z": round(self.deviation_z, 4),
            "trend": self.trend,
        }


class EWMAForecaster:
    """Exponentially weighted moving average volume forecaster.

    Parameters:
        span: EWMA span (number of observations for decay factor)
        z_threshold: z-score threshold to flag deviations
        period_hours: aggregation period in hours (default 24h)
    """

    def __init__(
        self, span: int = 7, z_threshold: float = 2.0, period_hours: int = 24,
    ) -> None:
        self.span = span
        self.z_threshold = z_threshold
        self.period_hours = period_hours

    def _aggregate_series(
        self, events: pd.DataFrame, entity_id: str,
    ) -> pd.Series:
        """Aggregate entity volume into fixed-period buckets."""
        e = events[
            (events["from_entity"] == entity_id) | (events["to_entity"] == entity_id)
        ].sort_values("timestamp")
        if e.empty:
            return pd.Series(dtype=float)

        # Resample to fixed periods
        e = e.set_index("timestamp")
        freq = f"{self.period_hours}h"
        volume = e["value_eth"].resample(freq).sum().fillna(0.0)
        return volume

    def forecast_entity(
        self, events: pd.DataFrame, entity_id: str,
    ) -> ForecastResult:
        """Generate EWMA forecast for a single entity."""
        volume = self._aggregate_series(events, entity_id)

        if len(volume) < 3:
            return ForecastResult(
                entity_id=entity_id,
                predicted_volume=0.0,
                actual_volume=float(volume.iloc[-1]) if len(volume) > 0 else None,
                deviation_z=0.0,
                trend="stable",
            )

        # Compute EWMA
        ewma = volume.ewm(span=self.span, min_periods=1).mean()
        ewma_std = volume.ewm(span=self.span, min_periods=2).std().fillna(
            volume.std() if volume.std() > 0 else 1e-9,
        )

        # Predicted = last EWMA value
        predicted = float(ewma.iloc[-1])
        actual = float(volume.iloc[-1])
        std = max(float(ewma_std.iloc[-1]), 1e-9)
        deviation_z = (actual - predicted) / std

        # Trend detection
        if len(ewma) >= 3:
            recent = ewma.iloc[-3:]
            slope = float(np.polyfit(range(len(recent)), recent.values, 1)[0])
            if slope > std * 0.1:
                trend = "increasing"
            elif slope < -std * 0.1:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return ForecastResult(
            entity_id=entity_id,
            predicted_volume=predicted,
            actual_volume=actual,
            deviation_z=float(deviation_z),
            trend=trend,
            forecast_values=ewma.tail(10).round(6).tolist(),
        )

    def forecast_all(
        self,
        events: pd.DataFrame,
        entities: list[str] | None = None,
    ) -> dict[str, ForecastResult]:
        """Forecast volume for all entities."""
        if entities is None:
            entities = sorted(set(events["from_entity"]) | set(events["to_entity"]))

        results: dict[str, ForecastResult] = {}
        for ent in entities:
            results[ent] = self.forecast_entity(events, ent)

        anomalous = sum(
            1 for r in results.values() if abs(r.deviation_z) > self.z_threshold
        )
        log.info(
            "volume forecast: %d entities, %d anomalous deviations (|z| > %.1f)",
            len(results), anomalous, self.z_threshold,
        )
        return results
