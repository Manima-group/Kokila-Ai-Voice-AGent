import { NextResponse } from "next/server";
import { API_ORIGIN, requireClientHeader } from "@/lib/server/session";

export async function POST(req: Request) {
  const denied = requireClientHeader(req);
  if (denied) return denied;
  const r = await fetch(`${API_ORIGIN}/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
