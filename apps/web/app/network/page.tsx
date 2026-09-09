"use client";

import { API, Loading, PageTitle, fmtNum, short, useApi } from "@/lib/ui";
import { GraphView } from "@/lib/graph";

interface FullGraph {
  nodes: { id: string; label: string | null; degree: number }[];
  edges: { source: string; target: string; weight: number }[];
}

export default function NetworkPage() {
  const { data } = useApi<FullGraph>(`${API}/graph?limit=70`);
  const nodes = data?.nodes ?? [];
  const hubs = [...nodes].sort((a, b) => b.degree - a.degree).slice(0, 15);
  return (
    <>
      <PageTitle
        title="Network Intelligence"
        subtitle="Interaction graph of the strongest relationships - node size = activity, color = risk"
      />
      <div className="grid cols-2">
        <div className="card">
          <h3>Interaction Graph</h3>
          {data ? (
            <GraphView
              nodes={nodes}
              edges={data.edges}
              height={520}
              onSelect={(id) => window.location.assign(`/entities?q=${id}`)}
            />
          ) : (
            <Loading />
          )}
        </div>
        <div className="card">
          <h3>Network Hubs (by interaction count)</h3>
          <table>
            <thead><tr><th>Entity</th><th>Activity</th></tr></thead>
            <tbody>
              {hubs.map((n) => (
                <tr key={n.id} className="clickable" onClick={() => window.location.assign(`/entities?q=${n.id}`)}>
                  <td className="mono">{n.label ?? short(n.id, 16)}</td>
                  <td className="mono dim">{fmtNum(n.degree, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
