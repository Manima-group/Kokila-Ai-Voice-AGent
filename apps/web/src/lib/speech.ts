"use client";

/**
 * Browser-native speech adapter (Web Speech API): STT via SpeechRecognition, TTS via speechSynthesis.
 *
 * This is the no-credential fallback path. The realtime path (LiveKit/WebRTC + OpenAI Realtime) is used when the
 * deployment issues media tokens. Browser speech services may process audio remotely (vendor-dependent); the UI
 * discloses that. Mute is enforced locally *first* (recognition aborted, audio discarded) and then persisted
 * server-side, so no audio is captured after the user presses mute.
 */

type SR = {
  lang: string; continuous: boolean; interimResults: boolean; maxAlternatives: number;
  start(): void; stop(): void; abort(): void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
};

function recognitionCtor(): (new () => SR) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function speechSupport(): { stt: boolean; tts: boolean } {
  return { stt: recognitionCtor() !== null, tts: typeof window !== "undefined" && "speechSynthesis" in window };
}

export type ListenHandlers = {
  onStart?: () => void;
  onInterim?: (text: string) => void;
  onFinal: (text: string) => void;
  onEnd?: () => void;
  onError?: (code: string) => void;
};

export class BrowserSpeech {
  private rec: SR | null = null;
  private epoch = 0;
  private spokenChars = 0;
  private speakingText = "";

  listen(lang: string, h: ListenHandlers): boolean {
    const Ctor = recognitionCtor();
    if (!Ctor) return false;
    this.abortListening();
    const r = new Ctor();
    this.rec = r;
    r.lang = lang;
    r.continuous = false;
    r.interimResults = true;
    r.maxAlternatives = 1;
    r.onstart = () => this.rec === r && h.onStart?.();
    r.onresult = (e) => {
      if (this.rec !== r) return;
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (!res) continue;
        const t = res[0]?.transcript ?? "";
        if (res.isFinal) {
          const text = t.trim();
          if (text) h.onFinal(text);
        } else interim += t;
      }
      if (interim) h.onInterim?.(interim);
    };
    r.onerror = (e) => {
      if (this.rec !== r || e.error === "aborted" || e.error === "no-speech") return;
      h.onError?.(e.error);
    };
    r.onend = () => {
      if (this.rec !== r) return;
      this.rec = null;
      h.onEnd?.();
    };
    try {
      r.start();
      return true;
    } catch {
      this.rec = null;
      h.onError?.("start_failed");
      return false;
    }
  }

  /** Immediately stop capture and discard any unsent audio/results. */
  abortListening(): void {
    const r = this.rec;
    this.rec = null;
    if (r) {
      r.onresult = null;
      try {
        r.abort();
      } catch {
        /* already stopped */
      }
    }
  }

  get listening(): boolean {
    return this.rec !== null;
  }

  speak(text: string, lang: string, rate: number, onDone: (completed: boolean) => void): void {
    if (!("speechSynthesis" in window)) {
      onDone(false);
      return;
    }
    this.cancelSpeech();
    const n = ++this.epoch;
    const u = new SpeechSynthesisUtterance(text);
    const voices = window.speechSynthesis.getVoices();
    const want = lang === "auto" ? "en-IN" : lang;
    u.voice = voices.find((v) => v.lang === want) ?? voices.find((v) => v.lang.startsWith(want.slice(0, 2))) ?? null;
    u.lang = want;
    u.rate = Math.min(2, Math.max(0.5, rate));
    this.spokenChars = 0;
    this.speakingText = text;
    u.onboundary = (ev) => {
      if (n === this.epoch) this.spokenChars = ev.charIndex + (ev.charLength || 0);
    };
    const done = (completed: boolean) => {
      if (n !== this.epoch) return;
      if (completed) this.spokenChars = text.length;
      this.speakingText = "";
      onDone(completed);
    };
    u.onend = () => done(true);
    u.onerror = () => done(false);
    window.speechSynthesis.speak(u);
  }

  /** Stop playback and clear queued speech. Returns characters actually played (best-effort). */
  cancelSpeech(): number {
    this.epoch++;
    const played = this.speakingText ? Math.min(this.spokenChars, this.speakingText.length) : this.spokenChars;
    this.speakingText = "";
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    return played;
  }
}
