"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Empty, ErrorBox, Loading, PageHeader, Pager, Table } from "@/components/ui";
import { useApi, useMutate } from "@/hooks/useApi";
import { fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Lead, Page } from "@/types";

const STATUSES = ["new", "contacted", "qualified", "unqualified", "converted", "lost"];
type Member = { user_id: string; full_name: string; role: string; is_active: boolean };

export default function Leads() {
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const q = useApi<Page<Lead>>(`/leads?limit=25&offset=${offset}${status ? `&status=${status}` : ""}`);
  const members = useApi<Member[]>(can("users:read") ? "/users" : null);
  const update = useMutate<{ id: string; status: string }>("PATCH", (b) => `/leads/${b.id}`, ["/leads"], (b) => ({ status: b.status }));
  const assign = useMutate<{ id: string; user_id: string | null }>("POST", (b) => `/leads/${b.id}/assign`, ["/leads"], (b) => ({ user_id: b.user_id }));

  return (
    <div>
      <PageHeader title="Leads" subtitle="Updated automatically from call outcomes using deterministic qualification rules." />
      <div className="mb-4 flex flex-wrap gap-2">
        {["", ...STATUSES].map((s) => (
          <button key={s || "all"} className={status === s ? "btn-primary" : "btn-secondary"} onClick={() => { setStatus(s); setOffset(0); }}>{s || "All"}</button>
        ))}
      </div>
      <ErrorBox error={update.error || assign.error} />
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : q.data?.items.length ? (
        <>
          <Table head={["Contact", "Status", "Score", "Last outcome", "Follow-up", "Assigned to"]}>
            {q.data.items.map((l) => (
              <tr key={l.id}>
                <td className="td"><Link className="text-brand-700 hover:underline" href={`/contacts/${l.contact_id}`}>{l.contact_name ?? l.contact_phone}</Link></td>
                <td className="td">
                  <select className="input w-36" value={l.status} onChange={(e) => update.mutate({ id: l.id, status: e.target.value })} aria-label="Lead status">
                    {STATUSES.map((s) => <option key={s}>{s}</option>)}
                  </select>
                </td>
                <td className="td">{l.score}</td>
                <td className="td">{l.last_outcome ? <Badge>{l.last_outcome}</Badge> : "—"}</td>
                <td className="td">{fmtDate(l.next_follow_up_at)}</td>
                <td className="td">
                  {can("leads:assign") ? (
                    <select className="input w-44" value={l.assigned_to ?? ""} onChange={(e) => assign.mutate({ id: l.id, user_id: e.target.value || null })} aria-label="Assignee">
                      <option value="">Unassigned</option>
                      {members.data?.filter((m) => m.is_active).map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name}</option>)}
                    </select>
                  ) : (members.data?.find((m) => m.user_id === l.assigned_to)?.full_name ?? (l.assigned_to ? "Assigned" : "—"))}
                </td>
              </tr>
            ))}
          </Table>
          <Pager total={q.data.total} limit={q.data.limit} offset={offset} onChange={setOffset} />
        </>
      ) : <Empty title="No leads" body="Leads are created from inbound calls, positive campaign outcomes, or manually from a contact." />}
    </div>
  );
}
