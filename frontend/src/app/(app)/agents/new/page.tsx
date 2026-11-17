"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ErrorBox, Field, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";

type Templates = { templates: Record<string, { label: string; tools: string[] }>; languages: Record<string, string> };
const schema = z.object({ name: z.string().min(2, "Name required").max(120), description: z.string().max(500).optional(), template: z.string().min(1, "Pick a template") });
type Form = z.infer<typeof schema>;

export default function NewAgent() {
  const router = useRouter();
  const t = useApi<Templates>("/agents/templates");
  const [step, setStep] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const { register, handleSubmit, watch, setValue, formState } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { template: "" } });
  const template = watch("template");

  const submit = handleSubmit(async (v) => {
    setError(null);
    try {
      const a = await api<{ id: string }>("/agents", { method: "POST", body: v });
      router.push(`/agents/${a.id}?created=1`);
    } catch (e) {
      setError(e);
    }
  });

  if (t.isLoading) return <Loading />;
  return (
    <div className="max-w-3xl">
      <PageHeader title="Create a voice agent" subtitle={`Step ${step} of 2`} />
      <ErrorBox error={t.error || error} />
      {step === 1 && t.data && (
        <div>
          <div className="grid gap-3 sm:grid-cols-2">
            {Object.entries(t.data.templates).map(([key, tpl]) => (
              <button type="button" key={key} onClick={() => setValue("template", key, { shouldValidate: true })}
                className={`card text-left transition ${template === key ? "border-brand-500 ring-2 ring-brand-100" : "hover:border-brand-200"}`}>
                <div className="font-medium">{tpl.label}</div>
                <div className="mt-1 text-xs text-muted">Tools: {tpl.tools.join(", ").replace(/_/g, " ")}</div>
              </button>
            ))}
          </div>
          <div className="mt-6 flex justify-end"><button className="btn-primary" disabled={!template} onClick={() => setStep(2)}>Continue</button></div>
        </div>
      )}
      {step === 2 && (
        <form onSubmit={submit} className="card space-y-4" noValidate>
          <Field label="Agent name" error={formState.errors.name?.message}><input className="input" {...register("name")} placeholder="e.g. Admissions Desk" /></Field>
          <Field label="Description"><textarea className="input" rows={3} {...register("description")} /></Field>
          <p className="text-sm text-muted">The template pre-fills greeting, instructions and tools. You can edit languages, voice, knowledge and rules on the next screen before publishing.</p>
          <div className="flex justify-between">
            <button type="button" className="btn-secondary" onClick={() => setStep(1)}>Back</button>
            <button className="btn-primary" disabled={formState.isSubmitting}>Create draft</button>
          </div>
        </form>
      )}
    </div>
  );
}
