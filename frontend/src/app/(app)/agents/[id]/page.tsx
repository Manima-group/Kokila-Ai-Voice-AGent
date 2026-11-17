"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Badge, ErrorBox, Field, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Agent, AgentConfig } from "@/types";

type Detail = Agent & {
  latest: { id: string; version: number; config: AgentConfig; published_at: string | null } | null;
  language_support: Record<string, { adapter_supported: boolean; live_verified: boolean }>;
};
type Templates = { languages: Record<string, string>; tools: Record<string, string> };
type Version = { id: string; version: number; published_at: string | null; created_at: string };
type Source = { id: string; name: string; agent_id: string | null };
type Doc = { id: string; title: string; flagged_injection: boolean; created_at: string };

export default function AgentEditor() {
  const { id } = useParams<{ id: string }>();
  const detail = useApi<Detail>(`/agents/${id}`);
  const meta = useApi<Templates>("/agents/templates");
  if (detail.isLoading || !detail.data?.latest || !meta.data) return detail.error ? <ErrorBox error={detail.error} /> : <Loading />;
  return <Editor key={detail.data.latest.id} id={id} a={detail.data} meta={meta.data} initial={detail.data.latest.config} />;
}

function Editor({ id, a, meta, initial }: { id: string; a: Detail; meta: Templates; initial: AgentConfig }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const versions = useApi<Version[]>(`/agents/${id}/versions`);
  const [cfg, setCfg] = useState<AgentConfig>(initial);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const editable = can("agents:write");
  const set = <K extends keyof AgentConfig>(k: K, v: AgentConfig[K]) => setCfg({ ...cfg, [k]: v });
  const refresh = () => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[1]).startsWith(`/agents/${id}`) });

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(ok);
      await refresh();
    } catch (e) {
      setError(e);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const saveVersion = () => run(() => api(`/agents/${id}/versions`, { method: "POST", body: cfg }), "Saved as a new draft version.");
  const publish = (v: number) => run(() => api(`/agents/${id}/versions/${v}/publish`, { method: "POST" }), `Version ${v} published and synced to ${a.provider}.`);

  return (
    <div>
      <PageHeader title={a.name} subtitle={`${a.template.replace(/_/g, " ")} · provider: ${a.provider}`}
        actions={<><Badge>{a.status}</Badge><Badge tone={a.sync_status === "synced" ? "green" : a.sync_status === "failed" ? "red" : "grey"}>{a.sync_status}</Badge></>} />
      <div className="space-y-3">
        <ErrorBox error={error} />
        {a.sync_error && <ErrorBox error={new Error(`Last provider sync error: ${a.sync_error}`)} />}
        {notice && <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">{notice}</div>}
      </div>
      <div className="mt-4 grid gap-6 lg:grid-cols-3">
        <div className="card space-y-4 lg:col-span-2">
          <h2 className="font-semibold">Configuration</h2>
          <fieldset disabled={!editable} className="space-y-4">
            <div>
              <span className="label">Languages</span>
              <div className="flex flex-wrap gap-3">
                {Object.entries(meta.languages).map(([code, name]) => (
                  <label key={code} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={cfg.languages.includes(code)}
                      onChange={(e) => set("languages", e.target.checked ? [...cfg.languages, code] : cfg.languages.filter((l) => l !== code))} />
                    {name}
                    {a.language_support[code] && (
                      <span className="text-xs text-muted">({a.language_support[code].adapter_supported ? "provider-supported" : "not supported by provider"}, {a.language_support[code].live_verified ? "verified" : "live test pending"})</span>
                    )}
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-muted">The first selected language is the agent&apos;s primary language.</p>
            </div>
            <Field label="Voice ID" hint="Provider voice identifier (e.g. a Retell voice id)"><input className="input" value={cfg.voice_id} onChange={(e) => set("voice_id", e.target.value)} /></Field>
            <Field label="Greeting"><textarea className="input" rows={2} value={cfg.greeting} onChange={(e) => set("greeting", e.target.value)} /></Field>
            <Field label="Instructions"><textarea className="input" rows={6} value={cfg.instructions} onChange={(e) => set("instructions", e.target.value)} /></Field>
            <Field label="Business rules" hint="One rule per line, e.g. 'Never quote prices; offer a callback.'">
              <textarea className="input" rows={4} value={cfg.business_rules.join("\n")} onChange={(e) => set("business_rules", e.target.value.split("\n").filter((x) => x.trim()))} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Opens"><input className="input" value={cfg.business_hours.start} onChange={(e) => set("business_hours", { ...cfg.business_hours, start: e.target.value })} /></Field>
              <Field label="Closes"><input className="input" value={cfg.business_hours.end} onChange={(e) => set("business_hours", { ...cfg.business_hours, end: e.target.value })} /></Field>
              <Field label="Max call (seconds)"><input className="input" type="number" value={cfg.max_call_seconds} onChange={(e) => set("max_call_seconds", Number(e.target.value))} /></Field>
            </div>
            <div>
              <span className="label">Allowed tools</span>
              <div className="space-y-1">
                {Object.entries(meta.tools).map(([name, desc]) => (
                  <label key={name} className="flex items-start gap-2 text-sm">
                    <input type="checkbox" className="mt-1" checked={cfg.allowed_tools.includes(name)}
                      onChange={(e) => set("allowed_tools", e.target.checked ? [...cfg.allowed_tools, name] : cfg.allowed_tools.filter((x) => x !== name))} />
                    <span><span className="font-medium">{name.replace(/_/g, " ")}</span> <span className="text-muted">— {desc}</span></span>
                  </label>
                ))}
              </div>
            </div>
            <Field label="Human transfer number" hint="E.164 or 10-digit Indian number; used for live transfers">
              <input className="input" value={cfg.escalation.transfer_number ?? ""} onChange={(e) => set("escalation", { ...cfg.escalation, transfer_number: e.target.value || null })} />
            </Field>
          </fieldset>
          {editable && <button className="btn-primary" disabled={busy} onClick={saveVersion}>Save as new version</button>}
        </div>
        <div className="space-y-6">
          <div className="card">
            <h2 className="mb-3 font-semibold">Versions</h2>
            <ul className="divide-y divide-line">
              {versions.data?.map((v) => (
                <li key={v.id} className="flex items-center justify-between py-2 text-sm">
                  <span>v{v.version} {a.published_version_id === v.id && <Badge tone="green">live</Badge>}<span className="block text-xs text-muted">{fmtDate(v.created_at)}</span></span>
                  {can("agents:publish") && a.published_version_id !== v.id && <button className="btn-secondary" disabled={busy} onClick={() => publish(v.version)}>Publish</button>}
                </li>
              ))}
            </ul>
          </div>
          <Knowledge agentId={id} editable={editable} />
        </div>
      </div>
    </div>
  );
}

function Knowledge({ agentId, editable }: { agentId: string; editable: boolean }) {
  const sources = useApi<Source[]>("/agents/knowledge/sources");
  const mine = sources.data?.find((s) => s.agent_id === agentId);
  const docs = useApi<Doc[]>(mine ? `/agents/knowledge/sources/${mine.id}/documents` : null);
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState<unknown>(null);

  const add = async () => {
    setError(null);
    try {
      const src = mine ?? (await api<Source>("/agents/knowledge/sources", { method: "POST", body: { name: "Agent knowledge", agent_id: agentId } }));
      await api(`/agents/knowledge/sources/${src.id}/documents`, { method: "POST", body: { title, content } });
      setTitle("");
      setContent("");
      qc.invalidateQueries({ predicate: (q) => String(q.queryKey[1]).startsWith("/agents/knowledge") });
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div className="card">
      <h2 className="mb-1 font-semibold">Knowledge base</h2>
      <p className="mb-3 text-xs text-muted">Used as reference data on next publish. Documents that look like prompt-injection are flagged and excluded.</p>
      <ul className="mb-3 divide-y divide-line text-sm">
        {docs.data?.map((d) => <li key={d.id} className="py-2">{d.title} {d.flagged_injection && <Badge tone="red">excluded: suspicious</Badge>}</li>)}
        {!docs.data?.length && <li className="py-2 text-muted">No documents yet.</li>}
      </ul>
      {editable && (
        <div className="space-y-2">
          <ErrorBox error={error} />
          <input className="input" placeholder="Title (e.g. Fee structure 2026)" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea className="input" rows={4} placeholder="Paste approved FAQ or policy text" value={content} onChange={(e) => setContent(e.target.value)} />
          <button className="btn-secondary" disabled={!title || !content} onClick={add}>Add document</button>
        </div>
      )}
    </div>
  );
}
