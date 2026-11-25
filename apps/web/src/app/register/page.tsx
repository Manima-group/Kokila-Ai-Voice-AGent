"use client";

import Link from "next/link";
import { useState } from "react";
import { Footer, Logo } from "@/components/Brand";
import { api, KokilaApiError } from "@/lib/api";

export default function RegisterPage() {
  const [form, setForm] = useState({ display_name: "", email: "", password: "" });
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.register({ ...form, locale: "en-IN", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
      setDone(r.message);
    } catch (err) {
      setError(err instanceof KokilaApiError
        ? (err.error.code === "validation_failed" ? "Use a valid email and a password of at least 12 characters." : err.error.message)
        : "Registration failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center px-4">
      <div className="mb-6 flex items-center gap-3">
        <Logo size={48} />
        <h1 className="text-2xl font-bold tracking-tight">Create your Kokila account</h1>
      </div>
      {done ? (
        <div className="k-card space-y-4 p-6">
          <p>{done}</p>
          <Link href="/login" className="k-btn-primary w-full">Go to sign in</Link>
        </div>
      ) : (
        <form onSubmit={submit} className="k-card space-y-4 p-6">
          {(["display_name", "email", "password"] as const).map((f) => (
            <div key={f}>
              <label className="k-label" htmlFor={f}>{f === "display_name" ? "Your name" : f}</label>
              <input id={f} className="k-input" required type={f === "password" ? "password" : f === "email" ? "email" : "text"}
                     autoComplete={f === "password" ? "new-password" : f === "email" ? "email" : "name"}
                     minLength={f === "password" ? 12 : 1} value={form[f]}
                     onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
            </div>
          ))}
          <p className="text-xs text-k-grey-600">Passwords need at least 12 characters.</p>
          {error && <p role="alert" className="text-sm text-k-danger">{error}</p>}
          <button className="k-btn-primary w-full" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
          <p className="text-center text-sm text-k-grey-600">
            Have an account? <Link className="font-semibold underline" href="/login">Sign in</Link>
          </p>
        </form>
      )}
      <Footer />
    </main>
  );
}
