"use client";

import { useState } from "react";
import { API, Badge, Loading, PageTitle, post, short, useApi } from "@/lib/ui";

interface Automation {
  id: number; name: string; trigger_metric: string; trigger_operator: string;
  trigger_threshold: number; steps: { action: string }[]; requires_approval: boolean;
}
interface Run {
  id: number; automation_id: number; entity_id: string; status: string;
  step_results: { action: string; ok: boolean; detail?: string }[];
  created_at: string;
}

export default function AutomationsPage() {
  const { data: autos, reload: reloadAutos } = useApi<{ items: Automation[] }>(`${API}/automations`);
  const { data: runs, reload: reloadRuns } = useApi<{ items: Run[] }>(`${API}/workflow-runs`);
  const { data: entities } = useApi<{ items: { id: string }[] }>(`${API}/entities?limit=50`);
  const [entityId, setEntityId] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (autoId: number) => {
    const eid = entityId || entities?.items?.[0]?.id;
    if (!eid) return;
    setBusy(true);
    try {
      await post(`${API}/automations/${autoId}/run`, { entity_id: eid });
      reloadRuns();
    } finally {
      setBusy(false);
    }
  };

  const decide = async (runId: number, approve: boolean) => {
    await post(`${API}/workflow-runs/${runId}/approve?approve=${approve}`);
    reloadRuns();
  };

  return (
    <>
      <PageTitle
        title="Automations"
        subtitle="Intelligence-triggered workflows with human-in-the-loop approval gates"
      />
      <div className="sect">
        <div className="sect-title">run against entity</div>
        <select value={entityId} onChange={(e) => setEntityId(e.target.value)} style={{ maxWidth: 420 }}>
          <option value="">— first entity —</option>
          {entities?.items.map((e) => <option key={e.id} value={e.id}>{short(e.id, 20)}</option>)}
        </select>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>Workflows</h3>
          <table>
            <thead><tr><th>Name</th><th>Trigger</th><th>Steps</th><th></th></tr></thead>
            <tbody>
              {(autos?.items ?? []).map((a) => (
                <tr key={a.id}>
                  <td style={{ fontWeight: 600 }}>
                    {a.name}
                    {a.requires_approval && <Badge tone="info">approval</Badge>}
                  </td>
                  <td className="mono dim">{a.trigger_metric} {a.trigger_operator} {a.trigger_threshold}</td>
                  <td className="dim" style={{ fontSize: 11 }}>{a.steps.map((s) => s.action).join(" → ")}</td>
                  <td>
                    <button className="chip" disabled={busy} onClick={() => run(a.id)}>run</button>
                  </td>
                </tr>
              ))}
              {!autos?.items.length && (
                <tr>
                  <td colSpan={4} className="dim">
                    Seed one via <code>python -m nexus.cli automation seed</code>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>Workflow Runs</h3>
          <table>
            <thead><tr><th>Run</th><th>Entity</th><th>Status</th><th>Steps</th><th></th></tr></thead>
            <tbody>
              {(runs?.items ?? []).slice(0, 15).map((r) => (
                <tr key={r.id}>
                  <td className="mono dim">#{r.id}</td>
                  <td className="mono">{short(r.entity_id, 10)}</td>
                  <td>
                    <Badge tone={
                      r.status === "completed" ? "ok"
                      : r.status === "awaiting_approval" ? "warn"
                      : r.status === "rejected" ? "crit" : "info"
                    }>{r.status.replace("_", " ")}</Badge>
                  </td>
                  <td className="dim" style={{ fontSize: 11 }}>
                    {(r.step_results ?? []).map((s) => (s.ok ? "✓" : "✗")).join(" ")}
                  </td>
                  <td>
                    {r.status === "awaiting_approval" && (
                      <>
                        <button className="chip" onClick={() => decide(r.id, true)}>approve</button>{" "}
                        <button className="chip" onClick={() => decide(r.id, false)}>reject</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {!runs?.items.length && <tr><td colSpan={5} className="dim">No runs yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
