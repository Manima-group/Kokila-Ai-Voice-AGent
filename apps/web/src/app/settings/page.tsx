"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Footer, Header } from "@/components/Brand";
import { api, KokilaApiError } from "@/lib/api";
import type { Identity } from "@/lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const [idn, setIdn] = useState<Identity | null>(null);
  const [form, setForm] = useState({ display_name: "", aliases: "", locale: "auto", response_length: "medium",
                                     speaking_rate: 1 });
  const [msg, setMsg] = useState<string | null>(null);
  const [mfa, setMfa] = useState<{ uri: string; secret: string } | null>(null);
  const [code, setCode] = useState("");

  const onErr = useCallback((e: unknown) => {
    if (e instanceof KokilaApiError && e.status === 401) router.replace("/login");
    else setMsg(e instanceof KokilaApiError ? e.error.message : "Network error");
  }, [router]);

  const [version, setVersion] = useState(0);
  const load = useCallback(async () => setVersion((v) => v + 1), []);
  useEffect(() => {
    let alive = true;
    api.get<Identity>("assistant/preferences").then((i) => {
      if (!alive) return;
      setIdn(i);
      setForm({ display_name: i.effective.display_name, aliases: i.effective.aliases.join(", "),
                locale: i.effective.locale, response_length: i.effective.response_length,
                speaking_rate: i.effective.speaking_rate });
    }).catch((e) => { if (alive) onErr(e); });
    return () => { alive = false; };
  }, [version, onErr]);

  const editable = new Set(idn?.editable_fields ?? []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!idn) return;
    try {
      await api.patch("assistant/preferences", {
        display_name: form.display_name, spoken_name: form.display_name,
        aliases: form.aliases.split(",").map((a) => a.trim()).filter(Boolean),
        locale: form.locale, response_length: form.response_length, speaking_rate: Number(form.speaking_rate),
        expected_revision: idn.revision,
      });
      setMsg("Saved. New conversations use this identity right away.");
      await load();
    } catch (err) { onErr(err); await load(); }
  }

  async function enrollMfa() {
    try { const r = await api.post<{ otpauth_uri: string; secret: string }>("auth/mfa/enroll");
          setMfa({ uri: r.otpauth_uri, secret: r.secret }); } catch (e) { onErr(e); }
  }
  async function verifyMfa() {
    try { await api.post("auth/mfa/verify", { code }); setMfa(null); setMsg("Two-factor authentication enabled."); }
    catch (e) { onErr(e); }
  }

  return (
    <>
      <Header subtitle="SETTINGS" right={<Link className="k-btn" href="/assistant">Back to assistant</Link>} />
      <main className="mx-auto max-w-2xl space-y-5 px-4 py-6">
        <h1 className="text-2xl font-bold">Assistant identity</h1>
        {msg && <p role="status" className="text-sm">{msg}</p>}
        {idn && !idn.effective.customization_enabled && (
          <p className="k-card p-3 text-sm text-k-grey-600">Custom assistant names aren&apos;t included in your plan.</p>)}
        {idn && idn.effective.customization_enabled && !idn.effective.personal_override_allowed && (
          <p className="k-card p-3 text-sm text-k-grey-600">Your workspace administrator has set the assistant identity.</p>)}
        <form onSubmit={save} className="k-card space-y-4 p-5">
          <div>
            <label className="k-label" htmlFor="dn">Assistant name</label>
            <input id="dn" className="k-input" maxLength={40} disabled={!editable.has("display_name")}
                   value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </div>
          <div>
            <label className="k-label" htmlFor="al">Other names (comma separated)</label>
            <input id="al" className="k-input" disabled={!editable.has("aliases")} value={form.aliases}
                   onChange={(e) => setForm({ ...form, aliases: e.target.value })} />
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className="k-label" htmlFor="lc">Language</label>
              <select id="lc" className="k-input" disabled={!editable.has("locale")} value={form.locale}
                      onChange={(e) => setForm({ ...form, locale: e.target.value })}>
                <option value="auto">Automatic</option><option value="te-IN">తెలుగు</option>
                <option value="hi-IN">हिन्दी</option><option value="en-IN">English</option>
              </select>
            </div>
            <div>
              <label className="k-label" htmlFor="rl">Reply length</label>
              <select id="rl" className="k-input" disabled={!editable.has("response_length")} value={form.response_length}
                      onChange={(e) => setForm({ ...form, response_length: e.target.value })}>
                <option value="short">Short</option><option value="medium">Medium</option><option value="long">Long</option>
              </select>
            </div>
            <div>
              <label className="k-label" htmlFor="sr">Speaking rate ({form.speaking_rate.toFixed(1)}×)</label>
              <input id="sr" type="range" min={0.5} max={2} step={0.1} className="w-full"
                     disabled={!editable.has("speaking_rate")} value={form.speaking_rate}
                     onChange={(e) => setForm({ ...form, speaking_rate: Number(e.target.value) })} />
            </div>
          </div>
          <p className="text-xs text-k-grey-600">Wake word: {idn?.effective.wake_status ?? "disabled"} — hands-free wake words
            aren&apos;t validated in this deployment yet, so use the microphone button or push-to-talk.</p>
          <button className="k-btn-primary" disabled={editable.size === 0}>Save identity</button>
        </form>

        <h2 className="text-xl font-bold">Security</h2>
        <div className="k-card space-y-3 p-5">
          {!mfa ? <button className="k-btn" onClick={enrollMfa}>Set up two-factor authentication</button> : (
            <>
              <p className="text-sm">Add this key to your authenticator app, then enter the 6-digit code.</p>
              <code className="block break-all rounded-lg bg-k-grey-50 p-2 text-xs">{mfa.secret}</code>
              <div className="flex gap-2">
                <input className="k-input" inputMode="numeric" value={code} aria-label="Verification code"
                       onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 8))} />
                <button className="k-btn-primary" onClick={verifyMfa} disabled={code.length < 6}>Verify</button>
              </div>
            </>
          )}
        </div>
      </main>
      <Footer />
    </>
  );
}
