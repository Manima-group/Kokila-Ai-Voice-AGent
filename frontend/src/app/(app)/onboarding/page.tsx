"use client";

import Link from "next/link";

import { PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import type { Agent, PhoneNumber } from "@/types";

export default function Onboarding() {
  const agents = useApi<Agent[]>("/agents");
  const numbers = useApi<PhoneNumber[]>("/phone-numbers");
  const cals = useApi<unknown[]>("/calendar-connections");
  const tenant = useApi<{ compliance: { status?: string } }>("/tenants/current");
  const steps = [
    { done: !!agents.data?.length, title: "Create your first voice agent", body: "Pick a template and customise greeting, languages and rules.", href: "/agents/new" },
    { done: !!agents.data?.some((a) => a.status === "published"), title: "Publish and test it", body: "Publishing syncs the agent to the voice provider. Try a simulated call.", href: "/voice-test" },
    { done: !!numbers.data?.length, title: "Connect a business number", body: "Route inbound calls on your number to the agent.", href: "/phone-numbers" },
    { done: !!cals.data?.length, title: "Set up appointments", body: "Use the Kokila calendar or connect Google Calendar.", href: "/appointments" },
    { done: !!tenant.data?.compliance?.status, title: "Submit compliance profile (for outbound)", body: "Required before live outbound campaigns.", href: "/settings" },
  ];
  return (
    <div className="max-w-2xl">
      <PageHeader title="Get started with Kokila" subtitle="Your 14-day trial includes 30 minutes for inbound calls and testing." />
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={s.title} className="card flex items-start gap-4">
            <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-semibold ${s.done ? "bg-green-100 text-green-700" : "bg-brand-50 text-brand-700"}`}>{s.done ? "✓" : i + 1}</span>
            <div className="flex-1"><div className="font-medium">{s.title}</div><p className="text-sm text-muted">{s.body}</p></div>
            <Link className="btn-secondary" href={s.href}>{s.done ? "Review" : "Start"}</Link>
          </li>
        ))}
      </ol>
      <Link href="/overview" className="btn-primary mt-6">Go to dashboard</Link>
    </div>
  );
}
