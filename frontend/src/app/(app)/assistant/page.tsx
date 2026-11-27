"use client";

import Link from "next/link";
import { useState } from "react";

import { Icon } from "@/components/icons";
import { ErrorBox, Field, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Config = {
  llm: { configured: boolean; provider: string | null; model: string | null };
  modes: { business: boolean; personal: boolean };
  research: boolean;
  preferences: { assistant_name: string; language: string; wake_phrase: string | null; response_length: string };
  custom_name_allowed: boolean;
};

export default function AssistantHome() {
  const { can } = useAuth();
  const cfg = useApi<Config>("/assistant/config");
  if (cfg.isLoading) return <Loading />;
  if (cfg.error) return <ErrorBox error={cfg.error} />;
  const c = cfg.data!;
  return (
    <div>
      <PageHeader title="Business Assistant" subtitle="Choose a mode. Business data and personal data are kept separate." />
      {!c.llm.configured && (
        <div className="mb-6 rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-800">
          The conversational AI model is not configured on this deployment. Quick reports from connected systems still work; chat needs an LLM provider and model set by the platform administrator.
        </div>
      )}
      <div className="grid gap-6 md:grid-cols-2">
        <ModeCard title="Business mode" icon="chart" href="/assistant/business" enabled={can("analytics:read")}
          body="Talk to your connected business data: sales, revenue, stock, overdue invoices, appointments and follow-ups — with charts, tables and downloadable reports." />
        <ModeCard title="Personal mode" icon="user" href="/assistant/personal" enabled={c.modes.personal}
          body="A private assistant for you: conversations, reminders and memory you control. It never sees company business data." />
      </div>
      <Preferences c={c} onSaved={() => cfg.refetch()} />
    </div>
  );
}

function ModeCard({ title, icon, href, body, enabled }: { title: string; icon: "chart" | "user"; href: string; body: string; enabled: boolean }) {
  return (
    <article className="flex flex-col rounded-2xl border border-line bg-white p-6">
      <span className="grid h-12 w-12 place-items-center rounded-xl bg-brand-50 text-brand-600"><Icon name={icon} className="h-6 w-6" /></span>
      <h2 className="mt-4 text-xl font-semibold">{title}</h2>
      <p className="mt-2 flex-1 text-sm text-muted">{body}</p>
      {enabled ? <Link className="btn-primary mt-6" href={href}>Open {title.toLowerCase()}</Link>
        : <span className="mt-6 flex items-center justify-center gap-2 rounded-lg bg-panel px-4 py-2 text-sm text-muted"><Icon name="lock" className="h-4 w-4" /> Not enabled for you</span>}
    </article>
  );
}

function Preferences({ c, onSaved }: { c: Config; onSaved: () => void }) {
  const [p, setP] = useState(c.preferences);
  const [error, setError] = useState<unknown>(null);
  const [ok, setOk] = useState(false);
  const save = async () => {
    setError(null); setOk(false);
    const body: Record<string, unknown> = { language: p.language, response_length: p.response_length };
    if (c.custom_name_allowed) { body.assistant_name = p.assistant_name; body.wake_phrase = p.wake_phrase || null; }
    try { await api("/assistant/preferences", { method: "PATCH", body }); setOk(true); onSaved(); } catch (e) { setError(e); }
  };
  return (
    <section className="card mt-6 max-w-2xl space-y-3">
      <h2 className="font-semibold">Assistant preferences</h2>
      <ErrorBox error={error} />
      {ok && <p className="text-sm text-green-700">Saved.</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Assistant name" hint={c.custom_name_allowed ? "e.g. Ben or Mr. Penn" : "Custom names are not included in your plan"}>
          <input className="input" disabled={!c.custom_name_allowed} value={p.assistant_name} onChange={(e) => setP({ ...p, assistant_name: e.target.value })} />
        </Field>
        <Field label="Preferred language">
          <select className="input" value={p.language} onChange={(e) => setP({ ...p, language: e.target.value })}>
            <option value="auto">Automatic</option><option value="te-IN">Telugu</option><option value="hi-IN">Hindi</option><option value="en-IN">English (India)</option>
          </select>
        </Field>
        <Field label="Wake phrase (hands-free, foreground tab only)" hint="Only works while this tab is open and the mic is unmuted">
          <input className="input" disabled={!c.custom_name_allowed} value={p.wake_phrase ?? ""} placeholder="Hey Kokila" onChange={(e) => setP({ ...p, wake_phrase: e.target.value })} />
        </Field>
        <Field label="Response length">
          <select className="input" value={p.response_length} onChange={(e) => setP({ ...p, response_length: e.target.value })}>
            <option value="short">Short</option><option value="medium">Medium</option><option value="detailed">Detailed</option>
          </select>
        </Field>
      </div>
      <button className="btn-primary" onClick={save}>Save preferences</button>
    </section>
  );
}
