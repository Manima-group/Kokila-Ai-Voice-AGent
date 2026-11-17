"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Badge, ErrorBox, Field, Loading, Modal, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Contact } from "@/types";

type Consent = { id: string; purpose: string; status: string; source: string; evidence: string | null; granted_at: string; expires_at: string | null };
type Detail = Contact & {
  leads: { id: string; status: string; score: number }[];
  consents: Consent[];
  suppressed: boolean;
  suppression_reason: string | null;
  timeline: { type: string; at: string; id?: string; status?: string; outcome?: string; body?: string; direction?: string }[];
};

export default function ContactDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { can } = useAuth();
  const q = useApi<Detail>(`/contacts/${id}`);
  const [open, setOpen] = useState(false);
  const [consent, setConsent] = useState({ purpose: "sales", source: "web_form", evidence: "", expires_at: "" });
  const [error, setError] = useState<unknown>(null);

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const c = q.data!;
  const call = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      q.refetch();
      return true;
    } catch (e) {
      setError(e);
      return false;
    }
  };

  return (
    <div>
      <PageHeader title={c.name ?? c.phone_e164} subtitle={`${c.phone_e164}${c.email ? ` · ${c.email}` : ""}`}
        actions={<>
          {c.suppressed ? <Badge tone="red">suppressed: {c.suppression_reason}</Badge> : <Badge tone="green">callable with consent</Badge>}
          {can("consent:write") && !c.suppressed && <button className="btn-secondary" onClick={() => call(() => api("/suppression", { method: "POST", body: { phone: c.phone_e164, reason: "opt_out" } }))}>Record opt-out</button>}
          {can("contacts:delete") && <button className="btn-danger" onClick={async () => {
            if (window.confirm("Permanently erase this contact's personal data? Call content will be redacted and the number suppressed.")) {
              if (await call(() => api("/deletion-requests", { method: "POST", body: { contact_id: id, reason: "Erasure requested" } }))) router.replace("/contacts");
            }
          }}>Erase data</button>}
        </>} />
      <ErrorBox error={error} />
      <div className="mt-4 grid gap-6 lg:grid-cols-3">
        <section className="card lg:col-span-2">
          <h2 className="mb-3 font-semibold">Timeline</h2>
          {c.timeline.length ? (
            <ol className="space-y-3 border-l-2 border-brand-100 pl-4">
              {c.timeline.map((e, i) => (
                <li key={i} className="text-sm">
                  <div className="text-xs text-muted">{fmtDate(e.at)} · {e.type}</div>
                  {e.type === "call" ? (
                    <Link className="text-brand-700 hover:underline" href={`/calls/${e.id}`}>{e.direction} call — {e.status}{e.outcome ? ` (${e.outcome})` : ""}</Link>
                  ) : <div>{e.body}</div>}
                </li>
              ))}
            </ol>
          ) : <p className="text-sm text-muted">No activity yet.</p>}
        </section>
        <div className="space-y-6">
          <section className="card">
            <h2 className="mb-2 font-semibold">Leads</h2>
            {c.leads.length ? c.leads.map((l) => <div key={l.id} className="text-sm"><Badge>{l.status}</Badge> score {l.score}</div>) : <p className="text-sm text-muted">No lead yet.</p>}
          </section>
          <section className="card">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-semibold">Consent records</h2>
              {can("consent:write") && <button className="btn-secondary" onClick={() => setOpen(true)}>Record consent</button>}
            </div>
            <ul className="space-y-2 text-sm">
              {c.consents.map((x) => (
                <li key={x.id} className="rounded-lg bg-panel p-2">
                  <div><Badge>{x.status === "granted" ? "granted" : "revoked"}</Badge> <span className="font-medium">{x.purpose}</span> via {x.source}</div>
                  <div className="text-xs text-muted">Granted {fmtDate(x.granted_at)}{x.expires_at ? ` · expires ${fmtDate(x.expires_at)}` : ""}</div>
                  <div className="text-xs">{x.evidence}</div>
                  {x.status === "granted" && can("consent:write") && <button className="mt-1 text-xs text-red-600 hover:underline" onClick={() => call(() => api(`/contacts/${id}/consents/${x.id}/revoke`, { method: "POST" }))}>Revoke</button>}
                </li>
              ))}
              {!c.consents.length && <li className="text-muted">No consent recorded — outbound campaigns will skip this contact.</li>}
            </ul>
          </section>
        </div>
      </div>
      <Modal open={open} title="Record consent" onClose={() => setOpen(false)}>
        <div className="space-y-3">
          <Field label="Purpose" hint="Must match the campaign purpose (e.g. sales, service, appointment_reminder)"><input className="input" value={consent.purpose} onChange={(e) => setConsent({ ...consent, purpose: e.target.value })} /></Field>
          <Field label="Source"><select className="input" value={consent.source} onChange={(e) => setConsent({ ...consent, source: e.target.value })}>{["web_form", "ivr", "written", "call_recording", "whatsapp_optin", "in_person"].map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Evidence" hint="Reference to verifiable proof (form id, recording id, document)"><textarea className="input" rows={3} value={consent.evidence} onChange={(e) => setConsent({ ...consent, evidence: e.target.value })} /></Field>
          <Field label="Expires (optional)"><input className="input" type="date" value={consent.expires_at} onChange={(e) => setConsent({ ...consent, expires_at: e.target.value })} /></Field>
          <button className="btn-primary" disabled={consent.evidence.length < 3} onClick={async () => {
            const ok = await call(() => api(`/contacts/${id}/consents`, { method: "POST", body: { purpose: consent.purpose, source: consent.source, evidence: consent.evidence, expires_at: consent.expires_at ? new Date(consent.expires_at).toISOString() : null } }));
            if (ok) setOpen(false);
          }}>Save consent</button>
        </div>
      </Modal>
    </div>
  );
}
