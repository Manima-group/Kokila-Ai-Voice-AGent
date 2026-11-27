"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Badge, ErrorBox, Field, Loading, Modal, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Connector = { key: string; name: string; category: string; auth: string; adapter: string; description: string; credential_fields: string[]; status: string; read_scopes: string[]; write_scopes: string[] };
type Conn = { id: string; connector_key: string; name: string; base_url: string; status: string; last_verified_at: string | null; last_error: string | null; verified_identity: string | null };

const STATUS: Record<string, [string, string]> = {
  connected: ["Connected", "green"], configured: ["Configured", "green"], failed: ["Needs attention", "red"],
  not_connected: ["Not connected", "grey"], not_available: ["Coming soon", "grey"],
};
const FIELD_LABEL: Record<string, string> = { base_url: "Site URL", api_key: "API key", api_secret: "API secret", access_token: "Access token" };

function Inner() {
  const { can } = useAuth();
  const params = useSearchParams();
  const cat = useApi<Connector[]>("/connect/connectors");
  const conns = useApi<Conn[]>(can("integrations:read") ? "/connect/connections" : null);
  const [open, setOpen] = useState<Connector | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<Conn | null>(null);

  const refresh = () => { cat.refetch(); conns.refetch(); };
  const connect = async () => {
    if (!open) return;
    setBusy(true); setError(null); setResult(null);
    try {
      const credentials = Object.fromEntries(open.credential_fields.filter((f) => f !== "base_url").map((f) => [f, form[f] ?? ""]));
      const r = await api<Conn>("/connect/connections", { method: "POST", body: { connector_key: open.key, name: form.name || open.name, base_url: form.base_url ?? "", credentials } });
      setResult(r);
      refresh();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const act = async (path: string) => {
    setError(null);
    try { await api(path, { method: "POST" }); refresh(); } catch (e) { setError(e); }
  };
  const google = async () => {
    setError(null);
    try { window.location.href = (await api<{ authorize_url: string }>("/integrations/google/authorize")).authorize_url; } catch (e) { setError(e); }
  };

  return (
    <div>
      <PageHeader title="Integrations" subtitle="Kokila Connect links your business software to both products. Connections are read-only by default and only show as connected after a live check succeeds." />
      {params.get("google") === "connected" && <div className="mb-3 rounded-lg bg-green-50 px-4 py-2 text-sm text-green-700">Google Calendar connected.</div>}
      {params.get("google") === "error" && <div className="mb-3 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">Google authorization failed.</div>}
      <ErrorBox error={error} />
      {cat.isLoading ? <Loading /> : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {cat.data?.map((c) => {
            const [label, tone] = STATUS[c.status] ?? [c.status, "grey"];
            return (
              <div key={c.key} className="card flex flex-col">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h2 className="font-semibold">{c.name}</h2>
                    <p className="text-xs uppercase tracking-wide text-muted">{c.category.replace("_", " / ")}</p>
                  </div>
                  <Badge tone={tone}>{label}</Badge>
                </div>
                <p className="mt-2 flex-1 text-sm text-muted">{c.description}</p>
                {c.read_scopes.length > 0 && <p className="mt-2 text-xs text-muted">Reads: {c.read_scopes.join(", ")}</p>}
                <div className="mt-4">
                  {c.adapter === "planned" ? <span className="text-sm text-muted">Adapter in development — not yet connectable.</span>
                    : !can("integrations:write") ? <span className="text-sm text-muted">Ask an admin to connect.</span>
                    : c.key === "google_calendar" ? <button className="btn-secondary" onClick={google}>{c.status === "connected" ? "Connect another" : "Connect with Google"}</button>
                    : c.key === "n8n" ? <Link className="btn-secondary" href="/calling-agent/automations">Configure webhooks</Link>
                    : <button className="btn-primary" onClick={() => { setOpen(c); setForm({ name: c.name }); setResult(null); setError(null); }}>{c.status === "connected" ? "Add connection" : "Connect"}</button>}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {!!conns.data?.length && (
        <section className="mt-8">
          <h2 className="mb-3 font-semibold">Your connections</h2>
          <ul className="space-y-2">
            {conns.data.map((c) => (
              <li key={c.id} className="card flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="text-sm">
                  <span className="font-medium">{c.name}</span> <span className="text-muted">({c.connector_key})</span> <Badge>{c.status}</Badge>
                  <div className="text-xs text-muted">{c.base_url} · {c.verified_identity ? `signed in as ${c.verified_identity}` : ""} {c.last_verified_at ? `· verified ${fmtDate(c.last_verified_at)}` : ""}</div>
                  {c.last_error && <div className="text-xs text-red-600">{c.last_error}</div>}
                </div>
                {can("integrations:write") && c.status !== "revoked" && (
                  <div className="flex gap-2">
                    <button className="btn-secondary" onClick={() => act(`/connect/connections/${c.id}/verify`)}>Test connection</button>
                    <button className="btn-secondary text-red-600" onClick={() => window.confirm("Revoke and delete stored credentials?") && act(`/connect/connections/${c.id}/revoke`)}>Revoke</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      <Modal open={!!open} title={`Connect ${open?.name ?? ""}`} onClose={() => setOpen(null)}>
        {open && (
          <div className="space-y-3">
            {open.key === "erpnext" && <p className="text-sm text-muted">In ERPNext open your user → API Access → Generate Keys. Use a read-only reporting user. Kokila stores keys encrypted and never shows them again.</p>}
            {open.key === "manima_hub" && <p className="text-sm text-muted">Manima Hub must expose the Kokila Connect endpoints (<code>/kokila/v1/manifest</code>). Use a scoped access token.</p>}
            <Field label="Connection name"><input className="input" value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            {open.credential_fields.map((f) => (
              <Field key={f} label={FIELD_LABEL[f] ?? f}>
                <input className="input" type={f === "base_url" ? "url" : "password"} autoComplete="off" value={form[f] ?? ""} placeholder={f === "base_url" ? "https://erp.yourcompany.com" : ""}
                  onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
              </Field>
            ))}
            <ErrorBox error={error} />
            {result && (result.status === "connected"
              ? <div className="rounded-lg bg-green-50 px-4 py-2 text-sm text-green-700">Connected and verified{result.verified_identity ? ` as ${result.verified_identity}` : ""}.</div>
              : <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">Saved but not connected: {result.last_error}</div>)}
            <button className="btn-primary" disabled={busy} onClick={connect}>{busy ? "Testing connection…" : "Save and test"}</button>
          </div>
        )}
      </Modal>
    </div>
  );
}

export default function IntegrationsPage() {
  return <Suspense><Inner /></Suspense>;
}
