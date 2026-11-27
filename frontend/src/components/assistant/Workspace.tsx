"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { type Artifact, ArtifactView, MetricCard, type MetricResult } from "@/components/assistant/Artifacts";
import { Icon } from "@/components/icons";
import { Badge, ErrorBox, Loading } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useVoice } from "@/hooks/useVoice";
import { ApiError, api, fmtDate } from "@/lib/api";

type Config = {
  llm: { configured: boolean; provider: string | null; model: string | null };
  voice: { engine: string; note: string };
  research: boolean;
  modes: { business: boolean; personal: boolean };
  memory: boolean;
  preferences: { assistant_name: string; language: string; voice_name: string | null; wake_phrase: string | null; response_length: string };
  custom_name_allowed: boolean;
};
type Conv = { id: string; title: string; updated_at: string };
type Msg = { id: string; role: string; content: string; artifacts: Artifact[]; provider: string | null; model: string | null; created_at: string };
type Metric = { key: string; title: string; source: string; description: string; params: string[]; available: boolean };

const LANGS: [string, string][] = [["auto", "Auto"], ["te-IN", "తెలుగు"], ["hi-IN", "हिन्दी"], ["en-IN", "English"]];
const BUSINESS_PROMPTS = ["What were today's sales?", "Show this month's revenue", "Which products are low in stock?", "How many invoices are overdue?",
  "Compare this month's sales with last month", "Show my upcoming appointments"];
const PERSONAL_PROMPTS = ["Remind me tomorrow at 10 AM to call the bank", "Remember that I prefer replies in Telugu", "Summarise my notes"];

export default function Workspace({ mode }: { mode: "business" | "personal" }) {
  const qc = useQueryClient();
  const cfg = useApi<Config>("/assistant/config");
  const convs = useApi<Conv[]>(`/assistant/conversations?mode=${mode}`);
  const metrics = useApi<Metric[]>(mode === "business" ? "/connect/metrics" : null);
  const [active, setActive] = useState<string | null>(null);
  const msgs = useApi<Msg[]>(active ? `/assistant/conversations/${active}/messages` : null);
  const [text, setText] = useState("");
  const [lang, setLang] = useState("auto");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [quick, setQuick] = useState<MetricResult | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const prefs = cfg.data?.preferences;
  const voiceRef = useRef<ReturnType<typeof useVoice> | null>(null);

  const send = useCallback(async (content: string) => {
    if (!content.trim()) return;
    setError(null);
    setSending(true);
    try {
      let cid = active;
      if (!cid) {
        cid = (await api<Conv>("/assistant/conversations", { method: "POST", body: { mode } })).id;
        setActive(cid);
      }
      setText("");
      const reply = await api<Msg>(`/assistant/conversations/${cid}/messages`, { method: "POST", body: { content, language: lang } });
      qc.invalidateQueries({ predicate: (q) => String(q.queryKey[1]).startsWith("/assistant/conversations") });
      voiceRef.current?.speak(reply.content, lang);
    } catch (e) {
      setError(e);
      voiceRef.current?.setState("idle");
    } finally {
      setSending(false);
    }
  }, [active, mode, lang, qc]);

  const voice = useVoice({ lang, onFinal: (t) => void send(t), wakePhrase: prefs?.wake_phrase });
  useEffect(() => { voiceRef.current = voice; }, [voice]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs.data?.length, sending]);

  const runQuick = async (key: string) => {
    setError(null);
    setQuick(null);
    const today = new Date();
    const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; // local date, not UTC
    const params = key.endsWith("sales_total") || key.endsWith("sales_compare") ? { date_from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), date_to: iso(today) } : {};
    try { setQuick(await api<MetricResult>("/connect/metrics/run", { method: "POST", body: { metric_key: key, params } })); } catch (e) { setError(e); }
  };

  if (cfg.isLoading) return <Loading />;
  if (cfg.error) return <ErrorBox error={cfg.error} />;
  const c = cfg.data!;
  const name = prefs?.assistant_name ?? "Kokila";
  const notConfigured = error instanceof ApiError && error.code === "llm_not_configured";

  return (
    <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
      <aside className="space-y-4">
        <button className="btn-primary w-full" onClick={() => { setActive(null); setQuick(null); }}><Icon name="plus" /> New conversation</button>
        <div className="rounded-xl border border-line bg-white">
          <div className="border-b border-line px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted">History</div>
          <ul className="max-h-72 overflow-y-auto">
            {convs.data?.map((x) => (
              <li key={x.id}>
                <button className={`block w-full truncate px-4 py-2 text-left text-sm ${active === x.id ? "bg-brand-50 text-brand-700" : "hover:bg-panel"}`} onClick={() => { setActive(x.id); setQuick(null); }}>{x.title}</button>
              </li>
            ))}
            {!convs.data?.length && <li className="px-4 py-3 text-sm text-muted">No conversations yet</li>}
          </ul>
        </div>
        {mode === "business" && (
          <div className="rounded-xl border border-line bg-white p-3">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Quick reports</div>
            <ul className="space-y-1">
              {metrics.data?.map((m) => (
                <li key={m.key}>
                  <button disabled={!m.available} title={m.available ? m.description : "Connect the data source under Integrations"}
                    className="w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-panel disabled:cursor-not-allowed disabled:opacity-40" onClick={() => runQuick(m.key)}>
                    {m.title} <span className="text-xs text-muted">· {m.source}</span>
                  </button>
                </li>
              ))}
            </ul>
            <Link href="/integrations" className="mt-2 block text-xs text-brand-700 hover:underline">Connect more data sources →</Link>
          </div>
        )}
        {mode === "personal" && <PersonalPanel memory={c.memory} />}
      </aside>

      <section className="flex min-h-[70vh] flex-col rounded-2xl border border-line bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-brand-50 text-brand-600"><Icon name="mic" /></span>
            <div>
              <div className="font-semibold">{name} <span className="text-sm font-normal text-muted">· {mode === "business" ? "Business mode" : "Personal mode"}</span></div>
              <div className="text-xs text-muted">{c.llm.configured ? `Model: ${c.llm.provider} / ${c.llm.model}` : "AI model not configured — quick reports still work"}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <VoiceStatus state={voice.state} micMuted={voice.micMuted} />
            <select className="input w-28" value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Conversation language">
              {LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
          {!active && !quick && (
            <div className="mx-auto max-w-xl py-10 text-center">
              <h2 className="text-xl font-semibold">How can I help{mode === "personal" ? " you today" : " with your business"}?</h2>
              <p className="mt-1 text-sm text-muted">{mode === "business" ? "Answers come only from your connected systems — never made up." : "Your personal chats, memory and reminders are private to you."}</p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {(mode === "business" ? BUSINESS_PROMPTS : PERSONAL_PROMPTS).map((p) => (
                  <button key={p} className="rounded-full border border-line px-3 py-1.5 text-sm hover:border-brand-200 hover:bg-brand-50" onClick={() => send(p)} disabled={sending || !c.llm.configured}>{p}</button>
                ))}
              </div>
            </div>
          )}
          {quick && <MetricCard m={quick} />}
          {msgs.data?.map((m) => (
            <div key={m.id} className={m.role === "user" ? "ml-auto max-w-[80%]" : "max-w-[95%]"}>
              <div className={`rounded-2xl px-4 py-2.5 text-sm ${m.role === "user" ? "bg-brand-600 text-white" : "bg-panel"}`}>
                <p className="whitespace-pre-wrap">{m.content}</p>
              </div>
              {m.artifacts?.map((a, i) => <ArtifactView key={i} a={a} onChange={() => qc.invalidateQueries()} />)}
              {m.role === "assistant" && m.model && <div className="mt-1 text-[11px] text-muted">{m.provider}/{m.model} · {fmtDate(m.created_at)}</div>}
            </div>
          ))}
          {sending && <div className="flex items-center gap-2 text-sm text-muted"><span className="h-2 w-2 animate-pulse rounded-full bg-brand-500" /> {name} is thinking…</div>}
          {voice.interim && <div className="ml-auto max-w-[80%] rounded-2xl border border-dashed border-brand-200 px-4 py-2 text-sm italic text-muted">{voice.interim}</div>}
          <div ref={endRef} />
        </div>

        <div className="border-t border-line p-3">
          {notConfigured ? (
            <div className="mb-2 rounded-lg bg-brand-50 px-4 py-2 text-sm text-brand-700">The AI model isn&apos;t configured on this deployment yet (LLM_PROVIDER / LLM_MODEL). Use Quick reports meanwhile.</div>
          ) : <div className="mb-2"><ErrorBox error={error} /></div>}
          {voice.error && <p className="mb-2 text-sm text-red-600">{voice.error}</p>}
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
            <button type="button" onClick={voice.toggleMic} disabled={!voice.supported} aria-pressed={!voice.micMuted}
              aria-label={voice.micMuted ? "Unmute microphone" : "Mute microphone"} title={voice.supported ? (voice.micMuted ? "Unmute microphone" : "Mute microphone") : "Voice input not supported in this browser"}
              className={`grid h-11 w-11 shrink-0 place-items-center rounded-full border ${voice.micMuted ? "border-line bg-white text-muted" : "border-brand-600 bg-brand-600 text-white"}`}>
              <Icon name={voice.micMuted ? "micOff" : "mic"} />
            </button>
            <button type="button" onClick={voice.toggleSpeaker} aria-pressed={voice.speakerMuted} aria-label={voice.speakerMuted ? "Unmute speaker" : "Mute speaker"}
              className={`grid h-11 w-11 shrink-0 place-items-center rounded-full border ${voice.speakerMuted ? "border-line bg-panel text-muted" : "border-line bg-white"}`}>
              <Icon name={voice.speakerMuted ? "speakerOff" : "speaker"} />
            </button>
            {voice.state === "speaking" && (
              <button type="button" onClick={voice.stopSpeaking} className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-line" aria-label="Stop speaking"><Icon name="stop" /></button>
            )}
            <textarea className="input min-h-11 flex-1 resize-none" rows={1} value={text} placeholder={`Message ${name}…`} aria-label="Message"
              onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(text); } }} />
            <button className="btn-primary h-11" disabled={sending || !text.trim()} aria-label="Send"><Icon name="send" /></button>
          </form>
          <p className="mt-2 text-[11px] text-muted">Voice uses your browser&apos;s speech engine ({voice.supported ? "available" : "not supported here — use Chrome or Edge"}); Telugu/Hindi quality depends on the browser. Microphone starts muted.</p>
        </div>
      </section>
    </div>
  );
}

function VoiceStatus({ state, micMuted }: { state: string; micMuted: boolean }) {
  const label = micMuted && state !== "speaking" && state !== "thinking" ? "Mic muted" : { listening: "Listening", thinking: "Thinking", speaking: "Speaking", error: "Voice error", unsupported: "Voice unsupported" }[state] ?? "Ready";
  const tone = label === "Listening" ? "green" : label === "Speaking" || label === "Thinking" ? "orange" : label.startsWith("Voice") ? "red" : "grey";
  return <span role="status"><Badge tone={tone}>{label}</Badge></span>;
}

function PersonalPanel({ memory }: { memory: boolean }) {
  const mem = useApi<{ id: string; content: string; status: string }[]>(memory ? "/assistant/memory" : null);
  const rem = useApi<{ id: string; text: string; due_at: string; status: string }[]>("/assistant/reminders");
  const [note, setNote] = useState("");
  return (
    <>
      {memory && (
        <div className="rounded-xl border border-line bg-white p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Memory (you control this)</div>
          <ul className="space-y-1 text-sm">
            {mem.data?.map((m) => (
              <li key={m.id} className="flex items-start justify-between gap-2">
                <span>{m.content} {m.status === "pending" && <Badge tone="orange">pending</Badge>}</span>
                <button aria-label="Delete memory" className="text-muted hover:text-red-600" onClick={async () => { await api(`/assistant/memory/${m.id}`, { method: "DELETE" }); mem.refetch(); }}><Icon name="trash" className="h-4 w-4" /></button>
              </li>
            ))}
            {!mem.data?.length && <li className="text-muted">Nothing saved.</li>}
          </ul>
          <form className="mt-2 flex gap-1" onSubmit={async (e) => { e.preventDefault(); if (!note.trim()) return; await api("/assistant/memory", { method: "POST", body: { content: note } }); setNote(""); mem.refetch(); }}>
            <input className="input text-sm" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add something to remember" aria-label="New memory" />
          </form>
        </div>
      )}
      <div className="rounded-xl border border-line bg-white p-3">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Reminders</div>
        <ul className="space-y-1 text-sm">
          {rem.data?.filter((r) => r.status === "scheduled").map((r) => (
            <li key={r.id} className="flex justify-between gap-2"><span>{r.text}<span className="block text-xs text-muted">{fmtDate(r.due_at)}</span></span>
              <button className="text-xs text-red-600 hover:underline" onClick={async () => { await api(`/assistant/reminders/${r.id}/cancel`, { method: "POST" }); rem.refetch(); }}>Cancel</button></li>
          ))}
          {!rem.data?.some((r) => r.status === "scheduled") && <li className="text-muted">No upcoming reminders.</li>}
        </ul>
      </div>
    </>
  );
}
