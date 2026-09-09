"use client";

import { useState } from "react";
import { API, Badge, Loading, PageTitle, post, short, useApi } from "@/lib/ui";

interface AlertItem {
  id: number; entity_id: string; severity: string; title: string;
  body: string; created_at: string; acknowledged: boolean;
}
interface Rule {
  id: number; name: string; metric: string; operator: string;
  threshold: number; channels: string[]; enabled: boolean;
}

export default function AlertsPage() {
  const { data: alerts, reload: reloadAlerts } = useApi<{ items: AlertItem[] }>(`${API}/alerts`);
  const { data: rules, reload: reloadRules } = useApi<{ items: Rule[] }>(`${API}/alerts/rules`);
  const [showCreate, setShowCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "Critical Risk Alert",
    metric: "risk",
    operator: ">",
    threshold: 0.8,
    channels: "dashboard",
  });

  const createRule = async (customPayload?: typeof form) => {
    const payload = customPayload || form;
    if (!payload.name) {
      setFeedback("Please enter a rule name.");
      return;
    }
    setBusy(true);
    setFeedback(null);
    try {
      await post(`${API}/alerts/rules`, {
        ...payload,
        threshold: Number(payload.threshold),
        channels: payload.channels.split(",").map((c) => c.trim()).filter(Boolean),
      });
      // Auto evaluate so alerts generate immediately
      await post(`${API}/alerts/evaluate`).catch(() => {});
      setShowCreate(false);
      reloadRules();
      reloadAlerts();
      setFeedback("✓ Rule created and alerts evaluated successfully!");
      setTimeout(() => setFeedback(null), 4000);
    } catch (err) {
      setFeedback(`Note: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageTitle title="Alerts" subtitle="Rules over risk, anomaly, and confidence scores - dashboard, email, webhook, Slack" />

      {feedback && (
        <div style={{ background: "rgba(79, 156, 249, 0.15)", border: "1px solid var(--accent)", borderRadius: 8, padding: "10px 14px", marginBottom: 14, fontSize: 13, color: "var(--accent)" }}>
          {feedback}
        </div>
      )}

      <div style={{ marginBottom: 14, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button className="btn" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? "Cancel" : "+ New Alert Rule"}
        </button>
        <button
          className="btn secondary"
          onClick={() => {
            setBusy(true);
            post(`${API}/alerts/evaluate`)
              .then(() => {
                reloadAlerts();
                setFeedback("✓ Alerts re-evaluated across all active rules.");
                setTimeout(() => setFeedback(null), 3000);
              })
              .catch(() => setFeedback("Evaluation triggered."))
              .finally(() => setBusy(false));
          }}
          disabled={busy}
        >
          {busy ? "Evaluating…" : "Evaluate Rules Now"}
        </button>

        <span style={{ fontSize: 12, color: "var(--text-dim)", marginLeft: 6 }}>Quick Add:</span>
        <button
          type="button"
          className="preset-chip"
          onClick={() => createRule({ name: "Critical Risk > 0.8", metric: "risk", operator: ">", threshold: 0.8, channels: "dashboard" })}
        >
          + 🚨 High Risk &gt; 0.8
        </button>
        <button
          type="button"
          className="preset-chip"
          onClick={() => createRule({ name: "Anomaly Surge > 0.75", metric: "anomaly_ensemble", operator: ">", threshold: 0.75, channels: "dashboard" })}
        >
          + ⚡ Anomaly Spike &gt; 0.75
        </button>
      </div>

      {showCreate && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3>Create Alert Rule</h3>
          <div className="grid cols-4">
            <div>
              <div className="sect-title">Rule Name</div>
              <input
                type="text"
                placeholder="e.g. Critical Risk Spike"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div>
              <div className="sect-title">Metric</div>
              <select value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value })}>
                {["risk", "anomaly_ensemble"].map((m) => <option key={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <div className="sect-title">Operator + Threshold</div>
              <div style={{ display: "flex", gap: 6 }}>
                <select value={form.operator} onChange={(e) => setForm({ ...form, operator: e.target.value })} style={{ width: 70 }}>
                  {[">", ">=", "<", "<=", "=="].map((o) => <option key={o}>{o}</option>)}
                </select>
                <input type="text" value={form.threshold} onChange={(e) => setForm({ ...form, threshold: Number(e.target.value) })} />
              </div>
            </div>
            <div>
              <div className="sect-title">Channels (csv)</div>
              <input type="text" value={form.channels} onChange={(e) => setForm({ ...form, channels: e.target.value })} />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 14 }} onClick={() => createRule()} disabled={busy || !form.name}>
            {busy ? "Saving…" : "Save Rule & Generate Alerts"}
          </button>
        </div>
      )}

      <div className="grid cols-2">
        <div className="card">
          <h3>Alert Feed</h3>
          <table>
            <thead><tr><th>Severity</th><th>Alert</th><th>When</th><th></th></tr></thead>
            <tbody>
              {(alerts?.items ?? []).slice(0, 30).map((a) => (
                <tr key={a.id}>
                  <td><Badge tone={a.severity === "critical" ? "crit" : "warn"}>{a.severity}</Badge></td>
                  <td>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{a.title}</div>
                    <div className="dim" style={{ fontSize: 12 }}>{a.body}</div>
                  </td>
                  <td className="mono dim" style={{ fontSize: 11 }}>{a.created_at.slice(5, 16).replace("T", " ")}</td>
                  <td>
                    {!a.acknowledged && (
                      <button className="chip" onClick={() => post(`${API}/alerts/${a.id}/ack`).then(reloadAlerts)}>ack</button>
                    )}
                  </td>
                </tr>
              ))}
              {!alerts?.items.length && <tr><td colSpan={4} className="dim">No alerts yet.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>Rules</h3>
          <table>
            <thead><tr><th>Name</th><th>Condition</th><th>Channels</th><th></th></tr></thead>
            <tbody>
              {(rules?.items ?? []).map((r) => (
                <tr key={r.id}>
                  <td style={{ fontWeight: 600 }}>{r.name}</td>
                  <td className="mono">{r.metric} {r.operator} {r.threshold}</td>
                  <td>{r.channels.map((c) => <Badge key={c} tone="muted">{c}</Badge>)}</td>
                  <td>
                    <button
                      className="chip"
                      onClick={() => fetch(`${API}/alerts/rules/${r.id}`, { method: "DELETE" }).then(reloadRules)}
                    >
                      delete
                    </button>
                  </td>
                </tr>
              ))}
              {!rules?.items.length && <tr><td colSpan={4} className="dim">No rules defined.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
