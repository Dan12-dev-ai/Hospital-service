import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, errorResponse } from "@/lib/server/backend";
import { integrationsUrl, playgroundUser } from "@/lib/server/playground";

/**
 * The integration API's OpenAPI document, for the playground (its endpoints
 * and request examples). Public at the API itself; here only for signed-in
 * administrators and developers, and cached for a few minutes.
 */
let cached: { at: number; body: unknown } | null = null;
const TTL_MS = 5 * 60_000;

export async function GET(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return errorResponse(401, "Authentication required.");
  const user = await playgroundUser(request, token);
  if ("error" in user) return errorResponse(user.status, user.error);
  if (!cached || Date.now() - cached.at > TTL_MS) {
    try {
      const response = await fetch(integrationsUrl("/openapi.json"), { cache: "no-store", headers: { Accept: "application/json" } });
      if (!response.ok) return errorResponse(502, "The API reference is not available right now.");
      cached = { at: Date.now(), body: await response.json() };
    } catch {
      return errorResponse(502, "The integration API is not reachable. Try again shortly.");
    }
  }
  const answer = NextResponse.json(cached.body);
  answer.headers.set("Cache-Control", "no-store");
  return answer;
}
