"use client";

import { useState } from "react";

import { Empty, ErrorBox, Loading, PageHeader, Pager, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate } from "@/lib/api";
import type { Page } from "@/types";

type Log = { id: string; actor_user_id: string | null; actor_type: string; action: string; resource_type: string | null; resource_id: string | null; ip_address: string | null; details: Record<string, unknown>; created_at: string };

export default function Audit() {
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const q = useApi<Page<Log>>(`/audit-logs?limit=50&offset=${offset}${action ? `&action=${encodeURIComponent(action)}` : ""}`);
  return (
    <div>
      <PageHeader title="Audit log" subtitle="Security-relevant actions in your organization." />
      <input className="input mb-4 max-w-sm" placeholder="Filter by exact action, e.g. campaign.started" value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }} aria-label="Action filter" />
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : q.data?.items.length ? (
        <>
          <Table head={["When", "Action", "Actor", "Resource", "IP", "Details"]}>
            {q.data.items.map((l) => (
              <tr key={l.id}>
                <td className="td whitespace-nowrap">{fmtDate(l.created_at)}</td>
                <td className="td font-mono text-xs">{l.action}</td>
                <td className="td text-xs">{l.actor_type}{l.actor_user_id ? ` ${l.actor_user_id.slice(0, 8)}` : ""}</td>
                <td className="td text-xs">{l.resource_type ?? ""} {l.resource_id?.slice(0, 8) ?? ""}</td>
                <td className="td text-xs">{l.ip_address ?? ""}</td>
                <td className="td max-w-xs truncate text-xs">{JSON.stringify(l.details)}</td>
              </tr>
            ))}
          </Table>
          <Pager total={q.data.total} limit={q.data.limit} offset={offset} onChange={setOffset} />
        </>
      ) : <Empty title="No audit entries" />}
    </div>
  );
}
