"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Empty, ErrorBox, Loading, PageHeader, Pager, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate } from "@/lib/api";
import type { Call, Page } from "@/types";

export default function Calls() {
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [direction, setDirection] = useState("");
  const qs = new URLSearchParams({ limit: "25", offset: String(offset), ...(status && { status }), ...(direction && { direction }) });
  const q = useApi<Page<Call>>(`/calls?${qs}`, { refetchInterval: 15000 });
  return (
    <div>
      <PageHeader title="Call history" subtitle="Live and mock calls with outcomes. Mock calls are labelled and never billed." />
      <div className="mb-4 flex flex-wrap gap-2">
        <select className="input w-44" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} aria-label="Status">
          <option value="">All statuses</option>{["completed", "failed", "in_progress", "provider_accepted", "cancelled"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <select className="input w-44" value={direction} onChange={(e) => { setDirection(e.target.value); setOffset(0); }} aria-label="Direction">
          <option value="">All directions</option><option>inbound</option><option>outbound</option>
        </select>
      </div>
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : q.data?.items.length ? (
        <>
          <Table head={["When", "Direction", "From", "To", "Status", "Outcome", "Duration", "Handoff"]}>
            {q.data.items.map((c) => (
              <tr key={c.id} className="hover:bg-panel">
                <td className="td"><Link className="text-brand-700 hover:underline" href={`/calling-agent/calls/${c.id}`}>{fmtDate(c.created_at)}</Link> {c.is_mock && <Badge tone="orange">mock</Badge>}</td>
                <td className="td capitalize">{c.direction}</td>
                <td className="td font-mono text-xs">{c.from_number ?? "—"}</td>
                <td className="td font-mono text-xs">{c.to_number ?? "—"}</td>
                <td className="td"><Badge>{c.status}</Badge></td>
                <td className="td">{c.outcome ? <Badge>{c.outcome}</Badge> : "—"}</td>
                <td className="td">{c.duration_seconds}s</td>
                <td className="td">{c.handoff_requested ? <Badge tone="orange">requested</Badge> : ""}</td>
              </tr>
            ))}
          </Table>
          <Pager total={q.data.total} limit={q.data.limit} offset={offset} onChange={setOffset} />
        </>
      ) : <Empty title="No calls match" />}
    </div>
  );
}
