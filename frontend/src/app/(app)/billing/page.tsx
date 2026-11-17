"use client";

import { useState } from "react";

import { Badge, Empty, ErrorBox, Loading, PageHeader, Stat, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, fmtDate, fmtINR } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Page } from "@/types";

type Plan = { id: string; code: string; name: string; price_minor: number; included_minutes: number; max_agents: number; max_concurrent_calls: number; max_users: number; features: Record<string, boolean>; overage_per_minute_minor: number | null };
type Sub = { status: string; plan: Plan; minutes_used: number; minutes_included: number; current_period_end: string; billing_configured: boolean };
type Payment = { id: string; razorpay_order_id: string; amount_minor: number; status: string; created_at: string };
type Invoice = { id: string; number: string; total_minor: number; tax_minor: number; status: string; period_start: string; period_end: string; created_at: string };

declare global {
  interface Window {
    Razorpay?: new (opts: Record<string, unknown>) => { open: () => void };
  }
}

function loadCheckout(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.Razorpay) return resolve();
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Could not load Razorpay checkout"));
    document.body.appendChild(s);
  });
}

export default function Billing() {
  const { can } = useAuth();
  const sub = useApi<Sub>("/billing/subscription");
  const plans = useApi<Plan[]>("/billing/plans");
  const payments = useApi<Page<Payment>>("/billing/payments");
  const invoices = useApi<Page<Invoice>>("/billing/invoices");
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const buy = async (code: string) => {
    setError(null);
    setMsg(null);
    try {
      const order = await api<{ order_id: string; amount_minor: number; currency: string; key_id: string }>("/billing/checkout", { method: "POST", body: { plan_code: code } });
      await loadCheckout();
      new window.Razorpay!({
        key: order.key_id, amount: order.amount_minor, currency: order.currency, order_id: order.order_id, name: "Kokila", description: `Plan: ${code}`,
        theme: { color: "#ea580c" },
        handler: async (resp: Record<string, string>) => {
          const r = await api<{ message: string }>("/billing/verify", { method: "POST", body: resp });
          setMsg(r.message);
          payments.refetch();
        },
      }).open();
    } catch (e) {
      setError(e);
    }
  };

  if (sub.isLoading) return <Loading />;
  const s = sub.data;
  return (
    <div>
      <PageHeader title="Billing" subtitle="Plans activate only after Razorpay confirms payment capture via a signed webhook. Prices exclude 18% GST." />
      <ErrorBox error={error || sub.error} />
      {msg && <div className="mb-3 rounded-lg bg-green-50 px-4 py-2 text-sm text-green-700">{msg}</div>}
      {s && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="Current plan" value={<>{s.plan.name} <Badge>{s.status}</Badge></>} hint={`Period ends ${fmtDate(s.current_period_end)}`} />
          <Stat label="Minutes used" value={`${s.minutes_used} / ${s.minutes_included}`} hint="Billable minutes are rounded up per call" />
          <Stat label="Limits" value={`${s.plan.max_agents} agents`} hint={`${s.plan.max_concurrent_calls} concurrent calls · ${s.plan.max_users} users`} />
        </div>
      )}
      {s && !s.billing_configured && <p className="mt-3 text-sm text-muted">Online payments are not configured on this deployment yet.</p>}
      <h2 className="mb-3 mt-8 font-semibold">Plans</h2>
      {plans.data?.length ? (
        <div className="grid gap-4 md:grid-cols-3">
          {plans.data.map((p) => (
            <div key={p.id} className={`card ${s?.plan.code === p.code ? "border-brand-500" : ""}`}>
              <div className="font-semibold">{p.name}</div>
              <div className="mt-1 text-2xl font-bold">{fmtINR(p.price_minor)}<span className="text-sm font-normal text-muted">/month</span></div>
              <ul className="mt-3 space-y-1 text-sm text-muted">
                <li>{p.included_minutes} minutes included</li>
                <li>{p.overage_per_minute_minor != null ? `Overage ${fmtINR(p.overage_per_minute_minor)}/min` : "Hard cap, no overage"}</li>
                <li>{p.max_agents} agents · {p.max_concurrent_calls} concurrent calls · {p.max_users} users</li>
                <li>Outbound campaigns: {p.features.outbound ? "yes" : "no"}</li>
              </ul>
              {can("billing:write") && p.price_minor > 0 && s?.plan.code !== p.code && <button className="btn-primary mt-4 w-full" onClick={() => buy(p.code)}>Choose {p.name}</button>}
            </div>
          ))}
        </div>
      ) : <Empty title="No public plans published yet" body="Plans are configured by the platform administrator." />}
      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 font-semibold">Invoices</h2>
          {invoices.data?.items.length ? (
            <Table head={["Number", "Period", "GST", "Total", "Status"]}>
              {invoices.data.items.map((i) => <tr key={i.id}><td className="td font-mono text-xs">{i.number}</td><td className="td text-xs">{fmtDate(i.period_start)} – {fmtDate(i.period_end)}</td><td className="td">{fmtINR(i.tax_minor)}</td><td className="td">{fmtINR(i.total_minor)}</td><td className="td"><Badge>{i.status}</Badge></td></tr>)}
            </Table>
          ) : <p className="text-sm text-muted">No invoices yet.</p>}
        </div>
        <div>
          <h2 className="mb-3 font-semibold">Payment history</h2>
          {payments.data?.items.length ? (
            <Table head={["Order", "Amount", "Status", "Date"]}>
              {payments.data.items.map((p) => <tr key={p.id}><td className="td font-mono text-xs">{p.razorpay_order_id}</td><td className="td">{fmtINR(p.amount_minor)}</td><td className="td"><Badge>{p.status}</Badge></td><td className="td">{fmtDate(p.created_at)}</td></tr>)}
            </Table>
          ) : <p className="text-sm text-muted">No payments yet.</p>}
        </div>
      </div>
    </div>
  );
}
