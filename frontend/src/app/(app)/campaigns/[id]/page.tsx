"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { Badge, ErrorBox, Field, Loading, PageHeader, Stat, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Campaign } from "@/types";

type Detail = Campaign & { stats: { contacts_by_status: Record<string, number>; outcomes: Record<string, number>; attempts: number } };
type CC = { id: string; contact_id: string; name: string | null; phone: string; status: string; ineligible_reason: string | null; attempts: number; last_outcome: string | null; next_attempt_at: string | null };

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const q = useApi<Detail>(`/campaigns/${id}`, { refetchInterval: 10000 });
  const contacts = useApi<{ items: CC[] }>(`/campaigns/${id}/contacts?limit=200`, { refetchInterval: 10000 });
  const [tag, setTag] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const c = q.data!;
  const act = async (path: string, body?: unknown) => {
    setError(null);
    setMsg(null);
    try {
      const r = await api<Record<string, unknown>>(path, { method: "POST", body });
      setMsg(Object.entries(r).filter(([, v]) => typeof v !== "object").map(([k, v]) => `${k}: ${v}`).join(" · "));
      q.refetch();
      contacts.refetch();
    } catch (e) {
      setError(e);
    }
  };
  const s = c.stats.contacts_by_status;

  return (
    <div>
      <PageHeader title={c.name} subtitle={`Purpose: ${c.purpose} · ${c.window_start}–${c.window_end} ${c.timezone}`}
        actions={can("campaigns:control") && <>
          <Badge>{c.status}</Badge>
          {["draft", "scheduled"].includes(c.status) && <button className="btn-primary" onClick={() => act(`/campaigns/${id}/start`)}>Start</button>}
          {c.status === "running" && <><button className="btn-secondary" onClick={() => act(`/campaigns/${id}/dispatch-now`)}>Dispatch now</button><button className="btn-secondary" onClick={() => act(`/campaigns/${id}/pause`)}>Pause</button></>}
          {c.status === "paused" && <button className="btn-primary" onClick={() => act(`/campaigns/${id}/resume`)}>Resume</button>}
          {!["completed", "cancelled"].includes(c.status) && <button className="btn-danger" onClick={() => window.confirm("Cancel this campaign?") && act(`/campaigns/${id}/cancel`)}>Cancel</button>}
        </>} />
      <ErrorBox error={error} />
      {msg && <div className="mb-3 rounded-lg bg-panel px-4 py-2 text-sm">{msg}</div>}
      <div className="grid gap-4 sm:grid-cols-4">
        <Stat label="Eligible" value={s.eligible ?? 0} />
        <Stat label="Ineligible" value={s.ineligible ?? 0} hint="missing consent / suppressed" />
        <Stat label="Attempts" value={c.stats.attempts} />
        <Stat label="Completed" value={(s.completed ?? 0) + (s.exhausted ?? 0)} />
      </div>
      {Object.keys(c.stats.outcomes).length > 0 && (
        <div className="card mt-4 flex flex-wrap gap-2 text-sm">{Object.entries(c.stats.outcomes).map(([k, v]) => <span key={k}><Badge>{k}</Badge> {v}</span>)}</div>
      )}
      {can("campaigns:write") && !["completed", "cancelled"].includes(c.status) && (
        <div className="card mt-4 flex flex-wrap items-end gap-3">
          <Field label="Add all contacts with tag"><input className="input" value={tag} onChange={(e) => setTag(e.target.value)} placeholder="e.g. diwali-leads" /></Field>
          <button className="btn-secondary" disabled={!tag} onClick={() => act(`/campaigns/${id}/contacts`, { tag })}>Add contacts</button>
        </div>
      )}
      <h2 className="mb-3 mt-6 font-semibold">Contacts</h2>
      <Table head={["Contact", "Status", "Reason", "Attempts", "Last outcome", "Next attempt"]}>
        {contacts.data?.items.map((x) => (
          <tr key={x.id}>
            <td className="td">{x.name ?? "—"} <span className="font-mono text-xs text-muted">{x.phone}</span></td>
            <td className="td"><Badge>{x.status}</Badge></td>
            <td className="td text-xs">{x.ineligible_reason ?? ""}</td>
            <td className="td">{x.attempts}</td>
            <td className="td">{x.last_outcome ? <Badge>{x.last_outcome}</Badge> : "—"}</td>
            <td className="td">{fmtDate(x.next_attempt_at)}</td>
          </tr>
        ))}
      </Table>
    </div>
  );
}
