"use client";

// Browser speech (Web Speech API): recognition + synthesis with independent mic/speaker mute and barge-in.
// Quality and language availability depend on the browser; this is NOT the realtime (LiveKit/OpenAI) voice path.
import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceState = "idle" | "listening" | "thinking" | "speaking" | "unsupported" | "error";

type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  onspeechstart: (() => void) | null;
};

function makeRecognition(): Recognition | null {
  if (typeof window === "undefined") return null;
  const W = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  const C = W.SpeechRecognition ?? W.webkitSpeechRecognition;
  return C ? new C() : null;
}

export function useVoice({ lang, onFinal, wakePhrase }: { lang: string; onFinal: (text: string) => void; wakePhrase?: string | null }) {
  const [state, setState] = useState<VoiceState>("idle");
  const [micMuted, setMicMuted] = useState(true); // default muted; only an explicit user action unmutes
  const [speakerMuted, setSpeakerMuted] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceName, setVoiceName] = useState<string | null>(null);
  const [handsFree, setHandsFree] = useState(false);
  const rec = useRef<Recognition | null>(null);
  const onFinalRef = useRef(onFinal);
  const micMutedRef = useRef(true);
  const handsFreeRef = useRef(false);
  const startListeningRef = useRef<() => void>(() => undefined);

  useEffect(() => { onFinalRef.current = onFinal; }, [onFinal]);
  useEffect(() => { micMutedRef.current = micMuted; }, [micMuted]);
  useEffect(() => { handsFreeRef.current = handsFree; }, [handsFree]);

  const supported = typeof window !== "undefined" && !!makeRecognition() && "speechSynthesis" in window;

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const load = () => setVoices(window.speechSynthesis.getVoices());
    load();
    window.speechSynthesis.addEventListener("voiceschanged", load);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", load);
  }, []);

  const stopSpeaking = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  const stopListening = useCallback(() => {
    rec.current?.abort();
    rec.current = null;
    setInterim("");
    setState((s) => (s === "listening" ? "idle" : s));
  }, []);

  const startListening = useCallback(() => {
    if (micMutedRef.current) return;
    const r = makeRecognition();
    if (!r) { setState("unsupported"); return; }
    rec.current?.abort();
    r.lang = lang === "auto" ? "en-IN" : lang;
    r.continuous = handsFreeRef.current;
    r.interimResults = true;
    r.onspeechstart = () => stopSpeaking(); // barge-in: user speech cancels assistant playback
    r.onresult = (e) => {
      let text = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        text += res[0].transcript;
        if (res.isFinal) {
          let finalText = text.trim();
          setInterim("");
          if (handsFreeRef.current && wakePhrase) {
            const lower = finalText.toLowerCase();
            const w = wakePhrase.toLowerCase();
            if (!lower.startsWith(w)) return; // ignore speech not addressed to the assistant
            finalText = finalText.slice(w.length).replace(/^[\s,.!]+/, "");
          }
          if (finalText) { setState("thinking"); onFinalRef.current(finalText); }
          return;
        }
      }
      setInterim(text);
    };
    r.onerror = (e) => {
      if (e.error === "aborted" || e.error === "no-speech") return;
      setError(e.error === "not-allowed" ? "Microphone permission was denied. Allow it in your browser settings." : `Speech recognition error: ${e.error}`);
      setMicMuted(true);
      setState("error");
    };
    r.onend = () => {
      rec.current = null;
      if (handsFreeRef.current && !micMutedRef.current) setTimeout(() => startListeningRef.current(), 250);
      else setState((s) => (s === "listening" ? "idle" : s));
    };
    rec.current = r;
    setError(null);
    setState("listening");
    try { r.start(); } catch { /* already started */ }
  }, [lang, stopSpeaking, wakePhrase]);

  useEffect(() => { startListeningRef.current = startListening; }, [startListening]);

  const toggleMic = useCallback(() => {
    if (micMuted) {
      micMutedRef.current = false;
      setMicMuted(false);
      startListeningRef.current();
    } else {
      micMutedRef.current = true;
      setMicMuted(true);
      stopListening(); // stop capture immediately and discard interim audio/text
    }
  }, [micMuted, stopListening]);

  const toggleSpeaker = useCallback(() => {
    setSpeakerMuted((m) => { if (!m) stopSpeaking(); return !m; });
  }, [stopSpeaking]);

  const speak = useCallback((text: string, speakLang?: string) => {
    if (speakerMuted || typeof window === "undefined" || !("speechSynthesis" in window) || !text) { setState("idle"); return; }
    stopSpeaking();
    const u = new SpeechSynthesisUtterance(text.slice(0, 1200));
    const l = speakLang && speakLang !== "auto" ? speakLang : lang === "auto" ? "en-IN" : lang;
    u.lang = l;
    const v = voices.find((x) => x.name === voiceName) ?? voices.find((x) => x.lang === l);
    if (v) u.voice = v;
    u.onstart = () => setState("speaking");
    u.onend = () => { if (micMutedRef.current) setState("idle"); else startListeningRef.current(); };
    window.speechSynthesis.speak(u);
  }, [speakerMuted, voices, voiceName, lang, stopSpeaking]);

  useEffect(() => () => { rec.current?.abort(); stopSpeaking(); }, [stopSpeaking]);

  return { supported, state, setState, micMuted, speakerMuted, toggleMic, toggleSpeaker, interim, error, speak, stopSpeaking,
    startListening, voices, voiceName, setVoiceName, handsFree, setHandsFree, muteAll: () => { if (!micMuted) toggleMic(); if (!speakerMuted) toggleSpeaker(); } };
}
