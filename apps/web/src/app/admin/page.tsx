"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Footer, Header } from "@/components/Brand";
import { api, KokilaApiError } from "@/lib/api";

type Tenant = { id: string; name: string; type: string; status: string; policy_revision: number; revision: number;
                plan_code: string | null; enabled_count: number | null };
type Cap = { key: string; requirement_id: string; module: string; description: string; purchasable: boolean;
             dependencies: string[]; platform_enabled: boolean; control_revision: number };
type EffCap = { key: string; enabled: boolean; source: string; reason: string | null };
type Detail = { tenant: Tenant; subscription: { plan_code: string | null; plan_version: number | null } | null;
                member_count: number; policy: { revision: number; capabilities: Record<string, EffCap> } };
type Plan = { code: string; version: number; name: string; price_minor: number; capabilities: string[] };
type AuditItem = { id: string; action: string; target_ref: string; reason: string; created_at: string };

export default function AdminPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"tenants" | "controls" | "audit">("tenants");
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [q, setQ] = useState("");
  const [caps, setCaps] = useState<Cap[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [sel, setSel] = useState<Detail | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditItem[]>([]);
  const [denied, setDenied] = useState(false);

  const onErr = useCallback((e: unknown) => {
    if (e instanceof KokilaApiError && e.status === 401) { router.replace("/login"); return; }
    if (e instanceof KokilaApiError && (e.status === 403)) { setDenied(true); }
    const d = e instanceof KokilaApiError ? e.error.details as { dependency_conflicts?: unknown[] } | undefined : undefined;
    setMsg(e instanceof KokilaApiError
      ? `${e.error.message}${d?.dependency_conflicts ? `: ${JSON.stringify(d.dependency_conflicts)}` : ""}`
      : "Network error");
  }, [router]);

  const [tenantsVersion, setTenantsVersion] = useState(0);
  const loadTenants = useCallback(async () => setTenantsVersion((v) => v + 1), []);

  useEffect(() => {
    let alive = true;
    api.get<{ items: Tenant[] }>(`platform/tenants?limit=100${q ? `&q=${encodeURIComponent(q)}` : ""}`)
      .then((r) => { if (alive) setTenants(r.items); }).catch((e) => { if (alive) onErr(e); });
    return () => { alive = false; };
  }, [q, tenantsVersion, onErr]);

  useEffect(() => {
    api.get<{ items: Cap[] }>("platform/capabilities").then((r) => setCaps(r.items)).catch(onErr);
    api.get<{ items: Plan[] }>("platform/plans").then((r) => setPlans(r.items)).catch(onErr);
  }, [onErr]);

  async function open(id: string) {
    try { setSel(await api.get<Detail>(`platform/tenants/${id}`)); setPending({}); setMsg(null); } catch (e) { onErr(e); }
  }

  const effective = useMemo(() => {
    if (!sel) return {} as Record<string, boolean>;
    const base = Object.fromEntries(Object.entries(sel.policy.capabilities).map(([k, v]) => [k, v.enabled]));
    return { ...base, ...pending };
  }, [sel, pending]);

  const depWarnings = useMemo(() => caps.filter((c) => effective[c.key] && c.purchasable)
    .flatMap((c) => c.dependencies.filter((d) => !effective[d]).map((d) => `${c.key} needs ${d}`)), [caps, effective]);

  async function saveEntitlements() {
    if (!sel) return;
    const changes = Object.entries(pending).map(([key, enabled]) => ({ key, enabled }));
    if (!changes.length) return;
    if (!window.confirm(`Apply ${changes.length} change(s) to ${sel.tenant.name}? Disabling stops new operations immediately.`)) return;
    try {
      const r = await api.patch<{ revision: number; effective_capabilities: string[]; audit_id: string }>(
        `platform/tenants/${sel.tenant.id}/entitlements`,
        { changes, expected_revision: sel.policy.revision, reason });
      setMsg(`Saved. Policy revision ${r.revision}. Audit ${r.audit_id.slice(0, 8)}.`);
      setReason("");
      await open(sel.tenant.id);
      await loadTenants();
    } catch (e) { onErr(e); }
  }

  async function changePlan(code: string) {
    if (!sel || !code) return;
    if (!window.confirm(`Move ${sel.tenant.name} to ${code}? Capabilities not in the new plan stop immediately.`)) return;
    try {
      await api.put(`platform/tenants/${sel.tenant.id}/subscription`,
        { plan_code: code, expected_revision: sel.policy.revision, reason: reason || `plan change to ${code}` });
      setMsg(`Plan changed to ${code}. Billing proration is reconciled separately; no charge was made.`);
      await open(sel.tenant.id);
      await loadTenants();
    } catch (e) { onErr(e); }
  }

  async function setStatus(status: "active" | "suspended") {
    if (!sel || !reason) { setMsg("Enter a reason first."); return; }
    try {
      await api.patch(`platform/tenants/${sel.tenant.id}/status`,
        { status, expected_revision: sel.tenant.revision, reason });
      await open(sel.tenant.id);
      await loadTenants();
    } catch (e) { onErr(e); }
  }

  async function toggleControl(c: Cap) {
    const why = window.prompt(`Reason for ${c.platform_enabled ? "disabling" : "enabling"} ${c.key} for ALL tenants:`);
    if (!why || why.length < 3) return;
    try {
      await api.patch(`platform/capabilities/${c.key}`,
        { enabled: !c.platform_enabled, expected_revision: c.control_revision, reason: why });
      setCaps((await api.get<{ items: Cap[] }>("platform/capabilities")).items);
    } catch (e) { onErr(e); }
  }

  useEffect(() => {
    if (tab === "audit") api.get<{ items: AuditItem[] }>("platform/audit?limit=100").then((r) => setAudit(r.items)).catch(onErr);
  }, [tab, onErr]);

  if (denied && !tenants.length) {
    return (<><Header subtitle="MANIMA PLATFORM" /><main className="mx-auto max-w-xl p-6">
      <p className="k-card p-4">Platform administration needs a Manima platform session with two-factor authentication.
        Sign in with “Manima platform administration” checked.</p></main></>);
  }

  const modules = Array.from(new Set(caps.map((c) => c.module)));
  return (
    <>
      <Header subtitle="MANIMA SUPER ADMIN" right={<>
        {(["tenants", "controls", "audit"] as const).map((t) => (
          <button key={t} className={tab === t ? "k-btn-primary" : "k-btn"} onClick={() => setTab(t)}>{t[0]!.toUpperCase() + t.slice(1)}</button>
        ))}
        <button className="k-btn" onClick={async () => { await api.logout(); router.replace("/login"); }}>Sign out</button>
      </>} />
      <main className="mx-auto max-w-5xl px-4 py-6">
        {msg && <p role="status" className="k-card mb-4 p-3 text-sm">{msg}</p>}
        {tab === "tenants" && (
          <div className="grid gap-4 md:grid-cols-[280px_1fr]">
            <aside className="k-card p-3">
              <input className="k-input mb-2" placeholder="Search tenants" aria-label="Search tenants" value={q}
                     onChange={(e) => setQ(e.target.value)} />
              <ul className="max-h-[70vh] space-y-1 overflow-auto">
                {tenants.map((t) => (
                  <li key={t.id}>
                    <button onClick={() => open(t.id)} className={`w-full rounded-lg px-2 py-2 text-left text-sm hover:bg-k-yellow-50 ${sel?.tenant.id === t.id ? "bg-k-yellow-100" : ""}`}>
                      <span className="block font-medium">{t.name}</span>
                      <span className="text-xs text-k-grey-600">{t.type} · {t.status} · {t.plan_code ?? "no plan"} · {t.enabled_count ?? 0} features</span>
                    </button>
                  </li>
                ))}
                {!tenants.length && <li className="p-2 text-sm text-k-grey-600">No tenants.</li>}
              </ul>
            </aside>
            <section>
              {!sel ? <p className="k-card p-4 text-sm text-k-grey-600">Select a tenant to manage its package.</p> : (
                <div className="space-y-4">
                  <div className="k-card p-4">
                    <h1 className="text-xl font-bold">{sel.tenant.name}</h1>
                    <p className="text-sm text-k-grey-600">{sel.tenant.type} · {sel.tenant.status} · {sel.member_count} members ·
                      plan {sel.subscription?.plan_code ?? "none"} v{sel.subscription?.plan_version ?? "-"} · policy rev {sel.policy.revision}</p>
                    <div className="mt-3 flex flex-wrap items-end gap-2">
                      <div className="min-w-60 flex-1">
                        <label className="k-label" htmlFor="reason">Reason (required, audited)</label>
                        <input id="reason" className="k-input" value={reason} onChange={(e) => setReason(e.target.value)} />
                      </div>
                      <select className="k-input w-auto" aria-label="Change plan" value="" onChange={(e) => changePlan(e.target.value)}>
                        <option value="">Change plan…</option>
                        {plans.map((p) => <option key={`${p.code}-${p.version}`} value={p.code}>{p.name} (₹{(p.price_minor / 100).toLocaleString("en-IN")})</option>)}
                      </select>
                      {sel.tenant.status === "active"
                        ? <button className="k-btn-danger" onClick={() => setStatus("suspended")}>Suspend</button>
                        : <button className="k-btn" onClick={() => setStatus("active")}>Reactivate</button>}
                    </div>
                  </div>
                  <div className="k-card p-4">
                    <div className="mb-2 flex items-center justify-between">
                      <h2 className="font-semibold">Capability matrix</h2>
                      <span className="text-sm text-k-grey-600">
                        {caps.filter((c) => c.purchasable && effective[c.key]).length} enabled · {Object.keys(pending).length} pending
                      </span>
                    </div>
                    {depWarnings.length > 0 && <p className="mb-2 text-sm text-k-danger">Dependency warnings: {depWarnings.join("; ")}</p>}
                    {modules.map((m) => (
                      <fieldset key={m} className="mb-3">
                        <legend className="k-label">{m}</legend>
                        <div className="grid gap-1 sm:grid-cols-2">
                          {caps.filter((c) => c.module === m).map((c) => {
                            const cur = sel.policy.capabilities[c.key];
                            const on = !!effective[c.key];
                            return (
                              <label key={c.key} className={`flex items-start gap-2 rounded-lg p-2 text-sm ${c.key in pending ? "bg-k-yellow-50" : ""}`}>
                                <input type="checkbox" checked={on} disabled={!c.purchasable}
                                       onChange={(e) => setPending((p) => {
                                         const next = { ...p, [c.key]: e.target.checked };
                                         if (cur && cur.enabled === e.target.checked && cur.source !== "none") delete next[c.key];
                                         return next;
                                       })} />
                                <span>
                                  <span className="font-medium">{c.key}</span> <span className="text-xs text-k-grey-600">{c.requirement_id}</span>
                                  <span className="block text-xs text-k-grey-600">{c.description}
                                    {!c.purchasable && " · mandatory infrastructure"}
                                    {cur && !cur.enabled && cur.reason && ` · ${cur.reason}`}
                                    {!c.platform_enabled && " · platform kill switch ON"}</span>
                                </span>
                              </label>
                            );
                          })}
                        </div>
                      </fieldset>
                    ))}
                    <button className="k-btn-primary" onClick={saveEntitlements}
                            disabled={!Object.keys(pending).length || reason.length < 3}>Save package changes</button>
                  </div>
                </div>
              )}
            </section>
          </div>
        )}
        {tab === "controls" && (
          <div className="k-card p-4">
            <h1 className="mb-1 text-xl font-bold">Platform kill switches</h1>
            <p className="mb-3 text-sm text-k-grey-600">Disabling a capability here blocks it for every tenant immediately.</p>
            <ul className="divide-y divide-k-grey-100">
              {caps.filter((c) => c.purchasable).map((c) => (
                <li key={c.key} className="flex items-center justify-between py-2 text-sm">
                  <span><span className="font-medium">{c.key}</span> <span className="text-k-grey-600">{c.description}</span></span>
                  <button className={c.platform_enabled ? "k-btn" : "k-btn-danger"} onClick={() => toggleControl(c)}>
                    {c.platform_enabled ? "Enabled — disable" : "Disabled — enable"}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {tab === "audit" && (
          <div className="k-card overflow-x-auto p-4">
            <h1 className="mb-3 text-xl font-bold">Platform audit</h1>
            <table className="w-full text-left text-sm">
              <thead><tr className="text-k-grey-600"><th className="py-1">When</th><th>Action</th><th>Target</th><th>Reason</th></tr></thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id} className="border-t border-k-grey-100">
                    <td className="py-1.5 pr-3">{new Date(a.created_at).toLocaleString()}</td><td className="pr-3">{a.action}</td>
                    <td className="pr-3">{a.target_ref}</td><td>{a.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
      <Footer />
    </>
  );
}
