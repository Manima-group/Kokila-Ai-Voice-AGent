"use client";

import Link from "next/link";

import { Badge, Empty, ErrorBox, Loading, PageHeader, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Campaign } from "@/types";

export default function Campaigns() {
  const { can } = useAuth();
  const q = useApi<Campaign[]>("/campaigns");
  return (
    <div>
      <PageHeader title="Outbound campaigns" subtitle="Only contacts with recorded consent for the campaign purpose are dialled, within 9 AM–9 PM IST."
        actions={can("campaigns:write") && <Link className="btn-primary" href="/calling-agent/campaigns/new">New campaign</Link>} />
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : q.data?.length ? (
        <Table head={["Name", "Purpose", "Status", "Window", "Concurrency", "Created"]}>
          {q.data.map((c) => (
            <tr key={c.id} className="hover:bg-panel">
              <td className="td"><Link className="font-medium text-brand-700 hover:underline" href={`/calling-agent/campaigns/${c.id}`}>{c.name}</Link></td>
              <td className="td">{c.purpose}</td>
              <td className="td"><Badge>{c.status}</Badge></td>
              <td className="td">{c.window_start}–{c.window_end} <span className="text-xs text-muted">{c.timezone}</span></td>
              <td className="td">{c.max_concurrency}</td>
              <td className="td">{fmtDate(c.created_at)}</td>
            </tr>
          ))}
        </Table>
      ) : <Empty title="No campaigns" body="Create a campaign, add consented contacts and start it once compliance checks pass." />}
    </div>
  );
}
