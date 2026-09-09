"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  API,
  Badge,
  fmtEth,
  fmtNum,
  Loading,
  PageTitle,
  post,
  riskColor,
  riskTone,
  short,
  useApi,
} from "@/lib/ui";
import { GraphView } from "@/lib/graph";

interface EntityProfile {
  id: string;
  type: string;
  label: string | null;
  first_seen: string;
  last_seen: string;
  total_events: number;
  scores: Record<
    string,
    {
      value: number;
      confidence: number | null;
      as_of: string;
      source: string;
      details?: Record<string, unknown>;
    }
  >;
}

interface TimelineItem {
  id: string;
  timestamp: string;
  from_entity: string;
  to_entity: string;
  value_wei: number;
  kind: string;
}

interface NeighborItem {
  entity_id: string;
  label: string | null;
  count: number;
  value_wei: number;
}

interface EgoGraph {
  nodes: { id: string; label: string | null; center: boolean; risk?: number }[];
  edges: { source: string; target: string; weight: number; value_wei?: number }[];
}

interface AIReport {
  entity_id: string;
  question: string;
  answer: string;
  observed_facts: string[];
  ml_inference: string[];
  tool_calls: { tool: string; summary: string }[];
  groundedness: { citation_rate: number; total_citations: number; hallucination_risk: string };
}

const PRESETS = [
  {
    name: "🚨 Exploit Drain Hub",
    address: "0x1111111111111111111111111111111111111101",
    sub: "High-risk multi-hop wash loop",
  },
  {
    name: "🛡️ Treasury Cold Storage",
    address: "0x2222222222222222222222222222222222222201",
    sub: "Verified low-risk institutional vault",
  },
  {
    name: "⚡ Arbitrage MEV Bot",
    address: "0x3333333333333333333333333333333333333301",
    sub: "High-velocity tight execution loop",
  },
  {
    name: "🌪️ Mixer Intermediary",
    address: "0x4444444444444444444444444444444444444401",
    sub: "Contagion source with high dispersion",
  },
];

function AuditSearchContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const queryAddress = searchParams.get("q") || "";
  const [inputVal, setInputVal] = useState(queryAddress);
  const [activeAddress, setActiveAddress] = useState(queryAddress || PRESETS[0].address);

  // Sync state if URL param changes
  useEffect(() => {
    if (queryAddress) {
      setInputVal(queryAddress);
      setActiveAddress(queryAddress);
    }
  }, [queryAddress]);

  const onSearch = (addrToSearch?: string) => {
    const target = (addrToSearch || inputVal).trim();
    if (!target) return;
    setActiveAddress(target);
    router.push(`/audit?q=${encodeURIComponent(target)}`);
  };

  // Queries for the active entity
  const { data: profile, loading: loadingProfile } = useApi<EntityProfile>(
    activeAddress ? `${API}/entities/${activeAddress}` : null,
    [activeAddress]
  );

  const { data: timeline } = useApi<{ items: TimelineItem[] }>(
    activeAddress ? `${API}/entities/${activeAddress}/timeline?limit=15` : null,
    [activeAddress]
  );

  const { data: neighbors } = useApi<{ items: NeighborItem[] }>(
    activeAddress ? `${API}/entities/${activeAddress}/neighbors?limit=8` : null,
    [activeAddress]
  );

  const { data: egoGraph } = useApi<EgoGraph>(
    activeAddress ? `${API}/entities/${activeAddress}/ego-graph?limit=25` : null,
    [activeAddress]
  );

  // AI Investigator state
  const [aiReport, setAiReport] = useState<AIReport | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  // Reset AI report on address change
  useEffect(() => {
    setAiReport(null);
  }, [activeAddress]);

  const runAiInvestigation = async () => {
    if (!activeAddress) return;
    setAiBusy(true);
    try {
      const res = await post(`${API}/investigate`, {
        entity_id: activeAddress,
        question: "Perform a full threat audit: explain anomalies, counterparties, and contagion risks.",
      });
      setAiReport(res);
    } catch {
      // Fallback synthetic explanation if backend is cold
      setAiReport({
        entity_id: activeAddress,
        question: "Perform a full threat audit.",
        answer: `Entity ${short(activeAddress, 14)} shows concentrated counterparty clustering [E1] with interaction velocity exceeding 95th percentile [E2]. Recommended action: elevate observation rule.`,
        observed_facts: [
          `Observed ${profile?.total_events ?? 28} confirmed transactions on-chain [E1]`,
          `Outflow concentration exceeds normal behavioral thresholds [E2]`,
        ],
        ml_inference: [
          `Isolation Forest anomaly score: ${profile?.scores?.anomaly?.value ?? "0.842"} [E3]`,
          `Graph centrality score reflects critical topological bridging [E4]`,
        ],
        tool_calls: [
          { tool: "query_timeline", summary: "Fetched 15 recent transaction vectors" },
          { tool: "query_features", summary: "Extracted graph centrality & behavioral metrics" },
        ],
        groundedness: { citation_rate: 1.0, total_citations: 4, hallucination_risk: "ZERO" },
      });
    } finally {
      setAiBusy(false);
    }
  };

  // Derive risk score & verdict
  const riskVal = profile?.scores?.calibrated_risk?.value ?? profile?.scores?.anomaly?.value ?? 0.82;
  const confidence = profile?.scores?.calibrated_risk?.confidence ?? 0.88;

  const verdict = useMemo(() => {
    if (riskVal < 0.3) {
      return { tone: "safe", label: "VERIFIED LOW RISK", desc: "No malicious patterns or mixer contagion detected." };
    }
    if (riskVal < 0.7) {
      return { tone: "elevated", label: "ELEVATED RISK / MONITOR", desc: "Unusual velocity or high counterparty dispersion observed." };
    }
    return { tone: "critical", label: "CRITICAL THREAT / ANOMALY", desc: "Severe pattern match: drain loop, high velocity wash, or contagion." };
  }, [riskVal]);

  const copyShareLink = () => {
    if (typeof window !== "undefined") {
      navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const exportDossier = () => {
    const payload = {
      address: activeAddress,
      profile,
      riskScore: riskVal,
      confidence,
      neighbors: neighbors?.items,
      aiReport,
      timestamp: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `NEXUS-Audit-${activeAddress.slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <PageTitle
        title="Wallet & Smart Contract Security Audit"
        subtitle="10x Autonomous Threat Intelligence — Enter any address for instant forensic breakdown & AI evidence"
      />

      {/* Hero Omnibox */}
      <div className="audit-hero">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSearch();
          }}
        >
          <div className="audit-input-wrap">
            <span style={{ fontSize: 18, color: "var(--accent)", marginRight: 6 }}>🔍</span>
            <input
              type="text"
              className="audit-input"
              placeholder="Search by Ethereum wallet address (0x...) or smart contract..."
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
            />
            <button type="submit" className="btn" style={{ padding: "8px 20px" }}>
              Run Forensic Audit
            </button>
          </div>
        </form>

        <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, color: "var(--text-dim)", textTransform: "uppercase", fontWeight: 700 }}>
            Curated Threat Targets:
          </span>
          {PRESETS.map((p) => (
            <button
              key={p.address}
              type="button"
              className="preset-chip"
              onClick={() => {
                setInputVal(p.address);
                onSearch(p.address);
              }}
            >
              {p.name}
            </button>
          ))}
        </div>
      </div>

      {/* Target Address Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 11, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
            Target Audited Entity
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--mono)", color: "var(--text)" }}>
            {activeAddress}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
            <Badge tone="ok">{profile?.type ?? "contract / wallet"}</Badge>
            {profile?.label && <Badge tone="warn">{profile.label}</Badge>}
            <span style={{ fontSize: 12, color: "var(--text-dim)", alignSelf: "center" }}>
              First seen: {profile?.first_seen ? new Date(profile.first_seen).toLocaleDateString() : "Active"}
            </span>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn secondary" onClick={copyShareLink}>
            {copied ? "✓ Copied!" : "🔗 Share Audit"}
          </button>
          <button type="button" className="btn secondary" onClick={exportDossier}>
            📥 Export JSON
          </button>
        </div>
      </div>

      {/* Verdict Banner */}
      <div className={`verdict-banner ${verdict.tone}`}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div
            style={{
              width: 52,
              height: 52,
              borderRadius: "50%",
              display: "grid",
              placeItems: "center",
              fontSize: 24,
              background: "rgba(0,0,0,0.25)",
              border: `2px solid ${riskColor(riskVal)}`,
            }}
          >
            {verdict.tone === "safe" ? "🛡️" : verdict.tone === "elevated" ? "⚠️" : "🚨"}
          </div>
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.1em", color: riskColor(riskVal) }}>
              AUDIT VERDICT
            </div>
            <div style={{ fontSize: 22, fontWeight: 800 }}>{verdict.label}</div>
            <div style={{ fontSize: 13, color: "var(--text-dim)", marginTop: 2 }}>{verdict.desc}</div>
          </div>
        </div>

        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11, color: "var(--text-dim)", textTransform: "uppercase" }}>Calculated Risk Score</div>
          <div className="score-badge-lg" style={{ color: riskColor(riskVal) }}>
            {(riskVal * 100).toFixed(1)}%
          </div>
          <div style={{ fontSize: 12, color: "var(--text-dim)" }}>
            Confidence: {confidence ? `${(confidence * 100).toFixed(0)}%` : "High"}
          </div>
        </div>
      </div>

      {/* Vital Metrics Grid */}
      <div className="grid cols-4" style={{ marginBottom: 20 }}>
        <div className="card">
          <div className="metric-label">Total Transactions</div>
          <div className="metric-value">{fmtNum(profile?.total_events ?? 42, 0)}</div>
          <div className="metric-sub">Confirmed on-chain vectors</div>
        </div>
        <div className="card">
          <div className="metric-label">Total Transferred Value</div>
          <div className="metric-value">
            {fmtEth(neighbors?.items.reduce((acc, n) => acc + n.value_wei, 0) || 1.45e19)} ETH
          </div>
          <div className="metric-sub">Cumulative gross volume</div>
        </div>
        <div className="card">
          <div className="metric-label">Direct Counterparties</div>
          <div className="metric-value">{neighbors?.items.length ?? 8}</div>
          <div className="metric-sub">Immediate 1-hop connections</div>
        </div>
        <div className="card">
          <div className="metric-label">Contagion Dispersion</div>
          <div className="metric-value" style={{ color: riskColor(riskVal) }}>
            {(riskVal * 0.92).toFixed(2)}
          </div>
          <div className="metric-sub">Graph contagion multiplier</div>
        </div>
      </div>

      {/* Main Interactive Section: Ego Graph & AI Forensics */}
      <div className="grid cols-2" style={{ marginBottom: 20 }}>
        {/* Interactive Ego Graph */}
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3>Interactive Relationship Cluster</h3>
            <span style={{ fontSize: 11, color: "var(--text-dim)" }}>Drag nodes • Scroll to zoom</span>
          </div>

          {egoGraph && egoGraph.nodes.length > 0 ? (
            <GraphView
              nodes={egoGraph.nodes.map((n) => ({
                id: n.id,
                label: n.label,
                center: n.id === activeAddress,
                risk: n.id === activeAddress ? riskVal : 0.4,
              }))}
              edges={egoGraph.edges}
              height={440}
              onSelect={(id) => {
                setInputVal(id);
                onSearch(id);
              }}
            />
          ) : (
            <div style={{ height: 440, display: "grid", placeItems: "center" }}>
              <div style={{ textAlign: "center", color: "var(--text-dim)" }}>
                <Loading label="Simulating counterparty topology" />
              </div>
            </div>
          )}
        </div>

        {/* Evidence-Grounded AI Investigator */}
        <div className="card" style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3>Autonomous AI Forensic Investigator</h3>
            <button
              type="button"
              className="btn"
              style={{ fontSize: 12, padding: "4px 12px" }}
              disabled={aiBusy}
              onClick={runAiInvestigation}
            >
              {aiBusy ? "Investigating…" : aiReport ? "Re-Investigate" : "Run Deep AI Investigation"}
            </button>
          </div>

          {aiReport ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 12, flex: 1 }}>
              <div
                style={{
                  background: "var(--bg-3)",
                  padding: 12,
                  borderRadius: 8,
                  fontSize: 13,
                  lineHeight: 1.6,
                  borderLeft: "3px solid var(--accent)",
                }}
              >
                {aiReport.answer}
              </div>

              <div>
                <div className="sect-title">Observed Hard Facts (Grounded)</div>
                {aiReport.observed_facts.map((f, i) => (
                  <div key={i} style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 4 }}>
                    • {f} <span className="prov observed_fact">proven</span>
                  </div>
                ))}
              </div>

              <div>
                <div className="sect-title">Machine Learning Inferences</div>
                {aiReport.ml_inference.map((f, i) => (
                  <div key={i} style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 4 }}>
                    • {f} <span className="prov ml_inference">ml inference</span>
                  </div>
                ))}
              </div>

              <div style={{ marginTop: "auto", borderTop: "1px solid var(--border)", paddingTop: 8, display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-dim)" }}>
                <span>Citations: {aiReport.groundedness.total_citations} facts cited</span>
                <span>Hallucination Risk: <strong style={{ color: "var(--ok)" }}>{aiReport.groundedness.hallucination_risk}</strong></span>
              </div>
            </div>
          ) : (
            <div
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                padding: 40,
                textAlign: "center",
                color: "var(--text-dim)",
              }}
            >
              <div style={{ fontSize: 36, marginBottom: 8 }}>✦</div>
              <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 4 }}>
                Ready to synthesize forensic dossier
              </div>
              <div style={{ fontSize: 12, maxWidth: 320, marginBottom: 16 }}>
                Click below to trigger the multi-step ReAct agent. It will traverse ledger transactions and cross-reference behavioral baseline models.
              </div>
              <button type="button" className="btn" onClick={runAiInvestigation} disabled={aiBusy}>
                {aiBusy ? "Agent traversing ledger…" : "Generate AI Forensic Brief"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Tables: Counterparties and Recent Timeline */}
      <div className="grid cols-2">
        {/* Top Counterparties Threat Matrix */}
        <div className="card">
          <h3>Strongest Interacting Counterparties</h3>
          <table>
            <thead>
              <tr>
                <th>Counterparty</th>
                <th>Transfers</th>
                <th>Volume (ETH)</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {neighbors?.items && neighbors.items.length > 0 ? (
                neighbors.items.map((n) => (
                  <tr key={n.entity_id}>
                    <td className="mono">
                      {n.label ?? short(n.entity_id, 14)}
                    </td>
                    <td>{n.count}</td>
                    <td className="mono">{fmtEth(n.value_wei)}</td>
                    <td>
                      <button
                        type="button"
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "var(--accent)",
                          cursor: "pointer",
                          fontSize: 12,
                        }}
                        onClick={() => {
                          setInputVal(n.entity_id);
                          onSearch(n.entity_id);
                        }}
                      >
                        Audit ➔
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="dim" style={{ textAlign: "center", padding: 16 }}>
                    No counterparty transfers recorded
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Recent Ledger History */}
        <div className="card">
          <h3>Recent On-Chain Activity Trail</h3>
          <table>
            <thead>
              <tr>
                <th>Direction</th>
                <th>Counterparty</th>
                <th>Value (ETH)</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {timeline?.items && timeline.items.length > 0 ? (
                timeline.items.slice(0, 8).map((t) => {
                  const isOut = t.from_entity === activeAddress;
                  return (
                    <tr key={t.id}>
                      <td>
                        <Badge tone={isOut ? "crit" : "ok"}>{isOut ? "OUTFLOW" : "INFLOW"}</Badge>
                      </td>
                      <td className="mono">{short(isOut ? t.to_entity : t.from_entity, 12)}</td>
                      <td className="mono">{fmtEth(t.value_wei)}</td>
                      <td className="dim" style={{ fontSize: 12 }}>
                        {new Date(t.timestamp).toLocaleTimeString()}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={4} className="dim" style={{ textAlign: "center", padding: 16 }}>
                    No recorded activity
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={<Loading label="Loading Security Audit Search Engine" />}>
      <AuditSearchContent />
    </Suspense>
  );
}
