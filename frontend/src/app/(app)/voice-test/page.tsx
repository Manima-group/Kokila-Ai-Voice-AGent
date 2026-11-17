"use client";

import Link from "next/link";
import { useState } from "react";

import { ErrorBox, Field, MockNotice, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { Agent } from "@/types";

const OUTCOMES = ["interested", "qualified", "not_interested", "callback_requested", "appointment_requested", "human_transfer", "do_not_call"];

export default function VoiceTest() {
  const agents = useApi<Agent[]>("/agents");
  const published = agents.data?.filter((a) => a.status === "published") ?? [];
  const [agentId, setAgentId] = useState("");
  const [mode, setMode] = useState<"simulate" | "phone">("simulate");
  const [lines, setLines] = useState("Hello, I want to know about 2BHK flats in Whitefield.\nMy budget is around 80 lakhs.");
  const [outcome, setOutcome] = useState("interested");
  const [language, setLanguage] = useState("en");
  const [to, setTo] = useState("");
  const [from, setFrom] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const go = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = mode === "simulate"
        ? await api<Record<string, unknown>>("/calls/simulate", { method: "POST", body: { agent_id: agentId || published[0]?.id, utterances: lines.split("\n").filter(Boolean), outcome, language } })
        : await api<Record<string, unknown>>("/calls/test", { method: "POST", body: { agent_id: agentId || published[0]?.id, to_number: to, from_number: from } });
      setResult(r);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl">
      <PageHeader title="Voice testing" subtitle="Exercise a published agent end-to-end through the real event pipeline." />
      <div className="mb-4 flex gap-2" role="tablist">
        <button role="tab" aria-selected={mode === "simulate"} className={mode === "simulate" ? "btn-primary" : "btn-secondary"} onClick={() => setMode("simulate")}>Simulated conversation</button>
        <button role="tab" aria-selected={mode === "phone"} className={mode === "phone" ? "btn-primary" : "btn-secondary"} onClick={() => setMode("phone")}>Real test call</button>
      </div>
      <div className="card space-y-4">
        {mode === "simulate" ? <MockNotice /> : (
          <p className="rounded-lg bg-panel px-4 py-2 text-xs text-muted">Places a real call through the configured provider to your own number. Requires a live provider (not mock mode), a published agent and an active plan. Results appear in Call history after the provider sends signed events.</p>
        )}
        <Field label="Agent">
          <select className="input" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            {published.length === 0 && <option value="">No published agents</option>}
            {published.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
        {mode === "simulate" ? (
          <>
            <Field label="Caller utterances (one per line)"><textarea className="input" rows={4} value={lines} onChange={(e) => setLines(e.target.value)} /></Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Simulated outcome"><select className="input" value={outcome} onChange={(e) => setOutcome(e.target.value)}>{OUTCOMES.map((o) => <option key={o}>{o}</option>)}</select></Field>
              <Field label="Language label"><select className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>{["en", "hi", "kn", "te"].map((l) => <option key={l}>{l}</option>)}</select></Field>
            </div>
          </>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Your phone number"><input className="input" value={to} onChange={(e) => setTo(e.target.value)} placeholder="+91…" /></Field>
            <Field label="From (your Kokila number)"><input className="input" value={from} onChange={(e) => setFrom(e.target.value)} placeholder="+91…" /></Field>
          </div>
        )}
        <ErrorBox error={error} />
        <button className="btn-primary" disabled={busy || published.length === 0} onClick={go}>{busy ? "Running…" : mode === "simulate" ? "Run simulation" : "Place test call"}</button>
        {result && (
          <div className="rounded-lg border border-line bg-panel p-4 text-sm">
            {typeof result.call_id === "string" ? <>Simulation stored. <Link className="text-brand-700 underline" href={`/calls/${result.call_id}`}>Open call detail</Link></> : <>Provider call id: <code>{String(result.provider_call_id)}</code></>}
          </div>
        )}
      </div>
    </div>
  );
}
