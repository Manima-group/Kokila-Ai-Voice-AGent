import { NextResponse } from "next/server";
import { API_ORIGIN, requireClientHeader, setTokens, type TokenPayload } from "@/lib/server/session";

export async function POST(req: Request) {
  const denied = requireClientHeader(req);
  if (denied) return denied;
  const body = await req.text();
  const r = await fetch(`${API_ORIGIN}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Forwarded-For": req.headers.get("x-forwarded-for") ?? "" },
    body,
    cache: "no-store",
  });
  const data = await r.json();
  if (!r.ok) return NextResponse.json(data, { status: r.status });
  const t = data as TokenPayload;
  const res = NextResponse.json({ workspace_id: t.workspace_id, platform: t.platform, mfa: t.mfa });
  setTokens(res, t);
  return res;
}
