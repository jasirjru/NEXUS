"use client";

import { API, Badge, Loading, PageTitle, RiskBar, riskTone, short, useApi } from "@/lib/ui";
import { useState } from "react";

interface ScoreRow {
  entity_id: string;
  value: number;
  details: Record<string, number>;
}

export default function AnomaliesPage() {
  const { data: ov } = useApi<{ active_anomalies: number }>(`${API}/overview`);
  // Latest anomaly scores via entity list + scores; we use the overview + drift endpoints
  const { data, loading } = useApi<{ items: { entity_id: string; value: number; details: Record<string, number> }[] }>(
    `${API}/anomaly-scores`,
  );
  if (loading) return <Loading />;
  return (
    <>
      <PageTitle
        title="Anomaly Detection"
        subtitle={`${ov?.active_anomalies ?? "—"} entities above 0.8 (ensemble of robust-zscore, isolation forest, LOF, autoencoder)`}
      />
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Entity</th><th>Ensemble</th><th>zscore</th><th>iforest</th><th>lof</th><th>autoencoder</th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).slice(0, 40).map((r) => (
              <tr key={r.entity_id} className="clickable" onClick={() => window.location.assign(`/entities?q=${r.entity_id}`)}>
                <td className="mono">{short(r.entity_id, 16)}</td>
                <td>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span className="mono">{r.value.toFixed(3)}</span>
                    <RiskBar value={r.value} />
                  </div>
                </td>
                <td className="mono dim">{(r.details?.robust_zscore ?? 0).toFixed(2)}</td>
                <td className="mono dim">{(r.details?.iforest ?? 0).toFixed(2)}</td>
                <td className="mono dim">{(r.details?.lof ?? 0).toFixed(2)}</td>
                <td className="mono dim">{(r.details?.autoencoder ?? 0).toFixed(2)}</td>
              </tr>
            ))}
            {!data?.items?.length && (
              <tr>
                <td colSpan={6} className="dim" style={{ textAlign: "center", padding: 24 }}>
                  No active anomalies above threshold. Trigger intelligence loop to score latest events.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
