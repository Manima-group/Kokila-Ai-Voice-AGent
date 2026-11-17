"use client";

import Link from "next/link";

import { Badge, Empty, ErrorBox, Loading, PageHeader, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Agent } from "@/types";

export default function AgentsPage() {
  const { can } = useAuth();
  const q = useApi<Agent[]>("/agents");
  return (
    <div>
      <PageHeader title="Voice agents" subtitle="Each agent has versioned configuration; publishing syncs it to the voice provider."
        actions={can("agents:write") && <Link className="btn-primary" href="/agents/new">New agent</Link>} />
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : q.data?.length ? (
        <Table head={["Name", "Template", "Status", "Version", "Provider sync", "Created"]}>
          {q.data.map((a) => (
            <tr key={a.id} className="hover:bg-panel">
              <td className="td"><Link className="font-medium text-brand-700 hover:underline" href={`/agents/${a.id}`}>{a.name}</Link></td>
              <td className="td">{a.template.replace(/_/g, " ")}</td>
              <td className="td"><Badge>{a.status}</Badge></td>
              <td className="td">v{a.latest_version}</td>
              <td className="td"><Badge tone={a.sync_status === "synced" ? "green" : a.sync_status === "failed" ? "red" : "grey"}>{a.sync_status}</Badge> <span className="text-xs text-muted">{a.provider}</span></td>
              <td className="td">{fmtDate(a.created_at)}</td>
            </tr>
          ))}
        </Table>
      ) : <Empty title="No agents yet" body="Start from a template: receptionist, admissions, real estate, booking, support or sales follow-up."
        action={can("agents:write") && <Link className="btn-primary" href="/agents/new">Create agent</Link>} />}
    </div>
  );
}
