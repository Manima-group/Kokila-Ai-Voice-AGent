"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Footer, Logo } from "@/components/Brand";
import { api, KokilaApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needOtp, setNeedOtp] = useState(false);
  const [platform, setPlatform] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.login({ email, password, platform, ...(otp ? { otp } : {}) });
      router.replace(r.platform ? "/admin" : "/assistant");
    } catch (err) {
      if (err instanceof KokilaApiError && err.error.code === "mfa_required") {
        setNeedOtp(true);
        setError(platform && !otp ? "Platform administration requires your authenticator code." : null);
      } else {
        setError(err instanceof KokilaApiError ? err.error.message : "Sign-in failed. Check your connection.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center px-4">
      <div className="mb-6 flex items-center gap-3">
        <Logo size={48} />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Sign in to Kokila</h1>
          <p className="text-sm text-k-grey-600">Your everyday voice companion.</p>
        </div>
      </div>
      <form onSubmit={submit} className="k-card space-y-4 p-6" noValidate>
        <div>
          <label className="k-label" htmlFor="email">Email</label>
          <input id="email" className="k-input" type="email" autoComplete="email" required value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="k-label" htmlFor="password">Password</label>
          <input id="password" className="k-input" type="password" autoComplete="current-password" required
                 value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {(needOtp || platform) && (
          <div>
            <label className="k-label" htmlFor="otp">Authenticator code</label>
            <input id="otp" className="k-input" inputMode="numeric" autoComplete="one-time-code" value={otp}
                   onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 8))} />
          </div>
        )}
        <label className="flex items-center gap-2 text-sm text-k-grey-600">
          <input type="checkbox" checked={platform} onChange={(e) => setPlatform(e.target.checked)} />
          Manima platform administration
        </label>
        {error && <p role="alert" className="text-sm text-k-danger">{error}</p>}
        <button className="k-btn-primary w-full" disabled={busy || !email || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-center text-sm text-k-grey-600">
          New here? <Link className="font-semibold underline" href="/register">Create an account</Link>
        </p>
      </form>
      <Footer />
    </main>
  );
}
