"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, getTenantId, refreshSession, setAccessToken, setTenantId } from "@/lib/api";
import type { Me, Membership } from "@/types";

type AuthState = {
  me: Me | null;
  loading: boolean;
  membership: Membership | null;
  can: (perm: string) => boolean;
  hasCap: (key: string) => boolean;
  capsLoaded: boolean;
  refreshCaps: () => Promise<void>;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  switchTenant: (id: string) => void;
  reload: () => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false } } }),
  );
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [tenant, setTenant] = useState<string | null>(null);
  const [caps, setCaps] = useState<Record<string, boolean> | null>(null);

  const loadCaps = useCallback(async () => {
    try {
      const r = await api<{ capabilities: Record<string, boolean> }>("/me/capabilities");
      setCaps(r.capabilities);
    } catch {
      setCaps({});
    }
  }, []);

  const loadMe = useCallback(async () => {
    const data = await api<Me>("/auth/me");
    setMe(data);
    const stored = getTenantId();
    const pick = data.memberships.find((m) => m.tenant_id === stored) ?? data.memberships[0] ?? null;
    setTenantId(pick?.tenant_id ?? null);
    setTenant(pick?.tenant_id ?? null);
    if (pick) await loadCaps();
    else setCaps({});
  }, [loadCaps]);

  useEffect(() => {
    (async () => {
      try {
        if (await refreshSession()) await loadMe();
      } catch {
        setMe(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [loadMe]);

  const value = useMemo<AuthState>(() => {
    const membership = me?.memberships.find((m) => m.tenant_id === tenant) ?? null;
    return {
      me,
      loading,
      membership,
      can: (perm) => !!membership?.permissions.includes(perm),
      hasCap: (key) => !!caps?.[key],
      capsLoaded: caps !== null,
      refreshCaps: loadCaps,
      login: async (token) => {
        setAccessToken(token);
        await loadMe();
      },
      logout: async () => {
        await api("/auth/logout", { method: "POST" }).catch(() => undefined);
        setAccessToken(null);
        setTenantId(null);
        setMe(null);
        client.clear();
      },
      switchTenant: (id) => {
        setTenantId(id);
        setTenant(id);
        setCaps(null);
        client.clear();
        void loadCaps();
      },
      reload: loadMe,
    };
  }, [me, loading, tenant, loadMe, client, caps, loadCaps]);

  return (
    <QueryClientProvider client={client}>
      <Ctx.Provider value={value}>{children}</Ctx.Provider>
    </QueryClientProvider>
  );
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside Providers");
  return v;
}
