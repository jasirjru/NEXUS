"""Tests for GNN models (skip if PyTorch Geometric not installed)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexus.models.graph.gnn import GNNDetector, build_edge_index_from_graph, _PYG_AVAILABLE


@pytest.mark.skipif(not _PYG_AVAILABLE, reason="torch-geometric not installed")
class TestGNNDetector:
    def _make_data(self):
        n_nodes = 30
        n_features = 8
        rng = np.random.RandomState(42)
        features = pd.DataFrame(
            rng.randn(n_nodes, n_features),
            columns=[f"f{i}" for i in range(n_features)],
            index=[f"node_{i}" for i in range(n_nodes)],
        )
        # Random graph edges
        edges_src = rng.randint(0, n_nodes, 50)
        edges_dst = rng.randint(0, n_nodes, 50)
        edge_index = np.array([edges_src, edges_dst], dtype=np.int64)
        labels = np.concatenate([np.zeros(n_nodes - 5), np.ones(5)]).astype(int)
        rng.shuffle(labels)
        return features, edge_index, labels

    def test_graphsage_supervised(self):
        features, edge_index, labels = self._make_data()
        det = GNNDetector(architecture="graphsage", epochs=10)
        det.fit(features, edge_index, labels)
        scores = det.score(features, edge_index)
        assert scores.shape == (len(features),)
        assert 0 <= scores.min() and scores.max() <= 1

    def test_gat_supervised(self):
        features, edge_index, labels = self._make_data()
        det = GNNDetector(architecture="gat", epochs=10)
        det.fit(features, edge_index, labels)
        scores = det.score(features, edge_index)
        assert scores.shape == (len(features),)

    def test_unsupervised(self):
        features, edge_index, _ = self._make_data()
        det = GNNDetector(architecture="graphsage", epochs=10)
        det.fit(features, edge_index, labels=None)
        scores = det.score(features, edge_index)
        assert scores.shape == (len(features),)


class TestGNNUnavailable:
    def test_unavailable_returns_default(self):
        if _PYG_AVAILABLE:
            pytest.skip("PyG is installed; testing unavailable path not meaningful")
        det = GNNDetector()
        assert not det.available
        scores = det.score(pd.DataFrame(np.zeros((5, 3))), np.zeros((2, 0), dtype=np.int64))
        assert all(s == 0.5 for s in scores)


class TestBuildEdgeIndex:
    def test_from_networkx(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("b", "c"), ("c", "a")])
        nodes = ["a", "b", "c"]
        ei = build_edge_index_from_graph(g, nodes)
        assert ei.shape[0] == 2
        assert ei.shape[1] == 3
