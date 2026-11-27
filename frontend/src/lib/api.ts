// Thin API client. Access token lives in memory; the refresh token is an httpOnly cookie set by the API.
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const TENANT_KEY = "kokila.tenant";

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getTenantId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TENANT_KEY);
}

export function setTenantId(id: string | null) {
  if (typeof window === "undefined") return;
  if (id) window.localStorage.setItem(TENANT_KEY, id);
  else window.localStorage.removeItem(TENANT_KEY);
}

export async function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) {
          accessToken = null;
          return false;
        }
        accessToken = (await r.json()).access_token;
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

type Options = { method?: string; body?: unknown; form?: FormData; retry?: boolean };

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const tenant = getTenantId();
  if (tenant) headers["X-Tenant-ID"] = tenant;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(`/api/v1${path}`, { method: opts.method ?? "GET", headers, body, credentials: "same-origin" });
  if (res.status === 401 && opts.retry !== false && !path.startsWith("/auth/")) {
    if (await refreshSession()) return api<T>(path, { ...opts, retry: false });
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? "error", err.message ?? `Request failed (${res.status})`, err.details);
  }
  return data as T;
}

export const fmtDate = (v?: string | null) => (v ? new Date(v).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—");
export const fmtINR = (minor?: number | null) =>
  minor == null ? "—" : (minor / 100).toLocaleString("en-IN", { style: "currency", currency: "INR" });
