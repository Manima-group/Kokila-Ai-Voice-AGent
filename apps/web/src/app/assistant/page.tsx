"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Footer, Header } from "@/components/Brand";
import { api, deviceId, KokilaApiError, newKey } from "@/lib/api";
import type { Capabilities, Identity, Me, Msg, Session, ToolRun, Turn } from "@/lib/api";
import { BrowserSpeech, speechSupport } from "@/lib/speech";

type UiState = "starting" | "idle" | "listening" | "thinking" | "speaking" | "interrupted" | "awaiting_approval"
  | "reconnecting" | "error";

const STATE_LABEL: Record<UiState, string> = {
  starting: "Starting…", idle: "Ready", listening: "Listening…", thinking: "Thinking…", speaking: "Speaking…",
  interrupted: "Interrupted", awaiting_approval: "Waiting for your approval", reconnecting: "Reconnecting…",
  error: "Something went wrong",
};
const LANGS = [
  { v: "auto", label: "Auto" }, { v: "te-IN", label: "తెలుగు" }, { v: "hi-IN", label: "हिन्दी" },
  { v: "en-IN", label: "English" },
];

const noopSubscribe = () => () => undefined;

export default function AssistantPage() {
  const router = useRouter();
  const speech = useRef<BrowserSpeech | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [runs, setRuns] = useState<Record<string, ToolRun>>({});
  const [ui, setUi] = useState<UiState>("starting");
  const uiRef = useRef<UiState>("starting");
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState("auto");
  const [handsFree, setHandsFree] = useState(true);
  const [micPermission, setMicPermission] = useState<string>("unknown");
  const supportKey = useSyncExternalStore(noopSubscribe,
    () => { const s = speechSupport(); return `${s.stt ? 1 : 0}${s.tts ? 1 : 0}`; }, () => "00");
  const support = { stt: supportKey[0] === "1", tts: supportKey[1] === "1" };
  const [text, setText] = useState("");
  const speakingMsg = useRef<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const voiceEnabled = !!caps?.enabled.includes("assistant.voice");
  const name = identity?.effective.display_name ?? "Kokila";

  const setUiState = (s: UiState) => {
    uiRef.current = s;
    setUi(s);
  };
  const applySession = (s: Session) => {
    sessionRef.current = s;
    setSession(s);
  };

  const fail = useCallback((err: unknown) => {
    if (err instanceof KokilaApiError && err.status === 401) {
      router.replace("/login");
      return;
    }
    setError(err instanceof KokilaApiError ? `${err.error.message}${err.error.trace_id ? ` (trace ${err.error.trace_id.slice(0, 8)})` : ""}` : "Network error — check your connection.");
  }, [router]);

  // ---- bootstrap -----------------------------------------------------------------------------------
  useEffect(() => {
    speech.current = new BrowserSpeech();
    navigator.permissions?.query({ name: "microphone" as PermissionName })
      .then((p) => { setMicPermission(p.state); p.onchange = () => setMicPermission(p.state); })
      .catch(() => setMicPermission("unknown"));
    (async () => {
      try {
        const [m, c, idn] = await Promise.all([api.get<Me>("me"), api.get<Capabilities>("me/capabilities"),
          api.get<Identity>("assistant/preferences")]);
        setMe(m);
        setCaps(c);
        setIdentity(idn);
        if (c.enabled.includes("assistant.voice")) {
          const s = await api.post<Session>("assistant/sessions", { channel: "web_voice", device_id: deviceId() });
          applySession(s);
          setConversationId(s.conversation_id);
        } else {
          const conv = await api.post<{ id: string }>("conversations", { channel: "web_text" });
          setConversationId(conv.id);
        }
        setUiState("idle");
      } catch (err) {
        setUiState("error");
        fail(err);
      }
    })();
    const sp = speech.current;
    return () => {
      sp?.abortListening();
      sp?.cancelSpeech();
    };
  }, [fail]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, interim]);

  // ---- reconnect: replay acknowledged messages, never mutations; never unmute -------------------------
  useEffect(() => {
    const onOnline = async () => {
      const s = sessionRef.current;
      if (!s) return;
      setUiState("reconnecting");
      try {
        const last = messages.at(-1)?.sequence ?? 0;
        const r = await api.post<{ session: Session; messages: Msg[] }>(`assistant/sessions/${s.id}/resume`,
          { last_sequence: last, device_id: deviceId() });
        applySession(r.session);
        setMessages((prev) => [...prev, ...r.messages.filter((m) => !prev.some((p) => p.id === m.id))]);
        setUiState("idle");
      } catch (err) {
        fail(err);
        setUiState("error");
      }
    };
    const onOffline = () => {
      speech.current?.abortListening();
      setUiState("reconnecting");
    };
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [messages, fail]);

  // ---- controls --------------------------------------------------------------------------------------
  async function setControls(patch: { mic_muted?: boolean; speaker_muted?: boolean }): Promise<Session | null> {
    const s = sessionRef.current;
    if (!s) return null;
    try {
      const next = await api.post<Session>(`assistant/sessions/${s.id}/controls`,
        { ...patch, expected_revision: s.revision, device_id: deviceId() });
      applySession(next);
      return next;
    } catch (err) {
      if (err instanceof KokilaApiError && err.status === 409) {
        applySession(await api.get<Session>(`assistant/sessions/${s.id}`));
      }
      fail(err);
      return null;
    }
  }

  function startListening() {
    const s = sessionRef.current;
    const sp = speech.current;
    if (!s || s.mic_muted || !sp) return;
    if (uiRef.current === "thinking" || uiRef.current === "speaking" || uiRef.current === "awaiting_approval") return;
    const srLang = lang === "auto" ? (s.locale !== "auto" ? s.locale : "en-IN") : lang;
    const ok = sp.listen(srLang, {
      onStart: () => setUiState("listening"),
      onInterim: (t) => setInterim(t),
      onFinal: (t) => { setInterim(""); void sendTurn(t, "voice"); },
      onEnd: () => {
        setInterim("");
        if (uiRef.current === "listening") {
          setUiState("idle");
          if (handsFree && sessionRef.current && !sessionRef.current.mic_muted) setTimeout(startListening, 300);
        }
      },
      onError: async (code) => {
        setInterim("");
        if (code === "not-allowed" || code === "service-not-allowed") {
          setError("Microphone permission was denied. Allow it in your browser settings or keep typing.");
          await setControls({ mic_muted: true });
        } else setError(`Speech recognition error: ${code}. You can keep typing.`);
        setUiState("idle");
      },
    });
    if (!ok) setError("Speech recognition is not available in this browser. Use Chrome/Edge, or type.");
  }

  async function toggleMic() {
    const s = sessionRef.current;
    if (!s) return;
    if (!s.mic_muted) {
      speech.current?.abortListening(); // stop capture locally first; nothing is sent after this point
      setInterim("");
      if (uiRef.current === "listening") setUiState("idle");
      await setControls({ mic_muted: true });
      return;
    }
    if (!support.stt) {
      setError("Speech recognition is not available in this browser. Use Chrome/Edge, or type.");
      return;
    }
    const next = await setControls({ mic_muted: false, ...(s.speaker_muted ? { speaker_muted: false } : {}) });
    if (next && !next.mic_muted) startListening();
  }

  async function toggleSpeaker() {
    const s = sessionRef.current;
    if (!s) return;
    if (!s.speaker_muted) {
      speech.current?.cancelSpeech(); // discard queued speech immediately
      speakingMsg.current = null;
      if (uiRef.current === "speaking") setUiState("idle");
    }
    await setControls({ speaker_muted: !s.speaker_muted });
  }

  async function muteAll() {
    speech.current?.abortListening();
    speech.current?.cancelSpeech();
    speakingMsg.current = null;
    setInterim("");
    setUiState("idle");
    await setControls({ mic_muted: true, speaker_muted: true });
  }

  async function interrupt() {
    const s = sessionRef.current;
    const played = speech.current?.cancelSpeech() ?? 0;
    if (!s) return;
    try {
      const next = await api.post<Session>(`assistant/sessions/${s.id}/interrupt`, {
        expected_generation: s.generation, message_id: speakingMsg.current, played_chars: played,
      });
      applySession(next);
      speakingMsg.current = null;
      setUiState("interrupted");
      setTimeout(() => { if (uiRef.current === "interrupted") { setUiState("idle"); startListening(); } }, 250);
    } catch (err) {
      fail(err);
    }
  }

  // ---- turns ----------------------------------------------------------------------------------------
  async function sendTurn(raw: string, mode: "voice" | "text") {
    const content = raw.trim();
    if (!content || !conversationId) return;
    speech.current?.abortListening();
    setError(null);
    setUiState("thinking");
    const s = sessionRef.current;
    try {
      const t = await api.post<Turn>(`conversations/${conversationId}/turns`, {
        text: content, input_mode: mode, ...(s ? { session_id: s.id, generation: s.generation } : {}),
        ...(lang !== "auto" ? { language: lang } : {}),
      }, newKey("turn"));
      setMessages((prev) => [...prev, t.user_message, ...(t.assistant_message ? [t.assistant_message] : [])]);
      if (t.tool_runs.length) {
        setRuns((prev) => ({ ...prev, ...Object.fromEntries(t.tool_runs.filter((r) => r.run_id).map((r) => [r.run_id!, r])) }));
      }
      if (t.stale) { setUiState("idle"); return; }
      if (t.state === "awaiting_approval") { setUiState("awaiting_approval"); }
      const cur = sessionRef.current;
      if (t.speak && cur && !cur.speaker_muted && support.tts && t.assistant_message) {
        setUiState(t.state === "awaiting_approval" ? "awaiting_approval" : "speaking");
        speakingMsg.current = t.assistant_message.id;
        speech.current?.speak(t.speak, t.language, identity?.effective.speaking_rate ?? 1, () => {
          speakingMsg.current = null;
          if (uiRef.current === "speaking") {
            setUiState("idle");
            if (handsFree) startListening();
          }
        });
      } else if (t.state !== "awaiting_approval") {
        setUiState("idle");
        if (handsFree && cur && !cur.mic_muted) startListening();
      }
    } catch (err) {
      if (err instanceof KokilaApiError && err.status === 409 && s) {
        applySession(await api.get<Session>(`assistant/sessions/${s.id}`));
      }
      setUiState("idle");
      fail(err);
    }
  }

  async function decide(run: ToolRun, decision: "approve" | "deny") {
    if (!run.approval) return;
    try {
      const out = await api.post<ToolRun>(`approvals/${run.approval.id}/decision`,
        { decision, args_hash: run.approval.args_hash });
      setRuns((prev) => ({ ...prev, [out.run_id!]: out }));
      if (conversationId) {
        const last = messages.at(-1)?.sequence ?? 0;
        const r = await api.get<{ items: Msg[] }>(`conversations/${conversationId}/messages?after_sequence=${last}`);
        setMessages((prev) => [...prev, ...r.items]);
      }
      setUiState("idle");
    } catch (err) {
      fail(err);
    }
  }

  async function newConversation() {
    speech.current?.abortListening();
    speech.current?.cancelSpeech();
    setMessages([]);
    setRuns({});
    try {
      const s = sessionRef.current;
      if (s) {
        await api.post(`assistant/sessions/${s.id}/end`);
        const ns = await api.post<Session>("assistant/sessions", { channel: "web_voice", device_id: deviceId() });
        applySession(ns);
        setConversationId(ns.conversation_id);
      } else {
        const conv = await api.post<{ id: string }>("conversations", { channel: "web_text" });
        setConversationId(conv.id);
      }
      setUiState("idle");
    } catch (err) {
      fail(err);
    }
  }

  async function logout() {
    speech.current?.abortListening();
    speech.current?.cancelSpeech();
    await api.logout().catch(() => undefined);
    router.replace("/login");
  }

  const pendingRuns = Object.values(runs).filter((r) => r.status === "awaiting_approval" && r.approval);
  const live = ui === "listening" || ui === "speaking";
  const micMuted = session?.mic_muted ?? true;
  const spkMuted = session?.speaker_muted ?? true;

  return (
    <>
      <Header subtitle="MANIMA · KOKILA ASSISTANT" right={<>
        <Link className="k-btn" href="/memory">Memory</Link>
        <Link className="k-btn" href="/settings">Settings</Link>
        <button className="k-btn" onClick={logout}>Sign out</button>
      </>} />
      <main className="mx-auto max-w-3xl px-4 pb-6">
        <section className="py-6 text-center">
          <h1 className="text-3xl font-bold tracking-tight">How can I help you today{me ? `, ${me.display_name.split(" ")[0]}` : ""}?</h1>
          <p className="mt-1 text-k-grey-600">{name} · your everyday voice companion</p>
          <div aria-hidden className={`mx-auto my-8 grid h-32 w-32 place-items-center rounded-full text-k-grey-900 shadow-[0_0_0_13px_#fff3c4,0_0_0_26px_#fffbea] ${live ? "k-orb-live" : ""}`}
               style={{ background: "radial-gradient(circle at 32% 25%, #fffbea, #f9d65c 48%, #d4a514)" }}>
            <svg width="62" height="62" viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round">
              <path d="M8 25v14M20 16v32M32 8v48M44 16v32M56 25v14" />
            </svg>
          </div>
          <p role="status" aria-live="polite" className="min-h-6 font-semibold">
            {STATE_LABEL[ui]}{voiceEnabled && micMuted && ui === "idle" ? " · microphone muted" : ""}
          </p>

          {voiceEnabled ? (
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <button className={micMuted ? "k-btn" : "k-btn-primary"} aria-pressed={!micMuted} onClick={toggleMic}
                      disabled={!session || ui === "starting"}>
                {micMuted ? "🎙️ Unmute microphone" : "🎙️ Mute microphone"}
              </button>
              <button className={spkMuted ? "k-btn" : "k-btn-primary"} aria-pressed={!spkMuted} onClick={toggleSpeaker}
                      disabled={!session}>
                {spkMuted ? "🔇 Unmute speaker" : "🔊 Mute speaker"}
              </button>
              <button className="k-btn" onClick={muteAll} disabled={!session || (micMuted && spkMuted)}>Mute all</button>
              <button className="k-btn" onClick={interrupt} disabled={ui !== "speaking"}>Stop speaking</button>
              <button className="k-btn" onClick={() => startListening()}
                      disabled={micMuted || ui === "listening" || ui === "thinking"}>Push to talk</button>
              <button className="k-btn" onClick={newConversation}>New conversation</button>
            </div>
          ) : (
            <p className="mt-3 text-sm text-k-grey-600">
              Voice isn&apos;t included in your current plan — text chat is available.
              <button className="ml-2 underline" onClick={newConversation}>New conversation</button>
            </p>
          )}
          <div className="mt-4 flex flex-wrap items-center justify-center gap-3 text-xs text-k-grey-600">
            <label className="flex items-center gap-1">Language
              <select className="rounded-lg border border-k-grey-200 bg-k-white px-2 py-1" value={lang}
                      onChange={(e) => setLang(e.target.value)} aria-label="Conversation language">
                {LANGS.map((l) => <option key={l.v} value={l.v}>{l.label}</option>)}
              </select>
            </label>
            {voiceEnabled && (
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={handsFree} onChange={(e) => setHandsFree(e.target.checked)} />
                Continuous turn-taking
              </label>
            )}
            <span>Mic permission: {micPermission}</span>
            <span>Workspace: {caps?.workspace_id.slice(0, 8) ?? "…"}</span>
          </div>
        </section>

        {error && <p role="alert" className="mb-3 rounded-xl border border-k-danger/40 bg-k-white p-3 text-sm text-k-danger">{error}</p>}

        {pendingRuns.map((r) => (
          <div key={r.run_id} className="k-card mb-3 border-k-yellow-500 bg-k-yellow-50 p-4" role="group"
               aria-label="Approval required">
            <p className="text-xs font-semibold uppercase tracking-wide text-k-yellow-700">Approval required · {r.tool_key}</p>
            <p className="mt-1">{r.approval!.summary}</p>
            <p className="mt-1 text-xs text-k-grey-600">
              {r.side_effect === "consequential" ? "This cannot be undone." : "You can review or delete this later in Memory."}
              {" "}Expires {new Date(r.approval!.expires_at).toLocaleTimeString()}.
            </p>
            <div className="mt-3 flex gap-2">
              <button className="k-btn-primary" onClick={() => decide(r, "approve")}>Approve</button>
              <button className="k-btn" onClick={() => decide(r, "deny")}>Deny</button>
            </div>
          </div>
        ))}

        <div ref={logRef} role="log" aria-live="polite" aria-label="Conversation transcript"
             className="k-card max-h-[26rem] min-h-44 overflow-auto p-4">
          {messages.length === 0 && (
            <p className="text-sm text-k-grey-600">
              {voiceEnabled ? "Unmute your microphone or type to start." : "Type a message to start."}
            </p>
          )}
          {messages.filter((m) => m.role !== "system").map((m) => (
            <div key={m.id} className={`my-2 whitespace-pre-wrap break-words rounded-xl px-3.5 py-2.5 ${
              m.role === "user" ? "ml-[12%] bg-k-yellow-100" : m.role === "tool" ? "bg-k-grey-50 text-sm" : "bg-k-grey-100"}`}>
              <span className="mb-1 block text-[11px] text-k-grey-600">
                {m.role === "user" ? "You" : m.role === "tool" ? `Tool · ${m.tool_key ?? ""}` : name}
                {m.dev_mock && " · development mock (not live AI)"}
                {m.status === "interrupted" && " · interrupted"}
              </span>
              {m.role === "assistant" && m.status === "interrupted" && m.played_chars !== null
                ? <>{m.content.slice(0, m.played_chars)}<span className="text-k-grey-400">{m.content.slice(m.played_chars)}</span></>
                : m.content}
            </div>
          ))}
          {interim && <div className="my-2 ml-[12%] rounded-xl bg-k-yellow-50 px-3.5 py-2.5 italic text-k-grey-600">{interim}</div>}
        </div>

        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); const t = text; setText(""); void sendTurn(t, "text"); }}>
          <input className="k-input flex-1" placeholder={`Message ${name}…`} aria-label="Message" value={text}
                 onChange={(e) => setText(e.target.value)} maxLength={4000} />
          <button className="k-btn-primary" disabled={!text.trim() || ui === "thinking" || !conversationId}>Send</button>
        </form>

        <section className="k-card mt-5 p-4 text-sm text-k-grey-600">
          <h2 className="mb-1 font-semibold text-k-grey-900">About this session</h2>
          <p>Speech uses your browser&apos;s built-in recognition and voices, which may process audio on the browser
            vendor&apos;s servers. Kokila never captures audio while the microphone is muted, and reconnecting never unmutes it.</p>
          <p className="mt-1">Actions that save or delete data always ask for your approval first.</p>
        </section>
      </main>
      <Footer />
    </>
  );
}
