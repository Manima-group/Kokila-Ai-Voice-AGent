"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export function useApi<T>(path: string | null, opts: { enabled?: boolean; refetchInterval?: number } = {}) {
  const { membership, me } = useAuth();
  return useQuery<T>({
    queryKey: [membership?.tenant_id ?? "platform", path],
    queryFn: () => api<T>(path as string),
    enabled: !!path && !!me && (opts.enabled ?? true),
    refetchInterval: opts.refetchInterval,
  });
}

export function useMutate<TBody = unknown, TRes = unknown>(
  method: string,
  path: string | ((b: TBody) => string),
  invalidate: string[] = [],
  toBody: (b: TBody) => unknown = (b) => b,
) {
  const qc = useQueryClient();
  return useMutation<TRes, Error, TBody>({
    mutationFn: (body: TBody) => api<TRes>(typeof path === "function" ? path(body) : path, { method, body: toBody(body) }),
    onSuccess: () => {
      invalidate.forEach((p) => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[1] ?? "").startsWith(p) }));
    },
  });
}
