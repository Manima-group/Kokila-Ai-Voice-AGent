"use client";

/** Browser client for the Kokila BFF. Tokens are never visible to this code (HttpOnly cookies). */

export type ApiError = { code: string; message: string; trace_id: string | null; retryable: boolean; details?: unknown };

export class KokilaApiError extends Error {
  constructor(public status: number, public error: ApiError) {
    super(error.message);
  }
}

async function call<T>(method: string, path: string, body?: unknown, idempotencyKey?: string): Promise<T> {
  const headers: Record<string, string> = { "X-Kokila-Client": "web" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                                credentials: "same-origin", cache: "no-store" });
  if (r.status === 204) return undefined as T;
  let data: unknown = null;
  try {
    data = await r.json();
  } catch {
    data = null;
  }
  if (!r.ok) {
    const err = (data as { error?: ApiError } | null)?.error ?? {
      code: "network_error", message: `request failed (${r.status})`, trace_id: null, retryable: true,
    };
    throw new KokilaApiError(r.status, err);
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => call<T>("GET", `/api/k/${p}`),
  post: <T>(p: string, body?: unknown, idem?: string) => call<T>("POST", `/api/k/${p}`, body ?? {}, idem),
  patch: <T>(p: string, body: unknown) => call<T>("PATCH", `/api/k/${p}`, body),
  put: <T>(p: string, body: unknown) => call<T>("PUT", `/api/k/${p}`, body),
  del: <T>(p: string) => call<T>("DELETE", `/api/k/${p}`),
  login: (body: unknown) => call<{ workspace_id: string | null; platform: boolean; mfa: boolean }>(
    "POST", "/api/auth/login", body),
  register: (body: unknown) => call<{ status: string; message: string }>("POST", "/api/auth/register", body),
  logout: () => call<void>("POST", "/api/auth/logout", {}),
};

export function newKey(prefix = "k"): string {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "")}`.slice(0, 64);
}

export function deviceId(): string {
  try {
    const k = "kokila.device_id";
    let v = localStorage.getItem(k);
    if (!v) {
      v = `dev-${crypto.randomUUID().replaceAll("-", "").slice(0, 24)}`;
      localStorage.setItem(k, v);
    }
    return v;
  } catch {
    return `dev-${crypto.randomUUID().replaceAll("-", "").slice(0, 24)}`;
  }
}

// --- API shapes ---------------------------------------------------------------------------------------
export type Me = {
  id: string; email: string; display_name: string; locale: string; timezone: string; mfa_enabled: boolean;
  platform_role: string | null; workspace_id: string | null; role: string | null;
};
export type Capabilities = {
  workspace_id: string; revision: number; enabled: string[]; permissions: string[];
  capabilities: Record<string, { enabled: boolean; reason: string | null }>;
};
export type Session = {
  id: string; conversation_id: string; channel: string; locale: string; state: string; generation: number;
  last_sequence: number; mic_muted: boolean; speaker_muted: boolean; revision: number; device_id: string;
};
export type Msg = {
  id: string; turn_id: string; sequence: number; role: "user" | "assistant" | "tool" | "system"; content: string;
  language: string | null; status: string; played_chars: number | null; dev_mock: boolean; tool_key: string | null;
};
export type ToolRun = {
  run_id: string | null; tool_key: string; status: string; side_effect: string; args: Record<string, unknown>;
  args_hash: string | null; result: unknown; error_code: string | null;
  approval: { id: string; summary: string; decision: string; expires_at: string; args_hash: string } | null;
};
export type Turn = {
  turn_id: string; state: string; language: string; stale: boolean; replayed: boolean; user_message: Msg;
  assistant_message: Msg | null; tool_runs: ToolRun[]; speak: string | null;
};
export type Identity = {
  effective: { display_name: string; spoken_name: string; aliases: string[]; locale: string; response_length: string;
               speaking_rate: number; wake_status: string; source_scope: string; customization_enabled: boolean;
               personal_override_allowed: boolean };
  editable_fields: string[]; revision: number; source_scope: string;
};
