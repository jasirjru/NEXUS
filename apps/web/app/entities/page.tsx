"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  API, Badge, Loading, PageTitle, fmtEth, fmtNum, post, RiskBar, riskTone, short, useApi,
} from "@/lib/ui";
import { GraphView } from "@/lib/graph";

interface EntityRow { id: string; type: string; label: string | null }
interface EntityProfile {
  id: string; type: string; label: string | null;
  first_seen: string | null; last_seen: string | null; total_events: number;
  scores: Record<string, { value: number; confidence: number | null; as_of: string; source: string }>;
}
interface Neighbor { entity_id: string; count: number; value_wei: number; label: string | null }
interface TimelineItem { id: string; type: string; timestamp: string; from_entity: string; to_entity: string; value_wei: number }
interface EgoGraph { nodes: { id: string; label: string | null; center: boolean }[]; edges: { source: string; target: string; weight: number }[] }
interface Investigation {
  answer: string; observed_facts: string[]; ml_inference: string[];
  groundedness: { citation_rate: number; hallucination_risk: string };
  tool_calls: { tool: string; summary: string }[];
}

function EntitiesInner() {
  const params = useSearchParams();
  const initialQ = params.get("q") ?? "";
  const [q, setQ] = useState(initialQ);
  const { data: list } = useApi<{ items: EntityRow[] }>(
    `${API}/entities?limit=25${q ? `&q=${encodeURIComponent(q)}` : ""}`, [q],
  );
  const [selected, setSelected] = useState<string | null>(initialQ || null);

  useEffect(() => {
    if (!selected && list?.items?.length && !q) setSelected(list.items[0].id);
  }, [list, selected, q]);

  return (
    <>
      <PageTitle title="Entity Investigation" subtitle="Profile, behavior, relationships, and AI analysis" />
      <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
        <input
          type="text"
          placeholder="Search address or label (e.g. drainer_0, exchange_1, 0x…)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
        {list?.items?.map((e) => (
          <button
            key={e.id}
            className={`chip ${selected === e.id ? "active" : ""}`}
            onClick={() => setSelected(e.id)}
          >
            {e.label ?? short(e.id, 12)}
            <span className="dim" style={{ marginLeft: 6, fontSize: 10 }}>{e.type}</span>
          </button>
        ))}
      </div>
      {selected && <EntityDetail entityId={selected} />}
    </>
  );
}

function EntityDetail({ entityId }: { entityId: string }) {
  const { data: profile } = useApi<EntityProfile>(`${API}/entities/${entityId}`, [entityId]);
  const { data: neighbors } = useApi<{ items: Neighbor[] }>(`${API}/entities/${entityId}/neighbors`, [entityId]);
  const { data: timeline } = useApi<{ items: TimelineItem[] }>(`${API}/entities/${entityId}/timeline?limit=30`, [entityId]);
  const { data: ego } = useApi<EgoGraph>(`${API}/entities/${entityId}/ego-graph`, [entityId]);
  const { data: feats } = useApi<{ features: Record<string, number> }>(`${API}/entities/${entityId}/features`, [entityId]);

  const [question, setQuestion] = useState("Why is this wallet suspicious?");
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [asking, setAsking] = useState(false);

  const ask = async () => {
    setAsking(true);
    try {
      setInvestigation(await post(`${API}/investigate`, { entity_id: entityId, question }));
    } catch {
      setInvestigation(null);
    } finally {
      setAsking(false);
    }
  };

  if (!profile) return <Loading />;

  const risk = profile.scores.risk?.value;
  const anomaly = profile.scores.anomaly_ensemble?.value;

  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr" }}>
      {/* header */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
          <div>
            <div className="mono" style={{ fontSize: 15, fontWeight: 700 }}>{profile.id}</div>
            <div className="dim" style={{ marginTop: 4, fontSize: 12 }}>
              {profile.label ?? "unlabeled"} · {profile.type} · {profile.total_events} events
              {profile.first_seen && ` · first seen ${profile.first_seen.slice(0, 10)}`}
            </div>
          </div>
          <div style={{ display: "flex", gap: 20 }}>
            {risk !== undefined && (
              <div style={{ textAlign: "center" }}>
                <div className="sect-title">risk</div>
                <div style={{ fontSize: 22, fontWeight: 800 }}>{risk.toFixed(3)}</div>
                <div className="dim" style={{ fontSize: 11 }}>
                  conf {profile.scores.risk.confidence?.toFixed(3) ?? "—"}
                </div>
              </div>
            )}
            {anomaly !== undefined && (
              <div style={{ textAlign: "center" }}>
                <div className="sect-title">anomaly</div>
                <div style={{ fontSize: 22, fontWeight: 800 }}>{anomaly.toFixed(3)}</div>
                <Badge tone={riskTone(anomaly)}>{profile.scores.anomaly_ensemble.source}</Badge>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        {/* behavioral profile */}
        <div className="card">
          <h3>Behavioral Profile</h3>
          <table>
            <tbody>
              {feats && Object.entries(feats.features)
                .filter(([, v]) => v !== 0)
                .slice(0, 12)
                .map(([k, v]) => (
                  <tr key={k}>
                    <td className="dim">{k.replace(/_/g, " ")}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{fmtNum(v)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>

        {/* graph */}
        <div className="card">
          <h3>Relationship Graph</h3>
          {ego && (
            <GraphView
              nodes={ego.nodes}
              edges={ego.edges}
              height={340}
              onSelect={(id) => (window.location.href = `/entities?q=${id}`)}
            />
          )}
        </div>

        {/* neighbors */}
        <div className="card">
          <h3>Related Entities</h3>
          <table>
            <thead><tr><th>Entity</th><th>Interactions</th><th>Value (ETH)</th></tr></thead>
            <tbody>
              {neighbors?.items?.slice(0, 10).map((n) => (
                <tr key={n.entity_id} className="clickable" onClick={() => window.location.assign(`/entities?q=${n.entity_id}`)}>
                  <td className="mono">{n.label ?? short(n.entity_id, 14)}</td>
                  <td className="mono">{n.count}</td>
                  <td className="mono">{fmtEth(n.value_wei)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* timeline */}
        <div className="card">
          <h3>Transaction Timeline (recent)</h3>
          <table>
            <thead><tr><th>When</th><th>Type</th><th>Counterparty</th><th>Value</th></tr></thead>
            <tbody>
              {timeline?.items?.slice(0, 12).map((t) => (
                <tr key={t.id}>
                  <td className="mono dim">{t.timestamp.slice(0, 16).replace("T", " ")}</td>
                  <td><Badge tone="muted">{t.type}</Badge></td>
                  <td className="mono">{short(t.from_entity === entityId ? t.to_entity : t.from_entity, 12)}</td>
                  <td className="mono">{fmtEth(t.value_wei)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* AI investigator */}
      <div className="card" style={{ marginTop: 16 }}>
        <h3>AI Investigator</h3>
        <div style={{ display: "flex", gap: 10 }}>
          <input type="text" value={question} onChange={(e) => setQuestion(e.target.value)} />
          <button className="btn" onClick={ask} disabled={asking}>
            {asking ? "Investigating…" : "Ask"}
          </button>
        </div>
        <div className="chips">
          {[
            "Why is this wallet suspicious?",
            "What changed in the last 24 hours?",
            "Show related entities.",
            "Compare this wallet with its historical behavior.",
          ].map((preset) => (
            <button key={preset} className="chip" onClick={() => setQuestion(preset)}>{preset}</button>
          ))}
        </div>
        {investigation && (
          <div style={{ marginTop: 8 }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
              {investigation.tool_calls.map((tc, i) => (
                <Badge key={i} tone="info">{tc.tool}</Badge>
              ))}
              <Badge tone={investigation.groundedness.hallucination_risk === "low" ? "ok" : "crit"}>
                groundedness: {Math.round(investigation.groundedness.citation_rate * 100)}%
              </Badge>
            </div>
            <div className="answer-block">{investigation.answer}</div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function EntitiesPage() {
  return (
    <Suspense fallback={<Loading />}>
      <EntitiesInner />
    </Suspense>
  );
}
