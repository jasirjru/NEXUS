"use client";

import Link from "next/link";
import { API, Loading, PageTitle, fmtNum, post, riskColor, RiskBar, short, useApi } from "@/lib/ui";

interface Overview {
  entities: number;
  events: number;
  open_alerts: number;
  investigations: number;
  active_anomalies: number;
  risk_distribution: { low: number; medium: number; high: number; critical: number };
  top_risk: { entity_id: string; risk: number; confidence: number | null }[];
}

export default function OverviewPage() {
  const { data, loading, reload } = useApi<Overview>(`${API}/overview`);
  if (loading && !data) return <Loading />;
  if (!data) return <div className="loading">unavailable</div>;

  const total = Object.values(data.risk_distribution).reduce((a, b) => a + b, 0) || 1;

  return (
    <>
      <PageTitle
        title="Intelligence Overview"
        subtitle="Live state of the observe → learn → detect → predict → investigate loop"
      />
      <div className="grid cols-4">
        <Card label="Events Ingested" value={fmtNum(data.events, 0)} sub="validated + normalized" />
        <Card label="Entities" value={fmtNum(data.entities, 0)} sub="wallets, contracts, protocols" />
        <Card label="Active Anomalies" value={fmtNum(data.active_anomalies, 0)} sub="ensemble score > 0.8" />
        <Card label="Open Alerts" value={fmtNum(data.open_alerts, 0)} sub={`${data.investigations} investigations run`} />
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Risk Distribution</h3>
          {(["low", "medium", "high", "critical"] as const).map((b) => {
            const colors = { low: "var(--ok)", medium: "var(--warn)", high: "#fb923c", critical: "var(--crit)" };
            const pct = Math.round((data.risk_distribution[b] / total) * 100);
            return (
              <div key={b} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                  <span className="dim" style={{ textTransform: "capitalize" }}>{b}</span>
                  <span className="mono">{data.risk_distribution[b]} ({pct}%)</span>
                </div>
                <div className="risk-bar">
                  <div style={{ width: `${pct}%`, background: colors[b] }} />
                </div>
              </div>
            );
          })}
        </div>

        <div className="card">
          <h3>Top Risk Entities</h3>
          <table>
            <thead>
              <tr><th>Entity</th><th>Risk</th><th>Confidence</th></tr>
            </thead>
            <tbody>
              {data.top_risk.map((r) => (
                <tr key={r.entity_id} className="clickable">
                  <td className="mono">
                    <Link href={`/entities?q=${r.entity_id}`} style={{ color: "inherit", textDecoration: "none" }}>
                      {short(r.entity_id, 14)}
                    </Link>
                  </td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="mono" style={{ color: riskColor(r.risk) }}>{r.risk.toFixed(3)}</span>
                      <RiskBar value={r.risk} />
                    </div>
                  </td>
                  <td className="mono dim">{r.confidence?.toFixed(3) ?? "—"}</td>
                </tr>
              ))}
              {!data.top_risk.length && (
                <tr><td colSpan={3} className="dim">run the pipeline: <code>python -m nexus.cli pipeline</code></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ marginTop: 16, display: "flex", gap: 10 }}>
        <button
          className="btn"
          onClick={async () => {
            await post(`${API}/pipeline/run`, { skip_ingest: true }).catch(() => {});
            reload();
          }}
        >
          Run Intelligence Loop
        </button>
        <button className="btn secondary" onClick={reload}>Refresh</button>
      </div>
    </>
  );
}

function Card({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="card">
      <h3>{label}</h3>
      <div className="kpi-value">{value}</div>
      <div className="kpi-sub">{sub}</div>
    </div>
  );
}
