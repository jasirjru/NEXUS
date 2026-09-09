"use client";

import { API, Badge, Loading, PageTitle, fmtNum, useApi } from "@/lib/ui";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export default function TemporalPage() {
  const { data: hist } = useApi<{ items: { bucket: string; count: number; value_eth: number }[] }>(
    `${API}/events/histogram?bucket=day`,
  );
  const { data: drift } = useApi<{ items: { feature: string; psi: number; drift: boolean }[] }>(
    `${API}/metrics/drift`,
  );
  const chart = (hist?.items ?? []).slice(-45);
  return (
    <>
      <PageTitle
        title="Temporal Behavior"
        subtitle="Activity over time + behavioral drift (PSI > 0.2 signals distribution shift)"
      />
      <div className="card">
        <h3>Daily Transaction Count (last 45 days)</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chart}>
            <CartesianGrid stroke="#1e2a3d" strokeDasharray="3 3" />
            <XAxis dataKey="bucket" tick={{ fill: "#7d8ba1", fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} />
            <YAxis tick={{ fill: "#7d8ba1", fontSize: 10 }} />
            <Tooltip
              contentStyle={{ background: "#0f1520", border: "1px solid #1e2a3d", borderRadius: 8 }}
              labelStyle={{ color: "#d7e1ee" }}
            />
            <Bar dataKey="count" fill="#4f9cf9" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h3>Feature Drift (30-day PSI)</h3>
        <table>
          <thead><tr><th>Feature</th><th>PSI</th><th>Status</th></tr></thead>
          <tbody>
            {(drift?.items ?? []).slice(0, 15).map((d) => (
              <tr key={d.feature}>
                <td className="dim">{d.feature.replace(/_/g, " ")}</td>
                <td className="mono">{d.psi.toFixed(4)}</td>
                <td><Badge tone={d.drift ? "crit" : "ok"}>{d.drift ? "drift" : "stable"}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
