"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, ErrorBox, Field, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";

type Tenant = { id: string; name: string; timezone: string; industry: string | null; outbound_paused: boolean; compliance: Record<string, unknown> };
type Policy = { resource: string; retain_days: number };

export default function Settings() {
  const t = useApi<Tenant>("/tenants/current");
  if (t.isLoading || !t.data) return t.error ? <ErrorBox error={t.error} /> : <Loading />;
  return <SettingsForm key={t.data.id} tenant={t.data} refetch={() => t.refetch()} />;
}

function SettingsForm({ tenant, refetch }: { tenant: Tenant; refetch: () => void }) {
  const t = { data: tenant, refetch };
  const policies = useApi<Policy[]>("/retention-policies");
  const [org, setOrg] = useState({ name: tenant.name, timezone: tenant.timezone, industry: tenant.industry ?? "" });
  const [comp, setComp] = useState({ legal_name: "", dlt_entity_id: "", telemarketer_registration: "", gstin: "", attests_consent_collection: false, attests_recording_disclosure: false });
  const [ret, setRet] = useState({ resource: "transcripts", retain_days: 180 });
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setError(null);
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      t.refetch();
      policies.refetch();
    } catch (e) {
      setError(e);
    }
  };
  const c = t.data?.compliance ?? {};

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title="Organization settings" actions={<><Link className="btn-secondary" href="/team">Team</Link><Link className="btn-secondary" href="/audit">Audit log</Link></>} />
      <ErrorBox error={error} />
      {msg && <div className="rounded-lg bg-green-50 px-4 py-2 text-sm text-green-700">{msg}</div>}
      <section className="card space-y-3">
        <h2 className="font-semibold">Profile</h2>
        <Field label="Organization name"><input className="input" value={org.name} onChange={(e) => setOrg({ ...org, name: e.target.value })} /></Field>
        <Field label="Timezone"><input className="input" value={org.timezone} onChange={(e) => setOrg({ ...org, timezone: e.target.value })} /></Field>
        <Field label="Industry"><input className="input" value={org.industry} onChange={(e) => setOrg({ ...org, industry: e.target.value })} /></Field>
        <button className="btn-primary" onClick={() => run(() => api("/tenants/current", { method: "PATCH", body: org }), "Profile saved.")}>Save</button>
      </section>
      <section className="card space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Outbound emergency stop</h2>
          {t.data?.outbound_paused ? <Badge tone="red">all outbound paused</Badge> : <Badge tone="green">outbound allowed</Badge>}
        </div>
        <p className="text-sm text-muted">Immediately stops dispatching any new outbound calls for every campaign in your organization.</p>
        <button className={t.data?.outbound_paused ? "btn-primary" : "btn-danger"}
          onClick={() => run(() => api(`/tenants/current/outbound-pause?paused=${!t.data?.outbound_paused}`, { method: "POST" }), "Updated.")}>
          {t.data?.outbound_paused ? "Resume outbound" : "Pause all outbound now"}
        </button>
      </section>
      <section className="card space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Telecom compliance profile</h2>
          <Badge>{String(c.status ?? "not_submitted")}</Badge>
        </div>
        <p className="text-sm text-muted">Required before live outbound campaigns. A Kokila administrator reviews your TRAI/DLT registration details. See the compliance checklist in the docs.</p>
        <Field label="Registered legal name"><input className="input" value={comp.legal_name} onChange={(e) => setComp({ ...comp, legal_name: e.target.value })} /></Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="DLT entity ID"><input className="input" value={comp.dlt_entity_id} onChange={(e) => setComp({ ...comp, dlt_entity_id: e.target.value })} /></Field>
          <Field label="Telemarketer reg."><input className="input" value={comp.telemarketer_registration} onChange={(e) => setComp({ ...comp, telemarketer_registration: e.target.value })} /></Field>
          <Field label="GSTIN"><input className="input" value={comp.gstin} onChange={(e) => setComp({ ...comp, gstin: e.target.value })} /></Field>
        </div>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={comp.attests_consent_collection} onChange={(e) => setComp({ ...comp, attests_consent_collection: e.target.checked })} />We collect and retain verifiable consent before calling customers for commercial purposes.</label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={comp.attests_recording_disclosure} onChange={(e) => setComp({ ...comp, attests_recording_disclosure: e.target.checked })} />Our agents disclose they are automated and disclose call recording.</label>
        <button className="btn-primary" onClick={() => run(() => api("/tenants/current/compliance", { method: "PUT", body: { ...comp, dlt_entity_id: comp.dlt_entity_id || null, telemarketer_registration: comp.telemarketer_registration || null, gstin: comp.gstin || null } }), "Submitted for review.")}>Submit for review</button>
      </section>
      <section className="card space-y-3">
        <h2 className="font-semibold">Data retention</h2>
        <ul className="text-sm">{policies.data?.map((p) => <li key={p.resource}>{p.resource}: {p.retain_days} days</li>)}{!policies.data?.length && <li className="text-muted">No custom policies (data retained until deleted).</li>}</ul>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Resource"><select className="input" value={ret.resource} onChange={(e) => setRet({ ...ret, resource: e.target.value })}>{["transcripts", "recordings", "call_events"].map((r) => <option key={r}>{r}</option>)}</select></Field>
          <Field label="Days"><input className="input w-28" type="number" value={ret.retain_days} onChange={(e) => setRet({ ...ret, retain_days: Number(e.target.value) })} /></Field>
          <button className="btn-secondary" onClick={() => run(() => api("/retention-policies", { method: "PUT", body: ret }), "Retention policy saved.")}>Save policy</button>
        </div>
      </section>
    </div>
  );
}
