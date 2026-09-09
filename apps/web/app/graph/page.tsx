"use client";

import { API, Loading, PageTitle, fmtNum, short, useApi } from "@/lib/ui";
import { GraphView } from "@/lib/graph";
import { useState } from "react";

export default function GraphExplorerPage() {
  const [size, setSize] = useState(60);
  const { data } = useApi<{ nodes: { id: string; label: string | null; degree: number }[]; edges: { source: string; target: string; weight: number }[] }>(
    `${API}/graph?limit=${size}`, [size],
  );
  return (
    <>
      <PageTitle title="Graph Explorer" subtitle="Explore the Ethereum interaction graph (aggregate strongest edges)" />
      <div className="chips">
        {[30, 60, 100, 150].map((n) => (
          <button key={n} className={`chip ${size === n ? "active" : ""}`} onClick={() => setSize(n)}>
            top {n} nodes
          </button>
        ))}
      </div>
      <div className="card">
        {data ? (
          <GraphView
            nodes={data.nodes}
            edges={data.edges}
            height={600}
            onSelect={(id) => window.location.assign(`/entities?q=${id}`)}
          />
        ) : (
          <Loading />
        )}
      </div>
      <p className="dim" style={{ marginTop: 10, fontSize: 12 }}>
        {data?.nodes.length ?? 0} nodes · {data?.edges.length ?? 0} edges. Click a node to open its investigation page.
      </p>
    </>
  );
}
