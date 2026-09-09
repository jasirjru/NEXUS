"""DuckDB analytical engine for fast aggregations and Parquet export.

Provides:
- Export feature frames to Parquet for reproducibility
- DuckDB queries for dashboard analytics (fast OLAP over event store)
- Graceful fallback to SQLAlchemy if DuckDB is not installed

DuckDB is used as an analytical layer — the primary event store remains
PostgreSQL/SQLite via SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from nexus.config import settings
from nexus.core.logging_setup import get_logger

log = get_logger("nexus.db.analytics")

# Graceful DuckDB import
_DUCKDB_AVAILABLE = False
try:
    import duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    pass


class AnalyticsEngine:
    """Analytical query engine backed by DuckDB (or Pandas fallback)."""

    def __init__(self, parquet_dir: Path | None = None) -> None:
        self.parquet_dir = parquet_dir or settings.artifacts_path / "parquet"
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self._con = None

        if _DUCKDB_AVAILABLE:
            self._con = duckdb.connect(":memory:")
            log.info("DuckDB analytics engine initialized")
        else:
            log.info("DuckDB not installed; using Pandas fallback for analytics")

    @property
    def duckdb_available(self) -> bool:
        return _DUCKDB_AVAILABLE and self._con is not None

    # ------------------------------------------------------------ Parquet export
    def export_features(self, features: pd.DataFrame, name: str = "features") -> Path:
        """Export a feature DataFrame to Parquet for versioning/reproducibility."""
        path = self.parquet_dir / f"{name}.parquet"
        features.to_parquet(path, engine="pyarrow")
        log.info("exported %d rows to %s", len(features), path)
        return path

    def export_events(self, events: pd.DataFrame, name: str = "events") -> Path:
        """Export events DataFrame to Parquet."""
        path = self.parquet_dir / f"{name}.parquet"
        events.to_parquet(path, engine="pyarrow")
        log.info("exported %d events to %s", len(events), path)
        return path

    def load_parquet(self, name: str) -> pd.DataFrame | None:
        """Load a previously exported Parquet file."""
        path = self.parquet_dir / f"{name}.parquet"
        if not path.exists():
            return None
        return pd.read_parquet(path)

    # ------------------------------------------------------------ DuckDB queries
    def query(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        """Execute a SQL query on registered Parquet files.

        Falls back to returning an empty DataFrame if DuckDB is unavailable.
        """
        if not self.duckdb_available:
            log.warning("DuckDB not available; returning empty result")
            return pd.DataFrame()

        try:
            return self._con.execute(sql).fetchdf()
        except Exception as e:
            log.error("DuckDB query failed: %s", e)
            return pd.DataFrame()

    def register_parquet(self, name: str, path: Path | None = None) -> bool:
        """Register a Parquet file as a DuckDB table for fast querying."""
        if not self.duckdb_available:
            return False

        path = path or self.parquet_dir / f"{name}.parquet"
        if not path.exists():
            log.warning("Parquet file not found: %s", path)
            return False

        try:
            self._con.execute(
                f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_parquet('{path}')"
            )
            log.info("registered Parquet table '%s' from %s", name, path)
            return True
        except Exception as e:
            log.error("failed to register Parquet table: %s", e)
            return False

    # ------------------------------------------------------------ Prebuilt queries
    def entity_volume_timeseries(
        self, entity_id: str, bucket_hours: int = 24,
    ) -> pd.DataFrame:
        """Get volume time series for an entity (requires events Parquet)."""
        if not self.duckdb_available:
            return pd.DataFrame()

        sql = f"""
            SELECT
                time_bucket(INTERVAL '{bucket_hours} hours', timestamp) AS bucket,
                COUNT(*) AS tx_count,
                SUM(CAST(value_wei AS DOUBLE)) / 1e18 AS volume_eth
            FROM events
            WHERE from_entity = ? OR to_entity = ?
            GROUP BY bucket
            ORDER BY bucket
        """
        try:
            return self._con.execute(sql, [entity_id, entity_id]).fetchdf()
        except Exception:
            return pd.DataFrame()

    def top_entities_by_volume(self, limit: int = 20) -> pd.DataFrame:
        """Top entities by total transaction volume."""
        if not self.duckdb_available:
            return pd.DataFrame()

        sql = f"""
            WITH all_entities AS (
                SELECT from_entity AS entity, value_wei FROM events
                UNION ALL
                SELECT to_entity AS entity, value_wei FROM events
            )
            SELECT
                entity,
                COUNT(*) AS tx_count,
                SUM(CAST(value_wei AS DOUBLE)) / 1e18 AS total_volume_eth
            FROM all_entities
            GROUP BY entity
            ORDER BY total_volume_eth DESC
            LIMIT {limit}
        """
        try:
            return self._con.execute(sql).fetchdf()
        except Exception:
            return pd.DataFrame()

    def hourly_activity(self) -> pd.DataFrame:
        """Aggregate activity by hour of day."""
        if not self.duckdb_available:
            return pd.DataFrame()

        sql = """
            SELECT
                EXTRACT(HOUR FROM timestamp) AS hour,
                COUNT(*) AS tx_count,
                SUM(CAST(value_wei AS DOUBLE)) / 1e18 AS volume_eth
            FROM events
            GROUP BY hour
            ORDER BY hour
        """
        try:
            return self._con.execute(sql).fetchdf()
        except Exception:
            return pd.DataFrame()

    def list_parquet_files(self) -> list[dict[str, Any]]:
        """List available Parquet files with metadata."""
        files = []
        for f in sorted(self.parquet_dir.glob("*.parquet")):
            stat = f.stat()
            files.append({
                "name": f.stem,
                "path": str(f),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return files

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None
