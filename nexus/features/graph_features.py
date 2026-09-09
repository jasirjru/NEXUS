"""Graph intelligence (NetworkX-first, per blueprint: advanced GNNs only later,
and only if they measurably beat these baselines).

Builds a directed interaction graph from the event store and computes:
- degree (in/out), PageRank, betweenness, clustering coefficient
- community membership (greedy modularity)
Optionally node embeddings via spectral method (SVD of adjacency) - cheap,
deterministic, and a fair 'embedding' baseline before any GNN.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.core.logging_setup import get_logger
from nexus.db.schema import Event

log = get_logger("nexus.features.graph")

GRAPH_FEATURE_NAMES = [
    "degree_in", "degree_out", "pagerank", "betweenness",
    "clustering", "community_size", "embedding_0", "embedding_1",
    "embedding_2", "embedding_3",
]


def build_graph(db: Session, max_events: int | None = None) -> nx.DiGraph:
    """Directed graph: edge per (from,to) pair, aggregated with count/weight."""
    q = select(Event.from_entity, Event.to_entity, Event.value_wei).order_by(Event.timestamp)
    if max_events:
        q = q.limit(max_events)
    g = nx.DiGraph()
    for src, dst, val in db.execute(q):
        if g.has_edge(src, dst):
            g[src][dst]["weight"] += 1
            g[src][dst]["value"] += val
        else:
            g.add_edge(src, dst, weight=1, value=int(val))
    log.info("graph built: %d nodes, %d edges", g.number_of_nodes(), g.number_of_edges())
    return g


@dataclass
class GraphFeatures:
    frame: pd.DataFrame  # indexed by entity id


def compute_graph_features(g: nx.DiGraph, embedding_dim: int = 4) -> GraphFeatures:
    if g.number_of_nodes() == 0:
        return GraphFeatures(frame=pd.DataFrame(columns=GRAPH_FEATURE_NAMES))

    log.info("computing pagerank/betweenness/communities ...")
    pagerank = nx.pagerank(g, alpha=0.85)
    betweenness = nx.betweenness_centrality(g, normalized=True)
    clustering = nx.clustering(g.to_undirected())
    communities = nx.community.greedy_modularity_communities(g.to_undirected())
    community_of: dict[str, int] = {}
    for ci, com in enumerate(communities):
        for n in com:
            community_of[n] = ci
    community_sizes = {ci: len(com) for ci, com in enumerate(communities)}

    # spectral embedding via SVD on the adjacency matrix (deterministic)
    nodes = sorted(g.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    adj = nx.to_scipy_sparse_array(g, nodelist=nodes, weight=None)
    k = min(embedding_dim, max(1, min(len(nodes) - 1, 8)))
    from scipy.sparse import csc_matrix
    from scipy.sparse.linalg import svds

    try:
        u, s, _ = svds(csc_matrix(adj).asfptype(), k=k)
        order = np.argsort(-s)
        u = u[:, order]
        emb = np.abs(u[:, :k])
    except Exception:
        emb = np.zeros((len(nodes), k))

    rows = {}
    for n in nodes:
        ci = community_of.get(n, -1)
        rows[n] = {
            "degree_in": g.in_degree(n),
            "degree_out": g.out_degree(n),
            "pagerank": pagerank.get(n, 0.0),
            "betweenness": betweenness.get(n, 0.0),
            "clustering": clustering.get(n, 0.0),
            "community_size": community_sizes.get(ci, 0),
        }
        for j in range(min(4, emb.shape[1])):
            rows[n][f"embedding_{j}"] = float(emb[nodes.index(n), j])

    frame = pd.DataFrame.from_dict(rows, orient="index")
    for col in GRAPH_FEATURE_NAMES:
        if col not in frame:
            frame[col] = 0.0
    frame = frame[GRAPH_FEATURE_NAMES].astype(float)
    return GraphFeatures(frame=frame)
