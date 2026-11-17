"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Loading } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const NAV: { href: string; label: string; perm?: string; section?: string }[] = [
  { href: "/dashboard", label: "Dashboard", perm: "analytics:read" },
  { href: "/agents", label: "Agents", perm: "agents:read", section: "Voice AI" },
  { href: "/voice-test", label: "Voice testing", perm: "agents:test" },
  { href: "/phone-numbers", label: "Phone numbers", perm: "phone_numbers:read" },
  { href: "/calls", label: "Call history", perm: "calls:read" },
  { href: "/contacts", label: "Contacts", perm: "contacts:read", section: "CRM" },
  { href: "/leads", label: "Leads", perm: "leads:read" },
  { href: "/campaigns", label: "Campaigns", perm: "campaigns:read" },
  { href: "/appointments", label: "Appointments", perm: "appointments:read" },
  { href: "/analytics", label: "Analytics", perm: "analytics:read", section: "Insights" },
  { href: "/integrations", label: "Integrations", perm: "integrations:read", section: "Organization" },
  { href: "/team", label: "Team", perm: "users:read" },
  { href: "/billing", label: "Billing", perm: "billing:read" },
  { href: "/settings", label: "Settings", perm: "tenant:write" },
  { href: "/audit", label: "Audit log", perm: "audit:read" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const { me, loading, membership, can, logout, switchTenant } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!loading && !me) router.replace(`/login?next=${encodeURIComponent(path)}`);
    if (!loading && me && !membership && me.is_superadmin && !path.startsWith("/admin")) router.replace("/admin");
  }, [loading, me, membership, router, path]);

  if (loading || !me) return <Loading label="Checking your session…" />;

  const items = NAV.filter((n) => !n.perm || can(n.perm));
  return (
    <div className="flex min-h-screen bg-panel">
      <aside className={`${open ? "block" : "hidden"} fixed inset-y-0 z-40 w-64 border-r border-line bg-white md:static md:block`}>
        <div className="flex h-16 items-center gap-2 border-b border-line px-5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 font-bold text-white">K</span>
          <span className="text-lg font-semibold">Kokila</span>
        </div>
        <nav className="space-y-0.5 p-3" aria-label="Main">
          {items.map((n) => (
            <div key={n.href}>
              {n.section && <div className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted">{n.section}</div>}
              <Link href={n.href} onClick={() => setOpen(false)}
                className={`block rounded-lg px-3 py-2 text-sm ${path.startsWith(n.href) ? "bg-brand-50 font-medium text-brand-700" : "text-ink hover:bg-panel"}`}>
                {n.label}
              </Link>
            </div>
          ))}
          {me.is_superadmin && (
            <div>
              <div className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted">Platform</div>
              <Link href="/admin" className={`block rounded-lg px-3 py-2 text-sm ${path.startsWith("/admin") ? "bg-brand-50 font-medium text-brand-700" : "hover:bg-panel"}`}>Super Admin</Link>
            </div>
          )}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between gap-3 border-b border-line bg-white px-4 md:px-8">
          <button className="btn-secondary md:hidden" onClick={() => setOpen(!open)} aria-label="Toggle navigation">☰</button>
          <div className="flex items-center gap-2 text-sm">
            {me.memberships.length > 1 ? (
              <select className="input w-56" value={membership?.tenant_id} onChange={(e) => switchTenant(e.target.value)} aria-label="Organization">
                {me.memberships.map((m) => <option key={m.tenant_id} value={m.tenant_id}>{m.tenant_name}</option>)}
              </select>
            ) : (
              <span className="font-medium">{membership?.tenant_name ?? "Platform"}</span>
            )}
            {membership && <span className="rounded bg-panel px-2 py-0.5 text-xs text-muted">{membership.role.replace("_", " ")}</span>}
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-muted sm:inline">{me.email}</span>
            <button className="btn-secondary" onClick={async () => { await logout(); router.replace("/login"); }}>Sign out</button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
