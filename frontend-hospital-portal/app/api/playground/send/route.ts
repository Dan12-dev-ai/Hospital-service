import { createHash } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, errorResponse, isRecord, rejectCrossSite } from "@/lib/server/backend";
import {
  METHODS,
  PlaygroundError,
  SHOWN_HEADERS,
  accessToken,
  allowedPath,
  forgetToken,
  integrationsUrl,
  playgroundUser,
  rateLimited,
} from "@/lib/server/playground";

const MAX_BODY = 256 * 1024;

/**
 * Sends one playground request to the integration API, in Test mode, with
 * the hospital's playground connection (lib/server/playground.ts). The page
 * sends {method, path, query?, body?}; the answer is {status, duration_ms,
 * headers, body}. The access token never reaches the browser.
 */
export async function POST(request: NextRequest) {
  const refused = rejectCrossSite(request);
  if (refused) return refused;
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  if (!session) return errorResponse(401, "Authentication required.");

  const raw = await request.text();
  if (raw.length > MAX_BODY) return errorResponse(413, "The request is too large for the playground (256 KB at most).");
  let input: unknown;
  try {
    input = JSON.parse(raw || "{}");
  } catch {
    return errorResponse(400, "Send JSON.");
  }
  if (!isRecord(input)) return errorResponse(400, "Send JSON.");
  const method = typeof input.method === "string" ? input.method.toUpperCase() : "";
  const path = typeof input.path === "string" ? input.path.trim() : "";
  const query = typeof input.query === "string" ? input.query.trim().replace(/^\?/, "") : "";
  const body = typeof input.body === "string" ? input.body : "";
  if (!METHODS.has(method)) return errorResponse(400, "Choose GET, POST, PUT or DELETE.");
  if (!allowedPath(path)) return errorResponse(400, "Choose an endpoint of the API.");
  if (query.length > 500 || /[\s#]/.test(query)) return errorResponse(400, "The query string is not valid.");

  const user = await playgroundUser(request, session);
  if ("error" in user) return errorResponse(user.status, user.error);
  const wait = rateLimited(createHash("sha256").update(session).digest("hex"));
  if (wait !== null) {
    const limited = errorResponse(429, "Too many playground requests; try again shortly.");
    limited.headers.set("Retry-After", String(wait));
    return limited;
  }

  const url = integrationsUrl(path) + (query ? `?${query}` : "");
  const contentType = path.startsWith("/fhir") ? "application/fhir+json" : "application/json";
  const send = async (token: string) => {
    const headers: Record<string, string> = { Authorization: `Bearer ${token}`, Accept: "application/json, application/fhir+json" };
    if (body && method !== "GET" && method !== "DELETE") headers["Content-Type"] = contentType;
    const started = Date.now();
    const response = await fetch(url, {
      method,
      headers,
      body: body && method !== "GET" && method !== "DELETE" ? body : undefined,
      cache: "no-store",
      redirect: "manual",
    });
    return { response, duration: Date.now() - started };
  };

  try {
    let result = await send(await accessToken(request, session, user.hospitalId));
    if (result.response.status === 401) {
      // The token expired or its credentials changed: once more with a new one.
      forgetToken(user.hospitalId);
      result = await send(await accessToken(request, session, user.hospitalId, true));
    }
    const text = await result.response.text();
    let parsed: unknown = text;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = text.slice(0, 20_000);
    }
    const headers: Record<string, string> = {};
    for (const name of SHOWN_HEADERS) {
      const value = result.response.headers.get(name);
      if (value) headers[name] = value;
    }
    const answer = NextResponse.json({
      status: result.response.status,
      duration_ms: result.duration,
      headers,
      body: parsed,
    });
    answer.headers.set("Cache-Control", "no-store");
    return answer;
  } catch (error) {
    if (error instanceof PlaygroundError) return errorResponse(error.status, error.message);
    return errorResponse(502, "The integration API is not reachable. Try again shortly.");
  }
}
