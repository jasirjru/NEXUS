"use client";

import { API, Loading, PageTitle, RiskBar, short, useApi, riskColor } from "@/lib/ui";

export default function RiskPage() {
  const { data } = useApi<{ top_risk: { entity_id: string; risk: number; confidence: number | null }[]; risk_distribution: Record<string, number> }>(`${API}/overview`);
  const items = data?.top_risk ?? [];
  return (
    <>
      <PageTitle title="Risk Monitoring" subtitle="Calibrated risk probabilities with confidence - learned weights, not hand-tuned" />
      <div className="grid cols-2">
        <div className="card">
          <h3>Highest-Risk Entities</h3>
          <table>
            <thead><tr><th>Entity</th><th>Risk</th><th>Confidence</th><th>Assessment</th></tr></thead>
            <tbody>
              {items.map((r) => {
                const highConf = (r.confidence ?? 0) >= 0.6;
                const tone = r.risk >= 0.5 && highConf ? "crit" : r.risk >= 0.5 ? "warn" : "ok";
                const label = r.risk >= 0.5
                  ? highConf ? "HIGH RISK · HIGH CONFIDENCE" : "HIGH RISK · LOW CONFIDENCE"
                  : highConf ? "benign (confirmed)" : "benign (uncertain)";
                return (
                  <tr key={r.entity_id} className="clickable" onClick={() => window.location.assign(`/entities?q=${r.entity_id}`)}>
                    <td className="mono">{short(r.entity_id, 14)}</td>
                    <td>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <span className="mono" style={{ color: riskColor(r.risk) }}>{r.risk.toFixed(3)}</span>
                        <RiskBar value={r.risk} />
                      </div>
                    </td>
                    <td className="mono dim">{r.confidence?.toFixed(3) ?? "—"}</td>
                    <td><span className={`badge ${tone}`} style={{ fontSize: 10 }}>{label}</span></td>
                  </tr>
                );
              })}
              {!items.length && <tr><td colSpan={4} className="dim">No risk scores yet — run the pipeline.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>About the Risk Engine</h3>
          <p className="dim" style={{ lineHeight: 1.7, fontSize: 13 }}>
            Risk probabilities are produced by a meta-model (logistic regression with
            isotonic/sigmoid calibration) over anomaly, behavioral, and graph signals.
            Weights are <b>learned from labeled outcomes</b>, never hand-picked. When no
            labels exist, the engine falls back to unsupervised mode and marks confidence
            accordingly — the UI always distinguishes calibrated from uncalibrated output.
          </p>
        </div>
      </div>
    </>
  );
}
