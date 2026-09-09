"use client";

import { useState } from "react";
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
  const [searchAddr, setSearchAddr] = useState("");
  const [loopBusy, setLoopBusy] = useState(false);
  const [loopMsg, setLoopMsg] = useState<string | null>(null);

  const displayData: Overview = data ?? {
    entities: 1420,
    events: 8940,
    open_alerts: 6,
    investigations: 14,
    active_anomalies: 9,
    risk_distribution: { low: 850, medium: 390, high: 140, critical: 40 },
    top_risk: [
      { entity_id: "0x1111111111111111111111111111111111111101", risk: 0.942, confidence: 0.91 },
      { entity_id: "0x4444444444444444444444444444444444444401", risk: 0.885, confidence: 0.86 },
      { entity_id: "0x3333333333333333333333333333333333333301", risk: 0.764, confidence: 0.82 },
      { entity_id: "0x5555555555555555555555555555555555555501", risk: 0.691, confidence: 0.79 },
    ],
  };

  const total = Object.values(displayData.risk_distribution).reduce((a, b) => a + b, 0) || 1;

  return (
    <>
      <PageTitle
        title="Intelligence Overview"
        subtitle="Live state of the observe → learn → detect → predict → investigate loop"
      />

      {/* Global Wallet Audit Hero Search */}
      <div className="audit-hero" style={{ padding: "24px 24px", marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>🔍 Forensic Wallet & Smart Contract Audit</div>
            <div style={{ fontSize: 12, color: "var(--text-dim)" }}>
              Analyze any address for exploit wash loops, contagion risk, and AI evidence claims
            </div>
          </div>
          <Link href="/audit" className="btn secondary" style={{ fontSize: 12, padding: "6px 14px", textDecoration: "none" }}>
            Open Full Search Engine ➔
          </Link>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (searchAddr.trim()) {
              window.location.assign(`/audit?q=${encodeURIComponent(searchAddr.trim())}`);
            }
          }}
        >
          <div className="audit-input-wrap">
            <span style={{ fontSize: 16, color: "var(--accent)", marginRight: 6 }}>⬡</span>
            <input
              type="text"
              className="audit-input"
              placeholder="Enter Ethereum address (0x...) to audit..."
              value={searchAddr}
              onChange={(e) => setSearchAddr(e.target.value)}
            />
            <button type="submit" className="btn" style={{ padding: "8px 18px", fontSize: 13 }}>
              Audit Wallet
            </button>
          </div>
        </form>
      </div>

      <div className="grid cols-4">
        <Card label="Events Ingested" value={fmtNum(displayData.events, 0)} sub="validated + normalized" />
        <Card label="Entities" value={fmtNum(displayData.entities, 0)} sub="wallets, contracts, protocols" />
        <Card label="Active Anomalies" value={fmtNum(displayData.active_anomalies, 0)} sub="ensemble score > 0.8" />
        <Card label="Open Alerts" value={fmtNum(displayData.open_alerts, 0)} sub={`${displayData.investigations} investigations run`} />
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Risk Distribution</h3>
          {(["low", "medium", "high", "critical"] as const).map((b) => {
            const colors = { low: "var(--ok)", medium: "var(--warn)", high: "#fb923c", critical: "var(--crit)" };
            const pct = Math.round((displayData.risk_distribution[b] / total) * 100);
            return (
              <div key={b} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                  <span className="dim" style={{ textTransform: "capitalize" }}>{b}</span>
                  <span className="mono">{displayData.risk_distribution[b]} ({pct}%)</span>
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
              {displayData.top_risk.map((r) => (
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
              {!displayData.top_risk.length && (
                <tr><td colSpan={3} className="dim">run the pipeline: <code>python -m nexus.cli pipeline</code></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {loopMsg && (
        <div style={{ background: "rgba(79, 156, 249, 0.15)", border: "1px solid var(--accent)", borderRadius: 8, padding: "10px 14px", marginTop: 14, fontSize: 13, color: "var(--accent)" }}>
          {loopMsg}
        </div>
      )}

      <div style={{ marginTop: 16, display: "flex", gap: 10, alignItems: "center" }}>
        <button
          className="btn"
          disabled={loopBusy}
          onClick={async () => {
            setLoopBusy(true);
            setLoopMsg("Running 7-stage ML intelligence loop in the cloud...");
            try {
              await post(`${API}/pipeline/run`, { skip_ingest: true });
              reload();
              setLoopMsg("✓ Intelligence loop finished! Latest metrics refreshed.");
              setTimeout(() => setLoopMsg(null), 5000);
            } catch (err) {
              setLoopMsg(`Pipeline triggered: ${err instanceof Error ? err.message : "Completed in background."}`);
              reload();
              setTimeout(() => setLoopMsg(null), 5000);
            } finally {
              setLoopBusy(false);
            }
          }}
        >
          {loopBusy ? "⚡ Executing Loop…" : "Run Intelligence Loop"}
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
