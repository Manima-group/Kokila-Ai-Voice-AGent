"use client";

import Link from "next/link";

import { Icon, type IconName } from "@/components/icons";
import { Badge } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Agent } from "@/types";

type Connector = { key: string; name: string; status: string; adapter: string };
type Overview = { calls: { total: number }; leads: { created: number } };
type Sub = { status: string; plan: { name: string }; minutes_used: number; minutes_included: number; current_period_end: string };
type Conv = { id: string; title: string; updated_at: string };

const STATUS_LABEL: Record<string, string> = { connected: "Connected", configured: "Configured", failed: "Needs attention", not_connected: "Not connected", not_available: "Coming soon" };

export default function OverviewPage() {
  const { me, membership, can, hasCap, capsLoaded } = useAuth();
  const calling = hasCap("product.calling_agent");
  const assistant = hasCap("product.business_assistant");
  const sub = useApi<Sub>(can("billing:read") ? "/billing/subscription" : null);
  const agents = useApi<Agent[]>(calling && can("agents:read") ? "/agents" : null);
  const today = useApi<Overview>(calling && can("analytics:read") ? "/analytics/overview?days=1" : null);
  const connectors = useApi<Connector[]>(membership ? "/connect/connectors" : null);
  const convs = useApi<Conv[]>(assistant && can("analytics:read") ? "/assistant/conversations?mode=business" : null);
  const connected = connectors.data?.filter((c) => c.status === "connected" || c.status === "configured") ?? [];
  const first = me?.full_name.split(" ")[0];

  return (
    <div>
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">Welcome back{first ? `, ${first}` : ""}</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight md:text-4xl">What would you like to do?</h1>
        </div>
        {sub.data && (
          <Link href="/billing" className="flex items-center gap-3 rounded-xl border border-line bg-white px-4 py-2.5 text-sm hover:border-brand-200">
            <span className="font-medium">{sub.data.plan.name}</span> <Badge>{sub.data.status}</Badge>
            <span className="text-muted">{sub.data.minutes_used}/{sub.data.minutes_included} min · until {fmtDate(sub.data.current_period_end).split(",")[0]}</span>
          </Link>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ProductCard
          icon="phone" title="Calling Agent" href="/calling-agent" cta="Open Calling Agent" locked={capsLoaded && !calling}
          description="Automate customer conversations with intelligent AI calling agents that answer inbound calls, qualify leads, conduct outbound campaigns and schedule appointments."
          stats={calling ? [
            { label: "Active agents", value: agents.data ? agents.data.filter((a) => a.status === "published").length : undefined },
            { label: "Today's calls", value: today.data?.calls.total },
            { label: "Leads today", value: today.data?.leads.created },
          ] : []}
        />
        <ProductCard
          icon="mic" title="Business Assistant" href="/assistant" cta="Open Business Assistant" locked={capsLoaded && !assistant}
          description="Talk to your business data, generate reports, understand documents, automate workflows and receive actionable business insights using voice or text."
          stats={assistant ? [
            { label: "Connected apps", value: connectors.data ? connected.length : undefined },
            { label: "Recent chats", value: convs.data?.length },
          ] : []}
          extra={assistant && (
            <Link href="/assistant/business" className="mt-4 flex items-center gap-3 rounded-xl bg-panel px-4 py-3 text-sm text-ink hover:bg-gray-100">
              <Icon name="chat" className="text-muted" /> {convs.data?.[0]?.title ?? "What were today's sales?"}
            </Link>
          )}
        />
      </div>

      <section className="mt-6 rounded-2xl border border-line bg-white p-5" aria-labelledby="integrations-heading">
        <div className="flex flex-col items-start gap-4 md:flex-row md:items-center">
          <h2 id="integrations-heading" className="flex items-center gap-3 text-lg font-semibold"><Icon name="puzzle" /> Integrations</h2>
          <div className="hidden h-8 w-px bg-line md:block" />
          <ul className="flex w-full flex-1 flex-wrap gap-2">
            {connectors.data?.map((c) => (
              <li key={c.key} title={STATUS_LABEL[c.status] ?? c.status}
                className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm ${c.status === "connected" || c.status === "configured" ? "bg-green-50 text-green-800" : c.adapter === "planned" ? "bg-panel text-muted" : "bg-panel text-ink"}`}>
                <span className={`h-2 w-2 rounded-full ${c.status === "connected" ? "bg-green-500" : c.status === "configured" ? "bg-green-400" : c.status === "failed" ? "bg-red-500" : "bg-gray-300"}`} aria-hidden />
                {c.name}
                <span className="sr-only">({STATUS_LABEL[c.status] ?? c.status})</span>
              </li>
            ))}
          </ul>
          {can("integrations:read") && (
            <Link href="/integrations" className="flex items-center gap-1 font-medium text-brand-700 hover:underline">Manage connections <Icon name="arrowRight" /></Link>
          )}
        </div>
      </section>
    </div>
  );
}

function ProductCard({ icon, title, description, href, cta, locked, stats, extra }: {
  icon: IconName; title: string; description: string; href: string; cta: string; locked: boolean;
  stats: { label: string; value: number | undefined }[]; extra?: React.ReactNode;
}) {
  const { can } = useAuth();
  return (
    <article className={`flex flex-col rounded-2xl border border-line bg-white p-6 md:p-8 ${locked ? "opacity-90" : ""}`}>
      <div className="flex items-start justify-between">
        <span className="grid h-14 w-14 place-items-center rounded-2xl bg-brand-50 text-brand-600"><Icon name={icon} className="h-7 w-7" /></span>
        {locked && <span className="flex items-center gap-1 rounded-full bg-panel px-3 py-1 text-xs font-medium text-muted"><Icon name="lock" className="h-4 w-4" /> Locked</span>}
      </div>
      <h2 className="mt-5 text-2xl font-bold">{title}</h2>
      <p className="mt-2 text-muted">{description}</p>
      {stats.length > 0 && (
        <dl className="mt-5 grid grid-cols-3 gap-3">
          {stats.map((s) => (
            <div key={s.label} className="rounded-xl bg-panel px-3 py-2">
              <dt className="text-xs text-muted">{s.label}</dt>
              <dd className="text-lg font-semibold">{s.value ?? <span className="inline-block h-5 w-8 animate-pulse rounded bg-gray-200" />}</dd>
            </div>
          ))}
        </dl>
      )}
      {extra}
      <div className="mt-auto pt-6">
        {locked ? (
          can("billing:read") ? <Link href="/billing" className="btn-secondary w-full py-3 text-base">Upgrade or request access</Link>
            : <p className="rounded-lg bg-panel px-4 py-3 text-center text-sm text-muted">Ask your organization admin to request access.</p>
        ) : (
          <Link href={href} className="btn-primary w-full py-3 text-base">{cta}</Link>
        )}
      </div>
    </article>
  );
}
