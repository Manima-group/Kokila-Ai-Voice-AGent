import { NextResponse } from "next/server";
import { API_ORIGIN, clearTokens, readTokens, requireClientHeader } from "@/lib/server/session";

export async function POST(req: Request) {
  const denied = requireClientHeader(req);
  if (denied) return denied;
  const { at } = await readTokens();
  if (at) {
    await fetch(`${API_ORIGIN}/v1/auth/logout`, {
      method: "POST", headers: { Authorization: `Bearer ${at}` }, cache: "no-store",
    }).catch(() => undefined);
  }
  const res = new NextResponse(null, { status: 204 });
  clearTokens(res);
  return res;
}
