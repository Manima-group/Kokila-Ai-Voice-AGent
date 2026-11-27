"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Icon, type IconName } from "@/components/icons";
import { Loading } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate } from "@/lib/api";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type NavItem = { href: string; label: string; icon: IconName; perm?: string; cap?: string; exact?: boolean };

const PLATFORM_NAV: NavItem[] = [
  { href: "/overview", label: "Overview", icon: "home" },
  { href: "/calling-agent", label: "Calling Agent", icon: "phone" },
  { href: "/assistant", label: "Business Assistant", icon: "mic" },
  { href: "/integrations", label: "Integrations", icon: "puzzle", perm: "integrations:read" },
  { href: "/billing", label: "Billing", icon: "card", perm: "billing:read" },
  { href: "/settings", label: "Settings", icon: "gear" },
  { href: "/help", label: "Help & Support", icon: "help" },
];

const CALLING_NAV: NavItem[] = [
  { href: "/calling-agent", label: "Overview", icon: "home", exact: true, perm: "analytics:read" },
  { href: "/calling-agent/agents", label: "AI Agent Builder", icon: "bot", perm: "agents:read" },
  { href: "/calling-agent/voice-test", label: "Voice testing", icon: "mic", perm: "agents:test" },
  { href: "/calling-agent/phone-numbers", label: "Phone numbers", icon: "phone", perm: "phone_numbers:read" },
  { href: "/calling-agent/calls", label: "Call history", icon: "list", perm: "calls:read" },
  { href: "/calling-agent/campaigns", label: "Outbound campaigns", icon: "megaphone", perm: "campaigns:read", cap: "voice.outbound" },
  { href: "/calling-agent/contacts", label: "Contacts", icon: "users", perm: "contacts:read" },
  { href: "/calling-agent/leads", label: "Leads", icon: "target", perm: "leads:read" },
  { href: "/calling-agent/appointments", label: "Appointments", icon: "calendar", perm: "appointments:read" },
  { href: "/calling-agent/analytics", label: "Analytics", icon: "chart", perm: "analytics:read" },
  { href: "/calling-agent/automations", label: "Automations", icon: "bolt", perm: "integrations:read" },
];

const ASSISTANT_NAV: NavItem[] = [
  { href: "/assistant", label: "Home", icon: "home", exact: true },
  { href: "/assistant/business", label: "Business mode", icon: "chart", perm: "analytics:read" },
  { href: "/assistant/personal", label: "Personal mode", icon: "user", cap: "assistant.personal" },
];

const PRODUCT_CAP: Record<string, string> = { "/calling-agent": "product.calling_agent", "/assistant": "product.business_assistant" };

export function product(path: string): "calling-agent" | "assistant" | null {
  if (path.startsWith("/calling-agent")) return "calling-agent";
  if (path.startsWith("/assistant")) return "assistant";
  return null;
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const { me, loading, membership, can, hasCap, capsLoaded, logout, switchTenant } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const prod = product(path);

  useEffect(() => {
    if (!loading && !me) router.replace(`/login?next=${encodeURIComponent(path)}`);
    if (!loading && me && !membership && me.is_superadmin && !path.startsWith("/admin")) router.replace("/admin");
  }, [loading, me, membership, router, path]);

  if (loading || !me) return <Loading label="Checking your session…" />;

  const nav = prod === "calling-agent" ? CALLING_NAV : prod === "assistant" ? ASSISTANT_NAV : PLATFORM_NAV;
  const items = nav.filter((n) => (!n.perm || can(n.perm)) && (!n.cap || hasCap(n.cap)));
  const active = (n: NavItem) => (n.exact ? path === n.href : path === n.href || path.startsWith(`${n.href}/`));
  const productKey = prod ? PRODUCT_CAP[`/${prod}`] : null;
  const locked = productKey && capsLoaded && !hasCap(productKey);

  return (
    <div className="flex min-h-screen bg-panel">
      <aside className={`${open ? "block" : "hidden"} fixed inset-y-0 z-40 w-64 border-r border-line bg-white md:static md:block`} aria-label="Sidebar">
        <div className="flex h-16 items-center gap-2 border-b border-line px-5 md:hidden">
          <Logo />
        </div>
        <nav className="space-y-1 p-3" aria-label="Main">
          {prod && (
            <div className="mb-3 space-y-2 border-b border-line pb-3">
              <Link href="/overview" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted hover:bg-panel">
                <Icon name="arrowLeft" /> Back to Overview
              </Link>
              <ProductSwitcher current={prod} />
            </div>
          )}
          {items.map((n) => (
            <Link key={n.href} href={n.href} onClick={() => setOpen(false)}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${active(n) ? "bg-brand-50 font-medium text-brand-700" : "text-ink hover:bg-panel"}`}>
              <Icon name={n.icon} className={active(n) ? "text-brand-600" : "text-muted"} />
              {n.label}
            </Link>
          ))}
          {!prod && can("audit:read") && (
            <Link href="/audit" className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${path.startsWith("/audit") ? "bg-brand-50 font-medium text-brand-700" : "hover:bg-panel"}`}>
              <Icon name="shield" className="text-muted" /> Audit log
            </Link>
          )}
          {me.is_superadmin && (
            <Link href="/admin" className={`mt-2 flex items-center gap-3 rounded-lg border border-dashed border-line px-3 py-2.5 text-sm ${path.startsWith("/admin") ? "bg-brand-50 font-medium text-brand-700" : "hover:bg-panel"}`}>
              <Icon name="crown" className="text-brand-600" /> Manima Super Admin
            </Link>
          )}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between gap-3 border-b border-line bg-white px-4 md:px-8">
          <div className="flex items-center gap-3">
            <button className="btn-secondary px-2 md:hidden" onClick={() => setOpen(!open)} aria-label="Toggle navigation"><Icon name="menu" /></button>
            <div className="hidden md:block"><Logo /></div>
          </div>
          <div className="flex items-center gap-2 text-sm md:gap-3">
            {me.memberships.length > 1 ? (
              <select className="input w-48 md:w-60" value={membership?.tenant_id} onChange={(e) => switchTenant(e.target.value)} aria-label="Organization">
                {me.memberships.map((m) => <option key={m.tenant_id} value={m.tenant_id}>{m.tenant_name}</option>)}
              </select>
            ) : membership ? (
              <span className="hidden rounded-lg border border-line px-3 py-2 font-medium sm:inline">{membership.tenant_name}</span>
            ) : null}
            {membership && <Notifications />}
            <ProfileMenu name={me.full_name} email={me.email} role={membership?.role} onSignOut={async () => { await logout(); router.replace("/login"); }} />
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-8">{locked ? <LockedProduct productKey={productKey} /> : children}</main>
      </div>
    </div>
  );
}

export function Logo() {
  return (
    <Link href="/overview" className="flex items-center gap-3" aria-label="Kokila home">
      <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-600 text-lg font-bold text-white">K</span>
      <span className="text-xl font-bold tracking-tight">Kokila</span>
      <span className="hidden border-l border-line pl-3 text-sm text-muted lg:inline">by Manima AI-Tech Solutions</span>
    </Link>
  );
}

function ProductSwitcher({ current }: { current: "calling-agent" | "assistant" }) {
  const { hasCap } = useAuth();
  const router = useRouter();
  return (
    <label className="block px-1">
      <span className="sr-only">Switch product</span>
      <select className="input" value={current} onChange={(e) => router.push(`/${e.target.value}`)}>
        <option value="calling-agent">Calling Agent{hasCap("product.calling_agent") ? "" : " (locked)"}</option>
        <option value="assistant">Business Assistant{hasCap("product.business_assistant") ? "" : " (locked)"}</option>
      </select>
    </label>
  );
}

export function LockedProduct({ productKey }: { productKey: string }) {
  const { can } = useAuth();
  const name = productKey === "product.calling_agent" ? "Calling Agent" : "Business Assistant";
  return (
    <div className="mx-auto mt-12 max-w-lg rounded-2xl border border-line bg-white p-10 text-center">
      <span className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-brand-50 text-brand-600"><Icon name="lock" className="h-7 w-7" /></span>
      <h1 className="text-xl font-semibold">{name} is not enabled for your organization</h1>
      <p className="mt-2 text-sm text-muted">Access is controlled by your subscription. {can("billing:write") ? "Upgrade your plan or request access from Manima." : "Ask your organization admin to request access."}</p>
      <div className="mt-6 flex justify-center gap-3">
        <Link className="btn-secondary" href="/overview">Back to Overview</Link>
        {can("billing:read") && <Link className="btn-primary" href="/billing">Upgrade or request access</Link>}
      </div>
    </div>
  );
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const q = useApi<{ unread: number; items: { id: string; title: string; body: string | null; link: string | null; read: boolean; created_at: string }[] }>("/notifications", { refetchInterval: 30000 });
  return (
    <div className="relative">
      <button className="btn-secondary relative px-2.5" aria-label={`Notifications${q.data?.unread ? `, ${q.data.unread} unread` : ""}`} onClick={() => setOpen(!open)}>
        <Icon name="bell" />
        {!!q.data?.unread && <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-brand-600 px-1 text-[11px] font-semibold text-white">{q.data.unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 rounded-xl border border-line bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-line px-4 py-2">
            <span className="text-sm font-semibold">Notifications</span>
            <button className="text-xs text-brand-700 hover:underline" onClick={async () => { await api("/notifications/read-all", { method: "POST" }); q.refetch(); }}>Mark all read</button>
          </div>
          <ul className="max-h-80 divide-y divide-line overflow-y-auto">
            {q.data?.items.length ? q.data.items.map((n) => (
              <li key={n.id} className={`px-4 py-3 text-sm ${n.read ? "" : "bg-brand-50/50"}`}>
                {n.link ? <Link href={n.link} className="font-medium hover:underline" onClick={() => setOpen(false)}>{n.title}</Link> : <span className="font-medium">{n.title}</span>}
                {n.body && <p className="text-muted">{n.body}</p>}
                <p className="text-xs text-muted">{fmtDate(n.created_at)}</p>
              </li>
            )) : <li className="px-4 py-6 text-center text-sm text-muted">No notifications</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

function ProfileMenu({ name, email, role, onSignOut }: { name: string; email: string; role?: string; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const initials = name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div className="relative">
      <button className="grid h-10 w-10 place-items-center rounded-full bg-brand-100 font-semibold text-brand-700" aria-label="Profile menu" onClick={() => setOpen(!open)}>{initials}</button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-64 rounded-xl border border-line bg-white p-2 shadow-lg">
          <div className="px-3 py-2">
            <div className="font-medium">{name}</div>
            <div className="text-xs text-muted">{email}</div>
            {role && <div className="mt-1 text-xs text-muted">{role.replace("_", " ")}</div>}
          </div>
          <Link href="/settings" className="block rounded-lg px-3 py-2 text-sm hover:bg-panel" onClick={() => setOpen(false)}>Settings</Link>
          <button className="block w-full rounded-lg px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50" onClick={onSignOut}>Sign out</button>
        </div>
      )}
    </div>
  );
}
