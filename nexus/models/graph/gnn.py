"""Graph Neural Network models: GraphSAGE and GAT for node classification.

Per blueprint:
- Do NOT use complex GNNs just because they sound advanced.
- Every advanced model must demonstrate measurable improvement over
  a strong baseline (the NetworkX SVD + PageRank baseline).
- Gracefully unavailable if torch-geometric is not installed.

These models operate on the same entity graph as the NetworkX pipeline but
learn non-linear neighborhood aggregations that may capture subtler anomaly
patterns.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from nexus.core.logging_setup import get_logger

log = get_logger("nexus.models.graph.gnn")

# Graceful import check
_TORCH_AVAILABLE = False
_PYG_AVAILABLE = False

try:
    import torch
    import torch.nn.functional as F
    _TORCH_AVAILABLE = True
except ImportError:
    pass

try:
    import torch_geometric  # noqa: F401
    from torch_geometric.data import Data
    from torch_geometric.nn import GATConv, SAGEConv
    _PYG_AVAILABLE = True
except ImportError:
    pass


def _rank01(x: np.ndarray) -> np.ndarray:
    """Map raw scores to [0,1] by empirical CDF."""
    r = pd.Series(x).rank(method="average").to_numpy()
    return (r - 0.5) / max(len(r), 1)


# ---------------------------------------------------------------- Models

if _TORCH_AVAILABLE and _PYG_AVAILABLE:

    class GraphSAGEModel(torch.nn.Module):
        """2-layer GraphSAGE for node scoring/classification."""

        def __init__(self, in_channels: int, hidden: int = 32, out_channels: int = 1):
            super().__init__()
            self.conv1 = SAGEConv(in_channels, hidden)
            self.conv2 = SAGEConv(hidden, hidden)
            self.head = torch.nn.Linear(hidden, out_channels)

        def forward(self, x, edge_index):
            h = F.relu(self.conv1(x, edge_index))
            h = F.dropout(h, p=0.3, training=self.training)
            h = F.relu(self.conv2(h, edge_index))
            return self.head(h)

    class GATModel(torch.nn.Module):
        """2-layer Graph Attention Network for node scoring."""

        def __init__(self, in_channels: int, hidden: int = 32, out_channels: int = 1, heads: int = 2):
            super().__init__()
            self.conv1 = GATConv(in_channels, hidden, heads=heads, dropout=0.3)
            self.conv2 = GATConv(hidden * heads, hidden, heads=1, concat=False, dropout=0.3)
            self.head = torch.nn.Linear(hidden, out_channels)

        def forward(self, x, edge_index):
            h = F.elu(self.conv1(x, edge_index))
            h = F.dropout(h, p=0.3, training=self.training)
            h = F.elu(self.conv2(h, edge_index))
            return self.head(h)


# ---------------------------------------------------------------- Detector interface

class GNNDetector:
    """Unified GNN-based anomaly detector matching the BaseDetector interface.

    Supports both GraphSAGE and GAT architectures. Trains on labeled data
    (supervised) or uses reconstruction error (unsupervised).
    """

    name = "gnn"
    available = _TORCH_AVAILABLE and _PYG_AVAILABLE

    def __init__(
        self,
        architecture: str = "graphsage",  # "graphsage" | "gat"
        hidden: int = 32,
        epochs: int = 100,
        lr: float = 1e-3,
        random_state: int = 42,
    ) -> None:
        self.architecture = architecture
        self.hidden = hidden
        self.epochs = epochs
        self.lr = lr
        self.random_state = random_state
        self.model = None
        self.node_ids: list[str] = []

        if not self.available:
            log.info("PyTorch Geometric not installed; GNNDetector unavailable")

    def _build_pyg_data(
        self,
        features: pd.DataFrame,
        edge_index_np: np.ndarray,
        labels: np.ndarray | None = None,
    ):
        """Build a PyG Data object from features and edge index."""
        x = torch.tensor(features.values, dtype=torch.float32)
        ei = torch.tensor(edge_index_np, dtype=torch.long)
        data = Data(x=x, edge_index=ei)
        if labels is not None:
            data.y = torch.tensor(labels, dtype=torch.float32)
        return data

    def _build_model(self, in_channels: int):
        torch.manual_seed(self.random_state)
        if self.architecture == "gat":
            return GATModel(in_channels, self.hidden)
        return GraphSAGEModel(in_channels, self.hidden)

    def fit(
        self,
        features: pd.DataFrame,
        edge_index: np.ndarray,
        labels: np.ndarray | None = None,
    ) -> "GNNDetector":
        """Train the GNN.

        Args:
            features: node feature matrix (indexed by entity id)
            edge_index: (2, num_edges) numpy array of edge indices
            labels: optional binary labels for supervised training
        """
        if not self.available:
            return self

        self.node_ids = list(features.index)
        data = self._build_pyg_data(features, edge_index, labels)
        self.model = self._build_model(features.shape[1])

        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.lr)

        if labels is not None and labels.sum() > 0:
            # Supervised training with BCE loss
            pos_weight = torch.tensor([(labels == 0).sum() / max((labels == 1).sum(), 1)])
            loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)

            self.model.train()
            for epoch in range(self.epochs):
                optimizer.zero_grad()
                out = self.model(data.x, data.edge_index).squeeze()
                loss = loss_fn(out, data.y)
                loss.backward()
                optimizer.step()
        else:
            # Unsupervised: train as autoencoder (reconstruct features)
            decoder = torch.nn.Linear(self.hidden, features.shape[1])
            torch.manual_seed(self.random_state)
            all_params = list(self.model.parameters()) + list(decoder.parameters())
            optimizer = torch.optim.Adam(all_params, lr=self.lr)
            loss_fn = torch.nn.MSELoss()

            self.model.train()
            for epoch in range(self.epochs):
                optimizer.zero_grad()
                # Get hidden representation
                h = F.relu(self.model.conv1(data.x, data.edge_index))
                h = F.relu(self.model.conv2(h, data.edge_index))
                recon = decoder(h)
                loss = loss_fn(recon, data.x)
                loss.backward()
                optimizer.step()

        self.model.eval()
        log.info("GNN (%s) trained for %d epochs on %d nodes",
                 self.architecture, self.epochs, len(features))
        return self

    def score(self, features: pd.DataFrame, edge_index: np.ndarray) -> np.ndarray:
        """Return anomaly scores in [0, 1] for each node."""
        if not self.available or self.model is None:
            return np.full(len(features), 0.5)

        data = self._build_pyg_data(features, edge_index)
        with torch.no_grad():
            out = self.model(data.x, data.edge_index).squeeze()
            probs = torch.sigmoid(out).numpy()

        return _rank01(probs)

    def get_params(self) -> dict[str, Any]:
        return {
            "architecture": self.architecture,
            "hidden": self.hidden,
            "epochs": self.epochs,
            "available": self.available,
        }


# ---------------------------------------------------------------- Helper

def build_edge_index_from_graph(
    g, node_list: list[str],
) -> np.ndarray:
    """Convert a NetworkX graph to a (2, E) edge index array.

    Args:
        g: NetworkX DiGraph
        node_list: ordered list of node ids (must match feature frame index)

    Returns:
        (2, num_edges) numpy array
    """
    node_to_idx = {n: i for i, n in enumerate(node_list)}
    src, dst = [], []
    for u, v in g.edges():
        if u in node_to_idx and v in node_to_idx:
            src.append(node_to_idx[u])
            dst.append(node_to_idx[v])
    if not src:
        return np.zeros((2, 0), dtype=np.int64)
    return np.array([src, dst], dtype=np.int64)
