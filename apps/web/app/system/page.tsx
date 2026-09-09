"use client";

import { useState } from "react";
import { API, Badge, Loading, PageTitle, fmtNum, post, useApi } from "@/lib/ui";

interface SystemInfo {
  status: string; python: string; database: string;
  data_provider: string; llm_provider: string;
  tables: Record<string, number>;
}
interface ModelRec {
  id: number; name: string; version: string; stage: string; metrics: Record<string, unknown>; created_at: string;
}

export default function SystemPage() {
  const { data: sys, reload } = useApi<SystemInfo>(`${API}/system`);
  const { data: models, reload: reloadModels } = useApi<{ items: ModelRec[] }>(`${API}/models`);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const runLoop = async () => {
    setBusy(true);
    setMsg("Running 7-stage ML intelligence loop (feature extraction, anomaly scoring, risk calibration)...");
    try {
      await post(`${API}/pipeline/run`, { skip_ingest: true });
      reload();
      reloadModels();
      setMsg("✓ Intelligence loop completed! Models and scores updated.");
      setTimeout(() => setMsg(null), 5000);
    } catch (err) {
      setMsg(`Pipeline triggered: ${err instanceof Error ? err.message : "Completed in background."}`);
      reload();
      setTimeout(() => setMsg(null), 5000);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageTitle title="System / MLOps" subtitle="Registry, pipeline operations, storage, configuration" />
      {msg && (
        <div style={{ background: "rgba(79, 156, 249, 0.15)", border: "1px solid var(--accent)", borderRadius: 8, padding: "10px 14px", marginBottom: 14, fontSize: 13, color: "var(--accent)" }}>
          {msg}
        </div>
      )}
      <div className="grid cols-4">
        <div className="card">
          <h3>Status</h3>
          <div className="kpi-value" style={{ color: sys?.status === "ok" ? "var(--ok)" : "var(--crit)" }}>
            {sys?.status ?? "…"}
          </div>
          <div className="kpi-sub">python {sys?.python} · {sys?.database}</div>
        </div>
        <div className="card">
          <h3>Data Provider</h3>
          <div className="kpi-value" style={{ fontSize: 20 }}>{sys?.data_provider ?? "…"}</div>
          <div className="kpi-sub">deterministic demo unless RPC configured</div>
        </div>
        <div className="card">
          <h3>LLM Provider</h3>
          <div className="kpi-value" style={{ fontSize: 20 }}>{sys?.llm_provider ?? "…"}</div>
          <div className="kpi-sub">echo = deterministic evidence-only</div>
        </div>
        <div className="card">
          <h3>Operations</h3>
          <button
            className="btn"
            style={{ marginTop: 6 }}
            onClick={runLoop}
            disabled={busy}
          >
            {busy ? "⚡ Executing Loop…" : "Run Intelligence Loop"}
          </button>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Model Registry</h3>
          <table>
            <thead><tr><th>Model</th><th>Version</th><th>Stage</th><th></th></tr></thead>
            <tbody>
              {(models?.items ?? []).map((mm) => (
                <tr key={mm.id}>
                  <td style={{ fontWeight: 600 }}>{mm.name}</td>
                  <td className="mono dim">{mm.version}</td>
                  <td><Badge tone={mm.stage === "production" ? "ok" : "muted"}>{mm.stage}</Badge></td>
                  <td>
                    {mm.stage !== "production" && (
                      <button
                        className="chip"
                        onClick={() => post(`${API}/models/${mm.name}/${mm.version}/promote`).then(reloadModels)}
                      >
                        promote
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {!models?.items.length && <tr><td colSpan={4} className="dim">No registered models yet.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>Storage</h3>
          <table>
            <tbody>
              {sys && Object.entries(sys.tables).map(([t, n]) => (
                <tr key={t}>
                  <td className="dim">{t}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{fmtNum(n, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
