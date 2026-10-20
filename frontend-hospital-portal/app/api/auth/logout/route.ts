import { NextResponse, type NextRequest } from "next/server";
import {
  SESSION_COOKIE,
  callBackend,
  clearSessionCookie,
  forwardedHeaders,
  rejectCrossSite,
} from "@/lib/server/backend";

/** Sign out: end the session on the backend and drop the cookie either way. */
export async function POST(request: NextRequest) {
  const refused = rejectCrossSite(request);
  if (refused) return refused;
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (token) {
    await callBackend("auth/logout", { method: "POST", headers: forwardedHeaders(request, token) });
  }
  const response = NextResponse.json({ ok: true });
  clearSessionCookie(response);
  return response;
}
