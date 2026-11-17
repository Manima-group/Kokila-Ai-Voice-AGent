"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import AuthFrame from "@/components/AuthFrame";
import { ErrorBox, Field } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const schema = z.object({
  company_name: z.string().min(2, "Company name is required"),
  full_name: z.string().min(2, "Your name is required"),
  email: z.email("Enter a valid email"),
  industry: z.string().optional(),
  password: z.string().min(10, "At least 10 characters").regex(/[A-Za-z]/, "Include a letter").regex(/\d/, "Include a digit"),
});
type Form = z.infer<typeof schema>;

export default function SignupPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<unknown>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (v) => {
    setError(null);
    try {
      const r = await api<{ access_token: string }>("/auth/register", { method: "POST", body: v });
      await login(r.access_token);
      router.replace("/onboarding");
    } catch (e) {
      setError(e);
    }
  });

  return (
    <AuthFrame title="Start your 14-day free trial" footer={<>Already registered? <Link className="text-brand-700 hover:underline" href="/login">Sign in</Link></>}>
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <ErrorBox error={error} />
        <Field label="Company name" error={formState.errors.company_name?.message}><input className="input" {...register("company_name")} /></Field>
        <Field label="Industry">
          <select className="input" {...register("industry")}>
            <option value="">Select…</option>
            {["Real estate", "Education", "Healthcare", "BPO / Telecalling", "Telecom", "Services", "Other"].map((i) => <option key={i}>{i}</option>)}
          </select>
        </Field>
        <Field label="Your name" error={formState.errors.full_name?.message}><input className="input" autoComplete="name" {...register("full_name")} /></Field>
        <Field label="Work email" error={formState.errors.email?.message}><input className="input" type="email" autoComplete="email" {...register("email")} /></Field>
        <Field label="Password" error={formState.errors.password?.message} hint="10+ characters with letters and digits">
          <input className="input" type="password" autoComplete="new-password" {...register("password")} />
        </Field>
        <button className="btn-primary w-full" disabled={formState.isSubmitting}>{formState.isSubmitting ? "Creating…" : "Create account"}</button>
      </form>
    </AuthFrame>
  );
}
