"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Badge, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Call } from "@/types";

type Detail = Call & {
  summary?: string | null;
  transcript?: string | null;
  transcript_segments?: { role: string; content: string }[] | null;
  extracted?: Record<string, unknown>;
  recording_url?: string | null;
  disconnection_reason: string | null;
  events: { type: string; applied: boolean; at: string }[];
};

export default function CallDetail() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const q = useApi<Detail>(`/calls/${id}`, { refetchInterval: 10000 });
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const c = q.data!;
  const act = async (path: string, ok: string) => {
    setError(null);
    try {
      await api(path, { method: "POST" });
      setMsg(ok);
      q.refetch();
    } catch (e) {
      setError(e);
    }
  };
  const live = !["completed", "failed", "cancelled"].includes(c.status);

  return (
    <div>
      <PageHeader title={`${c.direction === "inbound" ? "Inbound" : "Outbound"} call`} subtitle={fmtDate(c.created_at)}
        actions={<>
          {c.is_mock && <Badge tone="orange">mock — not a real call</Badge>}
          <Badge>{c.status}</Badge>
          {live && can("calls:handoff") && <button className="btn-danger" onClick={() => act(`/calls/${id}/terminate`, "Termination requested; final status arrives from the provider.")}>End call</button>}
          {c.handoff_requested && can("calls:handoff") && <button className="btn-secondary" onClick={() => act(`/calls/${id}/handoff`, "Handoff marked as handled.")}>Mark handoff handled</button>}
        </>} />
      <ErrorBox error={error} />
      {msg && <div className="mb-3 rounded-lg bg-green-50 px-4 py-2 text-sm text-green-700">{msg}</div>}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <div className="card">
            <h2 className="mb-2 font-semibold">Summary</h2>
            <p className="text-sm">{c.summary ?? (can("calls:transcript") ? "Post-call analysis not available yet." : "You do not have access to call content.")}</p>
          </div>
          <div className="card">
            <h2 className="mb-3 font-semibold">Transcript</h2>
            {c.transcript_segments?.length ? (
              <ol className="space-y-2">
                {c.transcript_segments.map((s, i) => (
                  <li key={i} className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${s.role === "agent" ? "bg-brand-50" : "ml-auto bg-panel"}`}>
                    <span className="block text-[11px] font-semibold uppercase text-muted">{s.role === "agent" ? "Agent" : "Caller"}</span>{s.content}
                  </li>
                ))}
              </ol>
            ) : c.transcript ? <pre className="whitespace-pre-wrap text-sm">{c.transcript}</pre> : <p className="text-sm text-muted">No transcript.</p>}
          </div>
        </div>
        <div className="space-y-6">
          <div className="card text-sm">
            <h2 className="mb-3 font-semibold">Details</h2>
            <dl className="grid grid-cols-2 gap-y-2">
              <dt className="text-muted">From</dt><dd className="font-mono text-xs">{c.from_number ?? "—"}</dd>
              <dt className="text-muted">To</dt><dd className="font-mono text-xs">{c.to_number ?? "—"}</dd>
              <dt className="text-muted">Outcome</dt><dd>{c.outcome ? <Badge>{c.outcome}</Badge> : "—"}</dd>
              <dt className="text-muted">Sentiment</dt><dd>{c.sentiment ?? "—"}</dd>
              <dt className="text-muted">Duration</dt><dd>{c.duration_seconds}s</dd>
              <dt className="text-muted">Ended by</dt><dd>{c.disconnection_reason ?? "—"}</dd>
              <dt className="text-muted">Analysis</dt><dd><Badge>{c.analysis_status}</Badge></dd>
              <dt className="text-muted">Provider</dt><dd>{c.provider}</dd>
            </dl>
            {c.contact_id && <Link className="btn-secondary mt-4 w-full" href={`/contacts/${c.contact_id}`}>Open contact</Link>}
            {c.recording_url && <a className="btn-secondary mt-2 w-full" href={c.recording_url} target="_blank" rel="noreferrer">Recording</a>}
          </div>
          {c.extracted && Object.keys(c.extracted).length > 0 && (
            <div className="card text-sm">
              <h2 className="mb-2 font-semibold">Extracted data</h2>
              <dl className="space-y-1">{Object.entries(c.extracted).map(([k, v]) => <div key={k}><dt className="inline text-muted">{k}: </dt><dd className="inline">{String(v)}</dd></div>)}</dl>
            </div>
          )}
          <div className="card text-sm">
            <h2 className="mb-2 font-semibold">Provider events</h2>
            <ul className="space-y-1">{c.events.map((e, i) => <li key={i}>{e.type} <span className="text-xs text-muted">{fmtDate(e.at)}</span> {!e.applied && <Badge tone="grey">ignored (stale)</Badge>}</li>)}</ul>
          </div>
        </div>
      </div>
    </div>
  );
}
