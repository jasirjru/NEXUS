"use client";

import { API, Badge, Loading, PageTitle, useApi } from "@/lib/ui";
import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

interface EvalRun {
  id: number; name: string; kind: string; metrics: Record<string, unknown>; created_at: string;
}

export default function ModelsPage() {
  const { data } = useApi<{ items: EvalRun[] }>(`${API}/evaluations`);
  const ablations = data?.items?.filter((r) => r.kind === "ablation") ?? [];
  const anomaly = data?.items?.filter((r) => r.kind === "anomaly") ?? [];
  const latestAblation = ablations[0]?.metrics ?? null;

  const ablationChart = latestAblation
    ? Object.entries(latestAblation).map(([stage, m]) => ({
        stage: stage.replace("baseline_", "base/").replace("plus_", "+"),
        roc_auc: (m as Record<string, number>).roc_auc ?? 0,
        pr_auc: (m as Record<string, number>).pr_auc ?? 0,
      }))
    : [];

  const m = (anomaly[0]?.metrics ?? {}) as Record<string, number | string>;

  return (
    <>
      <PageTitle
        title="Model Performance"
        subtitle="Only measured results - every number comes from an actual evaluation run"
      />
      <div className="grid cols-4">
        {[
          ["ROC-AUC", m.roc_auc],
          ["PR-AUC", m.pr_auc],
          ["F1 (best threshold)", m.f1],
          ["False-positive rate", m.false_positive_rate],
        ].map(([label, v]) => (
          <div className="card" key={label as string}>
            <h3>{label as string}</h3>
            <div className="kpi-value">{typeof v === "number" ? v.toFixed(3) : "—"}</div>
            <div className="kpi-sub">{anomaly[0] ? `run ${new Date(anomaly[0].created_at).toLocaleString()}` : "no runs yet"}</div>
          </div>
        ))}
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Ablation Study (incremental component value)</h3>
          {ablationChart.length ? (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={ablationChart}>
                <CartesianGrid stroke="#1e2a3d" strokeDasharray="3 3" />
                <XAxis dataKey="stage" tick={{ fill: "#7d8ba1", fontSize: 11 }} />
                <YAxis domain={[0, 1]} tick={{ fill: "#7d8ba1", fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ background: "#0f1520", border: "1px solid #1e2a3d", borderRadius: 8 }}
                  labelStyle={{ color: "#d7e1ee" }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="roc_auc" fill="#4f9cf9" radius={[3, 3, 0, 0]} />
                <Bar dataKey="pr_auc" fill="#7c6cf9" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="dim">Run the pipeline to generate ablations.</div>
          )}
        </div>

        <div className="card">
          <h3>Evaluation History</h3>
          <table>
            <thead><tr><th>Run</th><th>Kind</th><th>Key metrics</th><th>When</th></tr></thead>
            <tbody>
              {(data?.items ?? []).slice(0, 12).map((r) => {
                const mm = r.metrics as Record<string, number | string>;
                const key = mm.f1 !== undefined ? `f1=${Number(mm.f1).toFixed(3)}`
                  : mm.roc_auc !== undefined ? `auc=${Number(mm.roc_auc).toFixed(3)}` : "";
                return (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    <td><Badge tone="muted">{r.kind}</Badge></td>
                    <td className="mono dim">{key}</td>
                    <td className="mono dim" style={{ fontSize: 11 }}>{r.created_at.slice(5, 16).replace("T", " ")}</td>
                  </tr>
                );
              })}
              {!data?.items.length && <tr><td colSpan={4} className="dim">No evaluation runs yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
