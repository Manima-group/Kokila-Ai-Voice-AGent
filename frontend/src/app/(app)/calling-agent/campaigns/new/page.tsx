"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ErrorBox, Field, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { Agent, PhoneNumber } from "@/types";

const hm = z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/, "HH:MM");
const schema = z
  .object({
    name: z.string().min(2, "Name required"),
    purpose: z.string().min(2, "Purpose required"),
    agent_id: z.string().uuid("Pick a published agent"),
    from_phone_number_id: z.string().uuid("Pick an outbound-enabled number"),
    window_start: hm,
    window_end: hm,
    max_concurrency: z.coerce.number().int().min(1).max(100),
    max_attempts: z.coerce.number().int().min(1).max(5),
    retry_delay_minutes: z.coerce.number().int().min(15).max(10080),
    description: z.string().optional(),
  })
  .refine((v) => v.window_end > v.window_start, { message: "End must be after start", path: ["window_end"] });
type Form = z.input<typeof schema>;
type Out = z.output<typeof schema>;

export default function NewCampaign() {
  const router = useRouter();
  const agents = useApi<Agent[]>("/agents");
  const numbers = useApi<PhoneNumber[]>("/phone-numbers");
  const [error, setError] = useState<unknown>(null);
  const { register, handleSubmit, formState } = useForm<Form, unknown, Out>({
    resolver: zodResolver(schema),
    defaultValues: { purpose: "sales", window_start: "10:00", window_end: "19:00", max_concurrency: 2, max_attempts: 2, retry_delay_minutes: 120 },
  });
  const submit = handleSubmit(async (v) => {
    setError(null);
    try {
      const c = await api<{ id: string }>("/campaigns", { method: "POST", body: { ...v, timezone: "Asia/Kolkata", days_of_week: [0, 1, 2, 3, 4, 5] } });
      router.push(`/calling-agent/campaigns/${c.id}`);
    } catch (e) {
      setError(e);
    }
  });
  const e = formState.errors;
  return (
    <div className="max-w-2xl">
      <PageHeader title="New campaign" subtitle="Calls are additionally restricted to 09:00–21:00 IST regardless of this window." />
      <form onSubmit={submit} className="card space-y-4" noValidate>
        <ErrorBox error={error} />
        <Field label="Name" error={e.name?.message}><input className="input" {...register("name")} /></Field>
        <Field label="Purpose" error={e.purpose?.message} hint="Contacts need a granted consent with this exact purpose"><input className="input" {...register("purpose")} /></Field>
        <Field label="Agent" error={e.agent_id?.message}>
          <select className="input" {...register("agent_id")}><option value="">Select…</option>{agents.data?.filter((a) => a.status === "published").map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select>
        </Field>
        <Field label="Caller ID number" error={e.from_phone_number_id?.message}>
          <select className="input" {...register("from_phone_number_id")}><option value="">Select…</option>{numbers.data?.filter((n) => n.outbound_enabled).map((n) => <option key={n.id} value={n.id}>{n.e164} {n.label ? `(${n.label})` : ""}</option>)}</select>
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Window start" error={e.window_start?.message}><input className="input" {...register("window_start")} /></Field>
          <Field label="Window end" error={e.window_end?.message}><input className="input" {...register("window_end")} /></Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Max concurrent calls" error={e.max_concurrency?.message}><input className="input" type="number" {...register("max_concurrency")} /></Field>
          <Field label="Max attempts" error={e.max_attempts?.message}><input className="input" type="number" {...register("max_attempts")} /></Field>
          <Field label="Retry delay (min)" error={e.retry_delay_minutes?.message}><input className="input" type="number" {...register("retry_delay_minutes")} /></Field>
        </div>
        <Field label="Description"><textarea className="input" rows={2} {...register("description")} /></Field>
        <button className="btn-primary" disabled={formState.isSubmitting}>Create draft</button>
      </form>
    </div>
  );
}
