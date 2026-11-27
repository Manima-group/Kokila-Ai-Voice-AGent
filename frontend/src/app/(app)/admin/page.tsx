"use client";

import { useState } from "react";

import { Badge, ErrorBox, Field, Loading, Modal, PageHeader, Stat, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, fmtDate, fmtINR } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Health = { database: string; redis: string; tenants: { active: number; suspended: number }; calls_24h: number; live_calls: number; webhooks_failed: number; outbox_pending: number; outbox_dead: number; job_failures_open: number };
type TenantRow = { id: string; name: string; status: string; created_at: string; users: number; calls_30d: number; plan: string | null; subscription_status: string | null; compliance_status: string; outbound_paused: boolean };
type Plan = { id: string; code: string; name: string; price_minor: number; included_minutes: number; max_agents: number; max_concurrent_calls: number; max_users: number; features: Record<string, boolean>; is_public: boolean; is_active: boolean; overage_per_minute_minor: number | null; interval_months: number };
const EMPTY_PLAN = { code: "", name: "", price_minor: 0, included_minutes: 0, overage_per_minute_minor: null as number | null, max_agents: 1, max_concurrent_calls: 1, max_users: 3, features: { outbound: false, calendar: true, integrations: true } as Record<string, boolean>, is_public: true, is_active: true, interval_months: 1 };

export default function Admin() {
  const { me } = useAuth();
  const health = useApi<Health>(me?.is_superadmin ? "/admin/health" : null, { refetchInterval: 30000 });
  const tenants = useApi<{ total: number; items: TenantRow[] }>(me?.is_superadmin ? "/admin/tenants" : null);
  const plans = useApi<Plan[]>(me?.is_superadmin ? "/admin/plans" : null);
  const ks = useApi<{ enabled: boolean; reason?: string }>(me?.is_superadmin ? "/admin/kill-switch" : null);
  const [plan, setPlan] = useState<typeof EMPTY_PLAN | null>(null);
  const [capsFor, setCapsFor] = useState<TenantRow | null>(null);
  const [error, setError] = useState<unknown>(null);

  if (!me?.is_superadmin) return <ErrorBox error={new Error("Super admin access required")} />;
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      tenants.refetch();
      plans.refetch();
      ks.refetch();
      health.refetch();
    } catch (e) {
      setError(e);
    }
  };
  const reason = (label: string) => window.prompt(`${label} — reason (audited):`) ?? "";

  return (
    <div>
      <PageHeader title="Super Admin" subtitle="Platform operations. Every action here is written to the platform audit log." />
      <ErrorBox error={error} />
      {health.isLoading ? <Loading /> : health.data && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Database / Redis" value={<><Badge tone={health.data.database === "ok" ? "green" : "red"}>{health.data.database}</Badge> <Badge tone={health.data.redis === "ok" ? "green" : "red"}>{health.data.redis}</Badge></>} />
          <Stat label="Tenants" value={health.data.tenants.active} hint={`${health.data.tenants.suspended} suspended`} />
          <Stat label="Calls (24h)" value={health.data.calls_24h} hint={`${health.data.live_calls} live now`} />
          <Stat label="Failures" value={health.data.webhooks_failed + health.data.outbox_dead + health.data.job_failures_open} hint={`webhooks ${health.data.webhooks_failed} · outbox dead ${health.data.outbox_dead} · jobs ${health.data.job_failures_open}`} />
        </div>
      )}
      <div className="card mt-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="font-semibold">Platform outbound kill switch</div>
          <div className="text-sm text-muted">{ks.data?.enabled ? `ENGAGED — ${ks.data.reason ?? ""}` : "Not engaged; campaigns dispatch normally (subject to all other checks)."}</div>
        </div>
        <button className={ks.data?.enabled ? "btn-primary" : "btn-danger"} onClick={() => {
          const r = reason(ks.data?.enabled ? "Release kill switch" : "Engage kill switch");
          if (r.length >= 3) run(() => api("/admin/kill-switch", { method: "PUT", body: { enabled: !ks.data?.enabled, reason: r } }));
        }}>{ks.data?.enabled ? "Release" : "Stop all outbound"}</button>
      </div>
      <h2 className="mb-3 mt-8 font-semibold">Tenants ({tenants.data?.total ?? 0})</h2>
      <Table head={["Name", "Status", "Plan", "Users", "Calls 30d", "Compliance", "Created", "Actions"]}>
        {tenants.data?.items.map((t) => (
          <tr key={t.id}>
            <td className="td font-medium">{t.name}</td>
            <td className="td"><Badge>{t.status}</Badge></td>
            <td className="td">{t.plan ?? "—"} {t.subscription_status && <Badge>{t.subscription_status}</Badge>}</td>
            <td className="td">{t.users}</td>
            <td className="td">{t.calls_30d}</td>
            <td className="td"><Badge>{t.compliance_status}</Badge></td>
            <td className="td">{fmtDate(t.created_at)}</td>
            <td className="td space-x-2 whitespace-nowrap text-sm">
              <button className="text-brand-700 hover:underline" onClick={() => { const r = reason(t.status === "active" ? "Suspend tenant" : "Reactivate tenant"); if (r.length >= 3) run(() => api(`/admin/tenants/${t.id}/status`, { method: "POST", body: { status: t.status === "active" ? "suspended" : "active", reason: r } })); }}>{t.status === "active" ? "Suspend" : "Reactivate"}</button>
              {t.compliance_status === "pending_review" && <>
                <button className="text-green-700 hover:underline" onClick={() => { const r = reason("Approve outbound compliance"); if (r.length >= 3) run(() => api(`/admin/tenants/${t.id}/compliance-decision`, { method: "POST", body: { approved: true, note: r } })); }}>Approve</button>
                <button className="text-red-600 hover:underline" onClick={() => { const r = reason("Reject outbound compliance"); if (r.length >= 3) run(() => api(`/admin/tenants/${t.id}/compliance-decision`, { method: "POST", body: { approved: false, note: r } })); }}>Reject</button>
              </>}
              <button className="font-medium text-brand-700 hover:underline" onClick={() => setCapsFor(t)}>Products &amp; features</button>
              <button className="text-brand-700 hover:underline" onClick={() => { const code = window.prompt("Assign plan code:"); const r = code ? reason("Assign plan") : ""; if (code && r.length >= 3) run(() => api(`/admin/tenants/${t.id}/plan`, { method: "POST", body: { plan_code: code, days: 30, reason: r } })); }}>Assign plan</button>
            </td>
          </tr>
        ))}
      </Table>
      <div className="mb-3 mt-8 flex items-center justify-between"><h2 className="font-semibold">Plans & entitlements</h2><button className="btn-primary" onClick={() => setPlan({ ...EMPTY_PLAN })}>New plan</button></div>
      <Table head={["Code", "Name", "Price", "Minutes", "Agents", "Concurrency", "Users", "Features", "Public", ""]}>
        {plans.data?.map((p) => (
          <tr key={p.id}>
            <td className="td font-mono text-xs">{p.code}</td><td className="td">{p.name}</td><td className="td">{fmtINR(p.price_minor)}</td><td className="td">{p.included_minutes}</td>
            <td className="td">{p.max_agents}</td><td className="td">{p.max_concurrent_calls}</td><td className="td">{p.max_users}</td>
            <td className="td text-xs">{Object.entries(p.features).filter(([, v]) => v).map(([k]) => k).join(", ")}</td>
            <td className="td">{p.is_public ? "yes" : "no"}</td>
            <td className="td"><button className="text-sm text-brand-700 hover:underline" onClick={() => setPlan({ ...EMPTY_PLAN, ...p })}>Edit</button></td>
          </tr>
        ))}
      </Table>
      {capsFor && <CapabilityModal tenant={capsFor} onClose={() => { setCapsFor(null); tenants.refetch(); }} />}
      <Modal open={!!plan} title={plan?.code ? `Plan ${plan.code}` : "New plan"} onClose={() => setPlan(null)}>
        {plan && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Code"><input className="input" value={plan.code} onChange={(e) => setPlan({ ...plan, code: e.target.value })} /></Field>
            <Field label="Name"><input className="input" value={plan.name} onChange={(e) => setPlan({ ...plan, name: e.target.value })} /></Field>
            <Field label="Price (paise, excl. GST)"><input className="input" type="number" value={plan.price_minor} onChange={(e) => setPlan({ ...plan, price_minor: Number(e.target.value) })} /></Field>
            <Field label="Included minutes"><input className="input" type="number" value={plan.included_minutes} onChange={(e) => setPlan({ ...plan, included_minutes: Number(e.target.value) })} /></Field>
            <Field label="Max agents"><input className="input" type="number" value={plan.max_agents} onChange={(e) => setPlan({ ...plan, max_agents: Number(e.target.value) })} /></Field>
            <Field label="Max concurrent calls"><input className="input" type="number" value={plan.max_concurrent_calls} onChange={(e) => setPlan({ ...plan, max_concurrent_calls: Number(e.target.value) })} /></Field>
            <Field label="Max users"><input className="input" type="number" value={plan.max_users} onChange={(e) => setPlan({ ...plan, max_users: Number(e.target.value) })} /></Field>
            <Field label="Overage paise/min (blank = hard cap)"><input className="input" type="number" value={plan.overage_per_minute_minor ?? ""} onChange={(e) => setPlan({ ...plan, overage_per_minute_minor: e.target.value === "" ? null : Number(e.target.value) })} /></Field>
            <div className="col-span-2 flex flex-wrap gap-4 text-sm">
              {["outbound", "calendar", "integrations"].map((f) => <label key={f} className="flex items-center gap-2"><input type="checkbox" checked={!!plan.features[f]} onChange={(e) => setPlan({ ...plan, features: { ...plan.features, [f]: e.target.checked } })} />{f}</label>)}
              <label className="flex items-center gap-2"><input type="checkbox" checked={plan.is_public} onChange={(e) => setPlan({ ...plan, is_public: e.target.checked })} />public</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={plan.is_active} onChange={(e) => setPlan({ ...plan, is_active: e.target.checked })} />active</label>
            </div>
            <button className="btn-primary col-span-2" onClick={() => run(async () => {
              const { code, name, price_minor, included_minutes, overage_per_minute_minor, max_agents, max_concurrent_calls, max_users, features, is_public, is_active, interval_months } = plan;
              await api("/admin/plans", { method: "PUT", body: { code, name, price_minor, included_minutes, overage_per_minute_minor, max_agents, max_concurrent_calls, max_users, features, is_public, is_active, interval_months } });
              setPlan(null);
            })}>Save plan</button>
          </div>
        )}
      </Modal>
    </div>
  );
}


type CapRow = { key: string; label: string; product: string; effective: boolean; source: string; plan_enabled: boolean; override: boolean | null };

function CapabilityModal({ tenant, onClose }: { tenant: TenantRow; onClose: () => void }) {
  const q = useApi<{ revision: number; capabilities: CapRow[] }>(`/admin/tenants/${tenant.id}/capabilities`);
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const change = async (key: string, enabled: boolean | null) => {
    const reason = window.prompt("Reason for this change (audited):") ?? "";
    if (reason.length < 3) return;
    setError(null); setMsg(null);
    try {
      const r = await api<{ cascaded: string[] }>(`/admin/tenants/${tenant.id}/capabilities`, { method: "PATCH", body: { changes: [{ key, enabled }], expected_revision: q.data!.revision, reason } });
      setMsg(r.cascaded.length ? `Also disabled dependent features: ${r.cascaded.join(", ")}` : "Saved.");
      q.refetch();
    } catch (e) { setError(e); q.refetch(); }
  };
  const groups: [string, string][] = [["calling_agent", "Calling Agent"], ["business_assistant", "Business Assistant"], ["platform", "Platform"]];
  return (
    <Modal open title={`${tenant.name} — products & features`} onClose={onClose}>
      {q.isLoading ? <Loading /> : (
        <div className="space-y-4 text-sm">
          <p className="text-muted">Effective access = plan package + overrides, minus platform kill switches. Every change is enforced by the API and audited. Revision {q.data?.revision}.</p>
          <ErrorBox error={error} />
          {msg && <p className="text-green-700">{msg}</p>}
          {groups.map(([g, label]) => (
            <div key={g}>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{label}</div>
              <ul className="divide-y divide-line rounded-lg border border-line">
                {q.data?.capabilities.filter((c) => c.product === g).map((c) => (
                  <li key={c.key} className="flex items-center justify-between gap-2 px-3 py-2">
                    <span>
                      <span className={c.key.startsWith("product.") ? "font-semibold" : ""}>{c.label}</span>{" "}
                      <Badge tone={c.effective ? "green" : "grey"}>{c.effective ? "on" : c.source.replace("_", " ")}</Badge>
                      {c.override !== null && <span className="ml-1 text-xs text-brand-700">override</span>}
                    </span>
                    <span className="flex gap-1">
                      <button className="btn-secondary px-2 py-1 text-xs" disabled={c.override === true} onClick={() => change(c.key, true)}>Enable</button>
                      <button className="btn-secondary px-2 py-1 text-xs" disabled={c.override === false} onClick={() => change(c.key, false)}>Disable</button>
                      {c.override !== null && <button className="btn-secondary px-2 py-1 text-xs" onClick={() => change(c.key, null)}>Use plan</button>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
