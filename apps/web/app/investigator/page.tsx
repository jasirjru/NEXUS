"use client";

import { useState } from "react";
import { API, Badge, Loading, PageTitle, post, short, useApi } from "@/lib/ui";

interface Report {
  entity_id: string;
  question: string;
  answer: string;
  observed_facts: string[];
  ml_inference: string[];
  tool_calls: { tool: string; summary: string }[];
  groundedness: { citation_rate: number; total_citations: number; hallucination_risk: string };
}

export default function InvestigatorPage() {
  const { data: entities } = useApi<{ items: { id: string; label: string | null }[] }>(
    `${API}/entities?limit=30`,
  );
  const [entityId, setEntityId] = useState("");
  const [question, setQuestion] = useState("Why is this entity unusual?");
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!entityId) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await post(`${API}/investigate`, { entity_id: entityId, question }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageTitle
        title="AI Investigator"
        subtitle="Evidence-grounded investigation - the LLM cites collected evidence and never manufactures blockchain facts"
      />
      <div className="grid cols-2">
        <div className="card">
          <h3>New Investigation</h3>
          <div className="sect-title">entity</div>
          <select value={entityId} onChange={(e) => setEntityId(e.target.value)}>
            <option value="">— select entity —</option>
            {entities?.items.map((e) => (
              <option key={e.id} value={e.id}>{e.label ?? short(e.id, 18)}</option>
            ))}
          </select>
          <div className="sect-title" style={{ marginTop: 12 }}>question</div>
          <input type="text" value={question} onChange={(e) => setQuestion(e.target.value)} />
          <div className="chips">
            {[
              "Why is this entity unusual?",
              "What happened immediately before the anomaly?",
              "Which entities are related?",
              "What historical behavior differs from the current behavior?",
              "What information is still unknown?",
            ].map((preset) => (
              <button key={preset} className="chip" onClick={() => setQuestion(preset)}>{preset}</button>
            ))}
          </div>
          <button className="btn" onClick={run} disabled={!entityId || busy} style={{ marginTop: 8 }}>
            {busy ? "Investigating…" : "Investigate"}
          </button>
          {error && <div style={{ color: "var(--crit)", marginTop: 10, fontSize: 12 }}>{error}</div>}
        </div>

        <div className="card">
          <h3>Report</h3>
          {!report && !busy && <div className="dim">Select an entity and run an investigation.</div>}
          {busy && <Loading label="gathering evidence + analyzing" />}
          {report && (
            <>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                {report.tool_calls.map((tc, i) => <Badge key={i} tone="info">{tc.tool}</Badge>)}
                <Badge tone={report.groundedness.hallucination_risk === "low" ? "ok" : "crit"}>
                  {report.groundedness.total_citations} citations ·{" "}
                  {Math.round(report.groundedness.citation_rate * 100)}% of factual lines
                </Badge>
              </div>
              <div className="answer-block">{report.answer}</div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
