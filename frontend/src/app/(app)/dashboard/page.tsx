"use client";

import Link from "next/link";

import { Badge, Empty, ErrorBox, Loading, PageHeader, Stat, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Call, Page } from "@/types";

type Overview = {
  calls: { total: number; answered: number; failed: number; inbound: number; outbound: number; answer_rate: number | null; handoffs: number };
  duration: { total_minutes: number; avg_answered_seconds: number };
  leads: { created: number; qualified: number; converted: number; qualification_rate: number | null };
};
type Sub = { status: string; plan: { name: string; included_minutes: number }; minutes_used: number; current_period_end: string };

const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);

export default function Dashboard() {
  const { can, membership } = useAuth();
  const ov = useApi<Overview>("/analytics/overview?days=30");
  const sub = useApi<Sub>(can("billing:read") ? "/billing/subscription" : null);
  const calls = useApi<Page<Call>>("/calls?limit=8");
  const tasks = useApi<{ id: string; lead_id: string; body: string; due_at: string | null }[]>("/leads/tasks/open");

  return (
    <div>
      <PageHeader title={`Welcome${membership ? `, ${membership.tenant_name}` : ""}`} subtitle="Last 30 days of live (non-mock) activity" />
      {ov.isLoading ? <Loading /> : ov.error ? <ErrorBox error={ov.error} /> : ov.data && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Calls" value={ov.data.calls.total} hint={`${ov.data.calls.inbound} inbound · ${ov.data.calls.outbound} outbound`} />
          <Stat label="Answer rate" value={pct(ov.data.calls.answer_rate)} hint={`${ov.data.calls.failed} failed`} />
          <Stat label="Qualified leads" value={ov.data.leads.qualified} hint={`${ov.data.leads.created} leads created`} />
          <Stat label="Talk time" value={`${ov.data.duration.total_minutes} min`} hint={`${ov.data.calls.handoffs} human handoffs`} />
        </div>
      )}
      {sub.data && (
        <div className="card mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="text-sm">
            <span className="font-medium">{sub.data.plan.name}</span> <Badge>{sub.data.status}</Badge>
            <span className="ml-3 text-muted">{sub.data.minutes_used} / {sub.data.plan.included_minutes} minutes used · renews/ends {fmtDate(sub.data.current_period_end)}</span>
          </div>
          <Link href="/billing" className="btn-secondary">Manage plan</Link>
        </div>
      )}
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <section className="lg:col-span-2">
          <h2 className="mb-3 font-semibold">Recent calls</h2>
          {calls.isLoading ? <Loading /> : calls.data?.items.length ? (
            <Table head={["When", "Direction", "Status", "Outcome", "Duration"]}>
              {calls.data.items.map((c) => (
                <tr key={c.id} className="hover:bg-panel">
                  <td className="td"><Link className="text-brand-700 hover:underline" href={`/calls/${c.id}`}>{fmtDate(c.created_at)}</Link> {c.is_mock && <Badge tone="orange">mock</Badge>}</td>
                  <td className="td capitalize">{c.direction}</td>
                  <td className="td"><Badge>{c.status}</Badge></td>
                  <td className="td">{c.outcome ? <Badge>{c.outcome}</Badge> : "—"}</td>
                  <td className="td">{c.duration_seconds}s</td>
                </tr>
              ))}
            </Table>
          ) : <Empty title="No calls yet" body="Publish an agent and connect a phone number, or run a simulated call from Voice testing." action={<Link className="btn-primary" href="/agents">Set up an agent</Link>} />}
        </section>
        <section>
          <h2 className="mb-3 font-semibold">Open follow-ups</h2>
          {tasks.data?.length ? (
            <ul className="card divide-y divide-line p-0">
              {tasks.data.slice(0, 8).map((t) => (
                <li key={t.id} className="px-4 py-3 text-sm">
                  <div>{t.body}</div>
                  <div className="text-xs text-muted">Due {fmtDate(t.due_at)}</div>
                </li>
              ))}
            </ul>
          ) : <Empty title="No open follow-ups" />}
        </section>
      </div>
    </div>
  );
}
