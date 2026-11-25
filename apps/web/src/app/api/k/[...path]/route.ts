import { NextResponse } from "next/server";
import { API_ORIGIN, clearTokens, readTokens, refresh, requireClientHeader, setTokens } from "@/lib/server/session";

/** Authenticated proxy to the Kokila API under /v1. Refreshes the access token once on 401. */
const ALLOWED = /^[A-Za-z0-9._~\-/]+$/;

async function forward(req: Request, path: string[], at: string | undefined): Promise<Response> {
  const url = new URL(req.url);
  const headers: Record<string, string> = { "X-Request-Id": crypto.randomUUID() };
  if (at) headers.Authorization = `Bearer ${at}`;
  const ct = req.headers.get("content-type");
  if (ct) headers["Content-Type"] = ct;
  const idem = req.headers.get("idempotency-key");
  if (idem) headers["Idempotency-Key"] = idem;
  const body = req.method === "GET" || req.method === "HEAD" ? undefined : await req.clone().arrayBuffer();
  return fetch(`${API_ORIGIN}/v1/${path.join("/")}${url.search}`, {
    method: req.method, headers, body, cache: "no-store", redirect: "manual",
  });
}

async function handle(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const denied = requireClientHeader(req);
  if (denied) return denied;
  const { path } = await ctx.params;
  if (!path.every((p) => ALLOWED.test(p) && p !== ".." && p !== ".")) {
    return NextResponse.json({ error: { code: "not_found", message: "not found", trace_id: null, retryable: false } },
      { status: 404 });
  }
  const { at, rt } = await readTokens();
  let upstream = await forward(req, path, at);
  let rotated = null;
  if (upstream.status === 401 && rt) {
    rotated = await refresh(rt);
    if (rotated) upstream = await forward(req, path, rotated.access_token);
  }
  const res = new NextResponse(upstream.status === 204 ? null : await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json",
               "X-Trace-Id": upstream.headers.get("x-trace-id") ?? "" },
  });
  if (rotated) setTokens(res, rotated);
  else if (upstream.status === 401) clearTokens(res);
  return res;
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
