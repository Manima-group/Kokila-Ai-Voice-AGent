"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Badge, Empty, ErrorBox, Field, Loading, Modal, PageHeader, Table } from "@/components/ui";
import { useApi, useMutate } from "@/hooks/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Page } from "@/types";

type Conn = { id: string; kind: string; name: string; target_url: string | null; event_types: string[]; status: string; created_at: string };
type Delivery = { id: string; event_type: string; status: string; attempts: number; last_error: string | null; created_at: string };

function IntegrationsInner() {
  const { can } = useAuth();
  const params = useSearchParams();
  const conns = useApi<Conn[]>("/integrations");
  const types = useApi<string[]>("/integrations/event-types");
  const deliveries = useApi<Page<Delivery>>("/integrations/deliveries?limit=20");
  const disable = useMutate<string>("POST", (id) => `/integrations/${id}/disable`, ["/integrations"], () => undefined);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ kind: "webhook", name: "", target_url: "", event_types: [] as string[] });
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const create = async () => {
    setError(null);
    try {
      const r = await api<{ signing_secret: string }>("/integrations", { method: "POST", body: form });
      setSecret(r.signing_secret);
      conns.refetch();
    } catch (e) {
      setError(e);
    }
  };
  const google = async () => {
    setError(null);
    try {
      const r = await api<{ authorize_url: string }>("/integrations/google/authorize");
      window.location.href = r.authorize_url;
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div>
      <PageHeader title="Automations" subtitle="Send signed Kokila events (calls, appointments, opt-outs) to n8n or any HTTPS webhook."
        actions={can("integrations:write") && <><button className="btn-secondary" onClick={google}>Connect Google Calendar</button><button className="btn-primary" onClick={() => { setSecret(null); setOpen(true); }}>Add webhook</button></>} />
      {params.get("google") === "connected" && <div className="mb-3 rounded-lg bg-green-50 px-4 py-2 text-sm text-green-700">Google Calendar connected.</div>}
      {params.get("google") === "error" && <div className="mb-3 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">Google authorization failed.</div>}
      <ErrorBox error={error || disable.error} />
      {conns.isLoading ? <Loading /> : conns.data?.length ? (
        <Table head={["Name", "Type", "URL", "Events", "Status", ""]}>
          {conns.data.map((c) => (
            <tr key={c.id}>
              <td className="td">{c.name}</td><td className="td">{c.kind}</td><td className="td max-w-xs truncate font-mono text-xs">{c.target_url}</td>
              <td className="td text-xs">{c.event_types.length ? c.event_types.join(", ") : "all"}</td><td className="td"><Badge>{c.status}</Badge></td>
              <td className="td">{c.status === "active" && can("integrations:write") && <button className="text-sm text-red-600 hover:underline" onClick={() => disable.mutate(c.id)}>Disable</button>}</td>
            </tr>
          ))}
        </Table>
      ) : <Empty title="No integrations" body="Send call, appointment and opt-out events to your CRM, n8n or any HTTPS endpoint." />}
      <h2 className="mb-3 mt-8 font-semibold">Recent deliveries</h2>
      {deliveries.data?.items.length ? (
        <Table head={["Event", "Status", "Attempts", "Last error", "Created"]}>
          {deliveries.data.items.map((d) => <tr key={d.id}><td className="td">{d.event_type}</td><td className="td"><Badge>{d.status}</Badge></td><td className="td">{d.attempts}</td><td className="td text-xs">{d.last_error ?? ""}</td><td className="td">{fmtDate(d.created_at)}</td></tr>)}
        </Table>
      ) : <p className="text-sm text-muted">No events yet.</p>}
      <Modal open={open} title="Add webhook endpoint" onClose={() => setOpen(false)}>
        {secret ? (
          <div className="space-y-3 text-sm">
            <p>Copy this signing secret now — it will not be shown again. Verify <code>X-Kokila-Signature</code> = <code>sha256=HMAC(secret, timestamp + &quot;.&quot; + body)</code>.</p>
            <code className="block break-all rounded bg-panel p-3">{secret}</code>
            <button className="btn-primary" onClick={() => setOpen(false)}>Done</button>
          </div>
        ) : (
          <div className="space-y-3">
            <Field label="Type"><select className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}><option value="webhook">Webhook</option><option value="n8n">n8n</option></select></Field>
            <Field label="Name"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="HTTPS URL"><input className="input" value={form.target_url} onChange={(e) => setForm({ ...form, target_url: e.target.value })} placeholder="https://…" /></Field>
            <fieldset><span className="label">Events (none = all)</span>
              <div className="grid grid-cols-2 gap-1 text-sm">{types.data?.map((t) => <label key={t} className="flex items-center gap-2"><input type="checkbox" checked={form.event_types.includes(t)} onChange={(e) => setForm({ ...form, event_types: e.target.checked ? [...form.event_types, t] : form.event_types.filter((x) => x !== t) })} />{t}</label>)}</div>
            </fieldset>
            <button className="btn-primary" onClick={create}>Create</button>
          </div>
        )}
      </Modal>
    </div>
  );
}

export default function Integrations() {
  return <Suspense><IntegrationsInner /></Suspense>;
}
