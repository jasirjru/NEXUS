"""Feature engine tests: point-in-time correctness and families."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from nexus.features.behavioral import FEATURE_NAMES, compute_entity_features
from nexus.features.graph_features import GRAPH_FEATURE_NAMES, compute_graph_features


def _mk_events():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    # wallet A: two txs on day 1, one on day 10 (huge gap -> interval shift)
    for d, val in [(0, 1.0), (0, 2.0), (10, 50.0)]:
        rows.append({
            "id": f"e{len(rows)}", "type": "transaction",
            "timestamp": base + timedelta(days=d),
            "from_entity": "A", "to_entity": "B",
            "value_eth": val, "gas_used": 21000, "gas_price_gwei": 20.0,
            "value_wei": int(val * 1e18),
        })
    return pd.DataFrame(rows)


def test_features_point_in_time():
    events = _mk_events()
    early = datetime(2026, 1, 2, tzinfo=timezone.utc)
    f_early = compute_entity_features(events, as_of=early)
    late = datetime(2026, 1, 11, tzinfo=timezone.utc)
    quiet = datetime(2026, 1, 5, tzinfo=timezone.utc)
    f_late = compute_entity_features(events, as_of=late)
    f_quiet = compute_entity_features(events, as_of=quiet)

    assert f_early.loc["A", "tx_count_24h"] == 2
    assert f_quiet.loc["A", "tx_count_24h"] == 0  # day-10 tx must not appear early
    assert f_late.loc["A", "tx_count_24h"] == 1  # the day-10 tx, within 24h
    # future data must NOT leak into early features
    assert f_early.loc["A", "max_value_eth"] == 2.0
    assert f_late.loc["A", "max_value_eth"] == 50.0


def test_feature_families_present():
    events = _mk_events()
    f = compute_entity_features(events, as_of=datetime(2026, 1, 11, tzinfo=timezone.utc))
    assert set(FEATURE_NAMES).issubset(f.columns)


def test_volume_shift_detected():
    events = _mk_events()
    late = datetime(2026, 1, 11, tzinfo=timezone.utc)
    f = compute_entity_features(events, as_of=late)
    # 50 ETH in last 7d vs 3 ETH prior -> strong shift
    assert f.loc["A", "volume_recent_vs_hist"] > 5.0


def test_graph_features_shape():
    import networkx as nx

    g = nx.DiGraph()
    g.add_edge("a", "b", weight=3, value=10)
    g.add_edge("b", "c", weight=1, value=5)
    g.add_edge("c", "a", weight=1, value=5)
    gf = compute_graph_features(g)
    assert set(GRAPH_FEATURE_NAMES).issubset(gf.frame.columns)
    assert gf.frame.loc["a", "degree_out"] == 1
    assert 0.0 < gf.frame.loc["a", "pagerank"] < 1.0
