import "server-only";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

/**
 * Backend-for-frontend session handling. Tokens live only in HttpOnly, SameSite=Strict cookies, so browser
 * JavaScript never sees them (§31.4). Mutations additionally require the X-Kokila-Client header, which a
 * cross-site form cannot set without a CORS preflight (CSRF defence in depth).
 */
export const API_ORIGIN = process.env.KOKILA_API_ORIGIN ?? "http://localhost:8000";
const SECURE = process.env.NODE_ENV === "production";
export const AT = "kokila_at";
export const RT = "kokila_rt";

export type TokenPayload = {
  access_token: string;
  refresh_token: string;
  expires_at: string;
  workspace_id: string | null;
  platform: boolean;
  mfa: boolean;
};

export function setTokens(res: NextResponse, t: TokenPayload): void {
  res.cookies.set(AT, t.access_token, { httpOnly: true, secure: SECURE, sameSite: "strict", path: "/", maxAge: 900 });
  res.cookies.set(RT, t.refresh_token, {
    httpOnly: true, secure: SECURE, sameSite: "strict", path: "/api", maxAge: 60 * 60 * 24 * 14,
  });
}

export function clearTokens(res: NextResponse): void {
  res.cookies.set(AT, "", { httpOnly: true, secure: SECURE, sameSite: "strict", path: "/", maxAge: 0 });
  res.cookies.set(RT, "", { httpOnly: true, secure: SECURE, sameSite: "strict", path: "/api", maxAge: 0 });
}

export async function readTokens(): Promise<{ at?: string; rt?: string }> {
  const jar = await cookies();
  return { at: jar.get(AT)?.value, rt: jar.get(RT)?.value };
}

export function requireClientHeader(req: Request): NextResponse | null {
  if (req.method !== "GET" && req.headers.get("x-kokila-client") !== "web") {
    return NextResponse.json(
      { error: { code: "forbidden", message: "missing client header", trace_id: null, retryable: false } },
      { status: 403 },
    );
  }
  return null;
}

export async function refresh(rt: string, workspaceId?: string): Promise<TokenPayload | null> {
  const r = await fetch(`${API_ORIGIN}/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt, ...(workspaceId ? { workspace_id: workspaceId } : {}) }),
    cache: "no-store",
  });
  return r.ok ? ((await r.json()) as TokenPayload) : null;
}
