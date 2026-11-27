"use client";

import { useState } from "react";

import { Icon } from "@/components/icons";
import { api } from "@/lib/api";

export type MetricResult = {
  metric: string;
  title: string;
  definition: string;
  period: { from: string; to: string } | null;
  kpis: { label: string; value: number | null; unit: string | null }[];
  table: { columns: string[]; rows: (string | number | null)[][] } | null;
  chart: { type: string; x: string[]; series: { name: string; values: number[] }[] } | null;
  warnings: string[];
  source: { fetched_at: string; connector?: string; connection_name?: string; records?: number };
};

export type Artifact =
  | { type: "metric"; data: MetricResult }
  | { type: "approval"; data: { status: string; action_id: string; summary: string } }
  | { type: "memory_proposal"; data: { id: string; content: string } }
  | { type: "reminder"; data: { id: string; text: string; due_at: string } }
  | { type: "citations"; data: { title: string; url: string; snippet: string; retrieved: string }[] };

const fmt = (v: number | null, unit: string | null) =>
  v == null ? "—" : unit && /^[A-Z]{3}$/.test(unit)
    ? v.toLocaleString("en-IN", { style: "currency", currency: unit, maximumFractionDigits: 2 })
    : `${v.toLocaleString("en-IN")}${unit ? ` ${unit}` : ""}`;

function csv(m: MetricResult): string {
  const esc = (x: unknown) => {
    let s = String(x ?? "");
    if (/^[=+\-@]/.test(s)) s = `'${s}`; // spreadsheet formula-injection guard
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [m.title, ...m.kpis.map((k) => `${esc(k.label)},${esc(k.value)},${esc(k.unit)}`), ""];
  if (m.table) lines.push(m.table.columns.map(esc).join(","), ...m.table.rows.map((r) => r.map(esc).join(",")));
  return lines.join("\n");
}

export function MetricCard({ m }: { m: MetricResult }) {
  const max = m.chart ? Math.max(1, ...m.chart.series[0].values.map((v) => Math.abs(v))) : 1;
  const download = () => {
    const url = URL.createObjectURL(new Blob([csv(m)], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${m.metric}-${m.period?.from ?? "report"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="mt-3 rounded-xl border border-line bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{m.title}</div>
          {m.period && <div className="text-xs text-muted">{m.period.from === m.period.to ? m.period.from : `${m.period.from} → ${m.period.to}`}</div>}
        </div>
        <button className="btn-secondary px-2 py-1 text-xs" onClick={download}><Icon name="download" className="h-4 w-4" /> CSV</button>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        {m.kpis.map((k) => (
          <div key={k.label} className="rounded-lg bg-panel px-3 py-2">
            <div className="text-xs text-muted">{k.label}</div>
            <div className="font-semibold">{fmt(k.value, k.unit)}</div>
          </div>
        ))}
      </div>
      {m.chart && m.chart.x.length > 0 && (
        <div className="mt-4">
          <div className="flex h-32 items-end gap-1" role="img" aria-label={`${m.chart.series[0].name} chart`}>
            {m.chart.x.map((x, i) => {
              const v = m.chart!.series[0].values[i];
              return <div key={x} className="flex-1 rounded-t bg-brand-500" style={{ height: `${(Math.abs(v) / max) * 120 + 2}px`, opacity: v < 0 ? 0.4 : 1 }} title={`${x}: ${v.toLocaleString("en-IN")}`} />;
            })}
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-muted"><span>{m.chart.x[0]}</span><span>{m.chart.x[m.chart.x.length - 1]}</span></div>
        </div>
      )}
      {m.table && m.table.rows.length > 0 && (
        <div className="mt-4 max-h-64 overflow-auto rounded-lg border border-line">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 bg-panel"><tr>{m.table.columns.map((c) => <th key={c} className="th">{c}</th>)}</tr></thead>
            <tbody className="divide-y divide-line">{m.table.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="px-4 py-2">{typeof c === "number" ? c.toLocaleString("en-IN") : c ?? "—"}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      {m.warnings.map((w) => <p key={w} className="mt-2 text-xs text-brand-700">⚠ {w}</p>)}
      <p className="mt-2 text-xs text-muted">Source: {m.source.connection_name ?? m.source.connector} · {m.source.records ?? 0} records · fetched {new Date(m.source.fetched_at).toLocaleTimeString("en-IN")} · {m.definition}</p>
    </div>
  );
}

export function ArtifactView({ a, onChange }: { a: Artifact; onChange?: () => void }) {
  const [state, setState] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (a.type === "metric") return <MetricCard m={a.data} />;
  if (a.type === "approval") {
    const decide = async (approve: boolean) => {
      setError(null);
      try {
        const actions = await api<{ id: string; args_hash: string }[]>("/assistant/actions");
        const hash = actions.find((x) => x.id === a.data.action_id)?.args_hash ?? "";
        const r = await api<{ status: string }>(`/assistant/actions/${a.data.action_id}/decision`, { method: "POST", body: { approve, args_hash: hash } });
        setState(r.status);
        onChange?.();
      } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    };
    return (
      <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50 p-4 text-sm">
        <div className="font-medium">Approval needed</div>
        <p className="mt-1">{a.data.summary}</p>
        {state ? <p className="mt-2 font-medium">{state === "executed" ? "Done — created." : state === "rejected" ? "Rejected — nothing was changed." : `Status: ${state}`}</p> : (
          <div className="mt-3 flex gap-2">
            <button className="btn-primary" onClick={() => decide(true)}>Approve</button>
            <button className="btn-secondary" onClick={() => decide(false)}>Reject</button>
          </div>
        )}
        {error && <p className="mt-2 text-red-600">{error}</p>}
      </div>
    );
  }
  if (a.type === "memory_proposal") {
    return (
      <div className="mt-3 rounded-xl border border-line bg-white p-4 text-sm">
        <div className="font-medium">Save to memory?</div>
        <p className="mt-1">“{a.data.content}”</p>
        {state ? <p className="mt-2 font-medium">{state}</p> : (
          <div className="mt-3 flex gap-2">
            <button className="btn-primary" onClick={async () => { await api(`/assistant/memory/${a.data.id}/approve`, { method: "POST" }); setState("Saved"); onChange?.(); }}>Remember</button>
            <button className="btn-secondary" onClick={async () => { await api(`/assistant/memory/${a.data.id}`, { method: "DELETE" }); setState("Discarded"); onChange?.(); }}>Don&apos;t save</button>
          </div>
        )}
      </div>
    );
  }
  if (a.type === "reminder") return <div className="mt-3 rounded-xl border border-line bg-white p-3 text-sm">⏰ Reminder set: {a.data.text} — {new Date(a.data.due_at).toLocaleString("en-IN")}</div>;
  if (a.type === "citations") {
    return (
      <ol className="mt-3 space-y-1 text-sm">
        {a.data.map((c, i) => <li key={c.url}>[{i + 1}] <a className="text-brand-700 underline" href={c.url} target="_blank" rel="noreferrer noopener">{c.title}</a> <span className="text-xs text-muted">retrieved {c.retrieved}</span></li>)}
      </ol>
    );
  }
  return null;
}
