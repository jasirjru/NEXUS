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
  const [form, setForm] = useState({ name: "", metric: "risk", operator: ">", threshold: 0.8, channels: "dashboard" });

  const createRule = async () => {
    await post(`${API}/alerts/rules`, {
      ...form,
      threshold: Number(form.threshold),
      channels: form.channels.split(",").map((c) => c.trim()).filter(Boolean),
    });
    setShowCreate(false);
    reloadRules();
  };

  return (
    <>
      <PageTitle title="Alerts" subtitle="Rules over risk, anomaly, and confidence scores - dashboard, email, webhook, Slack" />
      <div style={{ marginBottom: 14 }}>
        <button className="btn" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? "Cancel" : "+ New Alert Rule"}
        </button>
        <button className="btn secondary" style={{ marginLeft: 8 }} onClick={() => post(`${API}/alerts/evaluate`).then(reloadAlerts)}>
          Evaluate Now
        </button>
      </div>

      {showCreate && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3>Create Rule</h3>
          <div className="grid cols-4">
            <div>
              <div className="sect-title">name</div>
              <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <div className="sect-title">metric</div>
              <select value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value })}>
                {["risk", "anomaly_ensemble"].map((m) => <option key={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <div className="sect-title">operator + threshold</div>
              <div style={{ display: "flex", gap: 6 }}>
                <select value={form.operator} onChange={(e) => setForm({ ...form, operator: e.target.value })} style={{ width: 70 }}>
                  {[">", ">=", "<", "<=", "=="].map((o) => <option key={o}>{o}</option>)}
                </select>
                <input type="text" value={form.threshold} onChange={(e) => setForm({ ...form, threshold: Number(e.target.value) })} />
              </div>
            </div>
            <div>
              <div className="sect-title">channels (csv)</div>
              <input type="text" value={form.channels} onChange={(e) => setForm({ ...form, channels: e.target.value })} />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 12 }} onClick={createRule} disabled={!form.name}>Create</button>
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
