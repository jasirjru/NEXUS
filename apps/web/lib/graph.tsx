"use client";

/** Force-directed interactive graph visualizer with spring physics simulation,
 * node dragging, pan/zoom canvas controls, and risk-weighted visual styling. */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { short } from "@/lib/ui";

export interface GNode {
  id: string;
  label?: string | null;
  degree?: number;
  center?: boolean;
  risk?: number;
}

export interface GEdge {
  source: string;
  target: string;
  weight: number;
  value_wei?: number;
}

interface SimNode extends GNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  fixed?: boolean;
}

function riskNodeColor(risk?: number) {
  if (risk === undefined) return "#4f9cf9";
  if (risk < 0.25) return "#34d399"; // green
  if (risk < 0.5) return "#fbbf24";  // amber
  if (risk < 0.8) return "#fb923c";  // orange
  return "#f87171";                  // red
}

function riskLabel(risk?: number) {
  if (risk === undefined) return "Unknown";
  if (risk < 0.25) return "Low Risk";
  if (risk < 0.5) return "Moderate Risk";
  if (risk < 0.8) return "Elevated Risk";
  return "Critical Risk";
}

export function GraphView({
  nodes,
  edges,
  height = 480,
  onSelect,
}: {
  nodes: GNode[];
  edges: GEdge[];
  height?: number;
  onSelect?: (id: string) => void;
}) {
  const W = 900;
  const H = height;
  const cx = W / 2;
  const cy = H / 2;

  // Viewport transforms (Pan & Zoom)
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [activeDragNode, setActiveDragNode] = useState<string | null>(null);
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0 });

  // Simulation nodes state
  const [simNodes, setSimNodes] = useState<Record<string, SimNode>>({});
  const simNodesRef = useRef<Record<string, SimNode>>({});

  // Initialize and run force simulation
  useEffect(() => {
    if (!nodes.length) return;

    // Initial positioning in concentric circles
    const initial: Record<string, SimNode> = {};
    const center = nodes.find((n) => n.center);
    const others = nodes.filter((n) => !n.center);

    if (center) {
      initial[center.id] = { ...center, x: cx, y: cy, vx: 0, vy: 0, fixed: true };
    }

    const nOthers = others.length;
    others.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(nOthers, 1);
      const r = Math.min(W, H) * (0.2 + 0.2 * (i % 2));
      initial[n.id] = {
        ...n,
        x: cx + r * Math.cos(angle) + (Math.random() - 0.5) * 20,
        y: cy + r * Math.sin(angle) + (Math.random() - 0.5) * 20,
        vx: 0,
        vy: 0,
      };
    });

    // Run force simulation iterations
    const k = Math.sqrt((W * H) / Math.max(nodes.length, 1)) * 0.75;
    const iterations = 80;

    for (let iter = 0; iter < iterations; iter++) {
      const alpha = 1 - iter / iterations;

      // 1. Repulsion between all pairs
      const nodeIds = Object.keys(initial);
      for (let i = 0; i < nodeIds.length; i++) {
        const u = initial[nodeIds[i]];
        for (let j = i + 1; j < nodeIds.length; j++) {
          const v = initial[nodeIds[j]];
          let dx = v.x - u.x;
          let dy = v.y - u.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;
          if (dist > 350) continue;
          const force = (k * k) / (dist * dist);
          const fx = (dx / dist) * force * 40 * alpha;
          const fy = (dy / dist) * force * 40 * alpha;
          if (!u.fixed) {
            u.vx -= fx;
            u.vy -= fy;
          }
          if (!v.fixed) {
            v.vx += fx;
            v.vy += fy;
          }
        }
      }

      // 2. Attraction along edges
      for (const edge of edges) {
        const u = initial[edge.source];
        const v = initial[edge.target];
        if (!u || !v) continue;
        const dx = v.x - u.x;
        const dy = v.y - u.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist * dist) / (k * 20);
        const fx = (dx / dist) * force * alpha;
        const fy = (dy / dist) * force * alpha;
        if (!u.fixed) {
          u.vx += fx;
          u.vy += fy;
        }
        if (!v.fixed) {
          v.vx -= fx;
          v.vy -= fy;
        }
      }

      // 3. Center gravity and update
      for (const id of nodeIds) {
        const n = initial[id];
        if (n.fixed) continue;
        const g = 0.04 * alpha;
        n.vx += (cx - n.x) * g;
        n.vy += (cy - n.y) * g;

        // Damping
        n.x += Math.max(-15, Math.min(15, n.vx * 0.5));
        n.y += Math.max(-15, Math.min(15, n.vy * 0.5));
        n.vx *= 0.6;
        n.vy *= 0.6;

        // Keep inside bounds
        n.x = Math.max(40, Math.min(W - 40, n.x));
        n.y = Math.max(40, Math.min(H - 40, n.y));
      }
    }

    simNodesRef.current = initial;
    setSimNodes({ ...initial });
  }, [nodes, edges, cx, cy, H]);

  // Connected neighbors calculation for hover highlighting
  const connectedNeighbors = useMemo(() => {
    if (!hoveredNodeId) return new Set<string>();
    const set = new Set<string>([hoveredNodeId]);
    for (const e of edges) {
      if (e.source === hoveredNodeId) set.add(e.target);
      if (e.target === hoveredNodeId) set.add(e.source);
    }
    return set;
  }, [hoveredNodeId, edges]);

  // Drag node handling
  const handleNodePointerDown = useCallback((e: React.PointerEvent, id: string) => {
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    setActiveDragNode(id);
  }, []);

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (activeDragNode) {
        const rect = e.currentTarget.getBoundingClientRect();
        const clientX = e.clientX - rect.left;
        const clientY = e.clientY - rect.top;

        // Convert client coordinates back through viewport transform
        const worldX = (clientX - transform.x) / transform.k;
        const worldY = (clientY - transform.y) / transform.k;

        setSimNodes((prev) => {
          const current = prev[activeDragNode];
          if (!current) return prev;
          return {
            ...prev,
            [activeDragNode]: {
              ...current,
              x: Math.max(20, Math.min(W - 20, worldX)),
              y: Math.max(20, Math.min(H - 20, worldY)),
            },
          };
        });
      } else if (isPanningRef.current) {
        const dx = e.clientX - panStartRef.current.x;
        const dy = e.clientY - panStartRef.current.y;
        panStartRef.current = { x: e.clientX, y: e.clientY };
        setTransform((prev) => ({ ...prev, x: prev.x + dx, y: prev.y + dy }));
      }
    },
    [activeDragNode, transform, H]
  );

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    setActiveDragNode(null);
    isPanningRef.current = false;
  }, []);

  const handleCanvasPointerDown = useCallback((e: React.PointerEvent) => {
    isPanningRef.current = true;
    panStartRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    setTransform((prev) => ({
      ...prev,
      k: Math.max(0.4, Math.min(3.0, prev.k * factor)),
    }));
  }, []);

  const zoomIn = () => setTransform((prev) => ({ ...prev, k: Math.min(3.0, prev.k * 1.25) }));
  const zoomOut = () => setTransform((prev) => ({ ...prev, k: Math.max(0.4, prev.k * 0.8) }));
  const resetTransform = () => setTransform({ x: 0, y: 0, k: 1 });

  if (!nodes.length) {
    return <div className="loading">no graph data available</div>;
  }

  const maxW = Math.max(...edges.map((e) => e.weight), 1);
  const hoveredNode = hoveredNodeId ? simNodes[hoveredNodeId] : null;

  return (
    <div style={{ position: "relative", width: "100%", height, userSelect: "none", overflow: "hidden" }}>
      {/* Viewport Toolbar */}
      <div
        style={{
          position: "absolute",
          top: 10,
          right: 12,
          zIndex: 10,
          display: "flex",
          gap: 6,
          background: "rgba(15, 23, 42, 0.85)",
          backdropFilter: "blur(6px)",
          padding: "4px 8px",
          borderRadius: 6,
          border: "1px solid #1e293b",
        }}
      >
        <button
          type="button"
          onClick={zoomIn}
          title="Zoom in"
          style={{
            background: "transparent",
            border: "none",
            color: "#94a3b8",
            cursor: "pointer",
            fontWeight: "bold",
            padding: "2px 6px",
          }}
        >
          +
        </button>
        <button
          type="button"
          onClick={zoomOut}
          title="Zoom out"
          style={{
            background: "transparent",
            border: "none",
            color: "#94a3b8",
            cursor: "pointer",
            fontWeight: "bold",
            padding: "2px 6px",
          }}
        >
          -
        </button>
        <button
          type="button"
          onClick={resetTransform}
          title="Reset zoom and position"
          style={{
            background: "transparent",
            border: "none",
            color: "#94a3b8",
            cursor: "pointer",
            fontSize: "11px",
            padding: "2px 6px",
          }}
        >
          Reset
        </button>
      </div>

      {/* Hover Entity Info Tooltip */}
      {hoveredNode && (
        <div
          style={{
            position: "absolute",
            bottom: 12,
            left: 12,
            zIndex: 10,
            background: "rgba(10, 14, 20, 0.92)",
            backdropFilter: "blur(8px)",
            border: "1px solid #2a3b50",
            borderRadius: 8,
            padding: "8px 14px",
            fontSize: "12px",
            pointerEvents: "none",
            color: "#e2e8f0",
            maxWidth: 320,
          }}
        >
          <div style={{ fontWeight: 600, color: "#4f9cf9", marginBottom: 2 }}>
            {hoveredNode.label || short(hoveredNode.id, 18)}
          </div>
          <div style={{ fontFamily: "monospace", fontSize: "11px", color: "#94a3b8", marginBottom: 4 }}>
            {hoveredNode.id}
          </div>
          <div style={{ display: "flex", gap: 12, fontSize: "11px" }}>
            <span>
              Degree: <b>{hoveredNode.degree ?? 0}</b>
            </span>
            <span>
              Risk:{" "}
              <b style={{ color: riskNodeColor(hoveredNode.risk) }}>
                {hoveredNode.risk !== undefined ? `${(hoveredNode.risk * 100).toFixed(0)}%` : "N/A"}
              </b>{" "}
              ({riskLabel(hoveredNode.risk)})
            </span>
          </div>
        </div>
      )}

      {/* Graph Canvas SVG */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{
          width: "100%",
          height,
          cursor: activeDragNode ? "grabbing" : isPanningRef.current ? "move" : "grab",
          background: "#080c12",
          borderRadius: 8,
        }}
        onPointerDown={handleCanvasPointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
      >
        <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}>
          {/* Edges */}
          {edges.map((e, i) => {
            const s = simNodes[e.source];
            const t = simNodes[e.target];
            if (!s || !t) return null;
            const isHighlighted =
              hoveredNodeId && (e.source === hoveredNodeId || e.target === hoveredNodeId);
            const isDimmed = hoveredNodeId && !isHighlighted;
            return (
              <line
                key={i}
                x1={s.x}
                y1={s.y}
                x2={t.x}
                y2={t.y}
                stroke={isHighlighted ? "#60a5fa" : "#1e293b"}
                strokeWidth={
                  isHighlighted
                    ? 1.8 + (e.weight / maxW) * 3.2
                    : 0.8 + (e.weight / maxW) * 2.0
                }
                opacity={isHighlighted ? 0.95 : isDimmed ? 0.2 : 0.6}
              />
            );
          })}

          {/* Nodes */}
          {Object.values(simNodes).map((n) => {
            const isCenter = n.center;
            const isHovered = hoveredNodeId === n.id;
            const isConnected = connectedNeighbors.has(n.id);
            const isDimmed = hoveredNodeId && !isConnected;
            const r = isCenter ? 11 : 5 + Math.min(Math.log2((n.degree ?? 1) + 1) * 2.2, 8);
            const color = riskNodeColor(n.risk);

            return (
              <g
                key={n.id}
                onMouseEnter={() => setHoveredNodeId(n.id)}
                onMouseLeave={() => setHoveredNodeId(null)}
                onPointerDown={(e) => handleNodePointerDown(e, n.id)}
                onClick={() => onSelect?.(n.id)}
                style={{ cursor: "pointer", opacity: isDimmed ? 0.25 : 1 }}
              >
                {/* Glow ring on high risk or hovered */}
                {(isHovered || isCenter || (n.risk && n.risk >= 0.8)) && (
                  <circle
                    cx={n.x}
                    cy={n.y}
                    r={r + (isHovered ? 8 : 4)}
                    fill={color}
                    opacity={isHovered ? 0.35 : 0.18}
                  />
                )}

                {/* Node body */}
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={r}
                  fill={color}
                  stroke="#080c12"
                  strokeWidth={isCenter ? 2.5 : 1.5}
                />

                {/* Node label */}
                {(isCenter || isHovered || (n.degree && n.degree > 15)) && (
                  <text
                    x={n.x}
                    y={n.y - r - 6}
                    textAnchor="middle"
                    fill="#f1f5f9"
                    fontSize={isCenter ? 12 : 10}
                    fontWeight={isCenter || isHovered ? 600 : 400}
                    fontFamily="ui-monospace, monospace"
                    style={{ pointerEvents: "none" }}
                  >
                    {n.label ?? short(n.id, 12)}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
