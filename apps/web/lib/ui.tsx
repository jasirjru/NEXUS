"use client";

/** Shared data-fetching + formatting helpers and small UI components. */

import { useCallback, useEffect, useState } from "react";

export const API = "/api/v1";

export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    if (!path) return;
    setLoading(true);
    fetch(path)
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
        return r.json();
      })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, loading, error, reload, setData };
}

export function post(path: string, body?: unknown) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(async (r) => {
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.json();
  });
}

export function short(id: string, n = 10) {
  if (!id) return "";
  return id.length <= n ? id : `${id.slice(0, n)}…${id.slice(-4)}`;
}

export function fmtEth(wei: number | null | undefined) {
  if (wei === null || wei === undefined) return "—";
  const eth = wei / 1e18;
  if (eth === 0) return "0";
  if (eth < 0.001) return eth.toExponential(2);
  if (eth < 1) return eth.toFixed(4);
  if (eth > 1e6) return `${(eth / 1e6).toFixed(1)}M`;
  return eth.toFixed(2);
}

export function fmtNum(x: number | null | undefined, digits = 3) {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  if (Math.abs(x) >= 1e6) return `${(x / 1e6).toFixed(1)}M`;
  return x.toFixed(digits);
}

export function riskColor(v: number) {
  if (v < 0.25) return "var(--ok)";
  if (v < 0.5) return "var(--warn)";
  if (v < 0.8) return "#fb923c";
  return "var(--crit)";
}

export function RiskBar({ value }: { value: number }) {
  return (
    <div className="risk-bar" style={{ minWidth: 70 }}>
      <div style={{ width: `${Math.round(value * 100)}%`, background: riskColor(value) }} />
    </div>
  );
}

export function Badge({ tone, children }: { tone: string; children: React.ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function riskTone(v: number) {
  if (v >= 0.8) return "crit";
  if (v >= 0.5) return "warn";
  return "ok";
}

export function Loading({ label = "loading" }: { label?: string }) {
  return <div className="loading">{label}…</div>;
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <>
      <h1>{title}</h1>
      {subtitle && <div className="subtitle">{subtitle}</div>}
    </>
  );
}
