"use client";

import { useState } from "react";

import { Badge, Empty, ErrorBox, Loading, PageHeader, Stat, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/lib/auth";

type Overview = {
  calls: { total: number; answered: number; failed: number; inbound: number; outbound: number; answer_rate: number | null; handoffs: number };
  duration: { total_minutes: number; avg_answered_seconds: number };
  leads: { created: number; qualified: number; converted: number; qualification_rate: number | null };
  outcomes: Record<string, number>;
  daily: { day: string; calls: number; answered: number }[];
  provider_cost: { provider: string; amount_minor: number | null; currency_note: string; calls_without_cost_data: number }[];
};
type AgentPerf = { agent_id: string; name: string; calls: number; answered: number; avg_seconds: number; positive_outcomes: number };
type CampPerf = { campaign_id: string; name: string; status: string; calls: number; answered: number; conversions: number; opt_outs: number; conversion_rate: number | null };
type Usage = { daily: { day: string; minutes: number; calls: number }[]; mock_minutes_excluded: number };
const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);

export default function Analytics() {
  const { can } = useAuth();
  const [days, setDays] = useState(30);
  const [mock, setMock] = useState(false);
  const ov = useApi<Overview>(`/analytics/overview?days=${days}&include_mock=${mock}`);
  const agents = useApi<AgentPerf[]>(`/analytics/agents?days=${days}`);
  const camps = useApi<CampPerf[]>("/analytics/campaigns");
  const usage = useApi<Usage>(can("billing:read") ? `/billing/usage?days=${days}` : null);
  const max = Math.max(1, ...(ov.data?.daily.map((d) => d.calls) ?? [1]));

  return (
    <div>
      <PageHeader title="Analytics" subtitle="Computed from stored call, lead and usage records."
        actions={<>
          <select className="input w-36" value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">{[7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}</select>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={mock} onChange={(e) => setMock(e.target.checked)} /> include mock</label>
        </>} />
      {ov.isLoading ? <Loading /> : ov.error ? <ErrorBox error={ov.error} /> : ov.data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Call volume" value={ov.data.calls.total} hint={`${ov.data.calls.inbound} in · ${ov.data.calls.outbound} out`} />
            <Stat label="Answered" value={ov.data.calls.answered} hint={`answer rate ${pct(ov.data.calls.answer_rate)}`} />
            <Stat label="Failed" value={ov.data.calls.failed} />
            <Stat label="Avg answered duration" value={`${ov.data.duration.avg_answered_seconds}s`} hint={`${ov.data.duration.total_minutes} min total`} />
            <Stat label="Leads created" value={ov.data.leads.created} />
            <Stat label="Qualified" value={ov.data.leads.qualified} hint={`rate ${pct(ov.data.leads.qualification_rate)}`} />
            <Stat label="Converted" value={ov.data.leads.converted} />
            <Stat label="Human handoffs" value={ov.data.calls.handoffs} />
          </div>
          <div className="card mt-6">
            <h2 className="mb-3 font-semibold">Daily calls</h2>
            {ov.data.daily.length ? (
              <div className="flex h-40 items-end gap-1" role="img" aria-label="Daily call volume bar chart">
                {ov.data.daily.map((d) => (
                  <div key={d.day} className="group relative flex-1" title={`${d.day}: ${d.calls} calls, ${d.answered} answered`}>
                    <div className="rounded-t bg-gray-200" style={{ height: `${(d.calls / max) * 150}px` }}>
                      <div className="rounded-t bg-brand-500" style={{ height: `${d.calls ? (d.answered / d.calls) * 100 : 0}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : <p className="text-sm text-muted">No calls in this period.</p>}
            <p className="mt-2 text-xs text-muted">Orange = answered, grey = not answered.</p>
          </div>
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div className="card">
              <h2 className="mb-3 font-semibold">Outcomes</h2>
              <div className="flex flex-wrap gap-2 text-sm">{Object.entries(ov.data.outcomes).map(([k, v]) => <span key={k}><Badge>{k}</Badge> {v}</span>)}</div>
              {!Object.keys(ov.data.outcomes).length && <p className="text-sm text-muted">No outcomes yet.</p>}
            </div>
            <div className="card">
              <h2 className="mb-3 font-semibold">Provider cost</h2>
              {ov.data.provider_cost.length ? ov.data.provider_cost.map((p) => (
                <div key={p.provider} className="text-sm">{p.provider}: {p.amount_minor ?? "unknown"} {p.currency_note} {p.calls_without_cost_data > 0 && <span className="text-xs text-muted">({p.calls_without_cost_data} calls without cost data)</span>}</div>
              )) : <p className="text-sm text-muted">No provider cost data.</p>}
              {usage.data && <p className="mt-3 text-sm">Billable minutes: {usage.data.daily.reduce((a, d) => a + d.minutes, 0)} <span className="text-xs text-muted">(mock minutes excluded: {usage.data.mock_minutes_excluded})</span></p>}
            </div>
          </div>
        </>
      )}
      <h2 className="mb-3 mt-8 font-semibold">Agent performance</h2>
      {agents.data?.length ? (
        <Table head={["Agent", "Calls", "Answered", "Avg seconds", "Positive outcomes"]}>
          {agents.data.map((a) => <tr key={a.agent_id}><td className="td">{a.name}</td><td className="td">{a.calls}</td><td className="td">{a.answered}</td><td className="td">{a.avg_seconds}</td><td className="td">{a.positive_outcomes}</td></tr>)}
        </Table>
      ) : <Empty title="No agents" />}
      <h2 className="mb-3 mt-8 font-semibold">Campaign performance</h2>
      {camps.data?.length ? (
        <Table head={["Campaign", "Status", "Calls", "Answered", "Conversions", "Opt-outs", "Conversion rate"]}>
          {camps.data.map((c) => <tr key={c.campaign_id}><td className="td">{c.name}</td><td className="td"><Badge>{c.status}</Badge></td><td className="td">{c.calls}</td><td className="td">{c.answered}</td><td className="td">{c.conversions}</td><td className="td">{c.opt_outs}</td><td className="td">{pct(c.conversion_rate)}</td></tr>)}
        </Table>
      ) : <Empty title="No campaigns" />}
    </div>
  );
}
