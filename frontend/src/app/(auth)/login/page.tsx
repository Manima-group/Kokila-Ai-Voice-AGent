"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import AuthFrame from "@/components/AuthFrame";
import { ErrorBox, Field } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const schema = z.object({ email: z.email("Enter a valid email"), password: z.string().min(1, "Password is required") });
type Form = z.infer<typeof schema>;

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<unknown>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (v) => {
    setError(null);
    try {
      const r = await api<{ access_token: string }>("/auth/login", { method: "POST", body: v });
      await login(r.access_token);
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard");
    } catch (e) {
      setError(e);
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <ErrorBox error={error} />
      <Field label="Email" error={formState.errors.email?.message}>
        <input className="input" type="email" autoComplete="email" {...register("email")} />
      </Field>
      <Field label="Password" error={formState.errors.password?.message}>
        <input className="input" type="password" autoComplete="current-password" {...register("password")} />
      </Field>
      <button className="btn-primary w-full" disabled={formState.isSubmitting}>{formState.isSubmitting ? "Signing in…" : "Sign in"}</button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <AuthFrame title="Sign in to Kokila" footer={<>New here? <Link className="text-brand-700 hover:underline" href="/signup">Create an account</Link></>}>
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthFrame>
  );
}
