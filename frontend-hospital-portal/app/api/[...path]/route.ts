import { NextResponse, type NextRequest } from "next/server";
import {
  SESSION_COOKIE,
  callBackend,
  clearSessionCookie,
  errorResponse,
  forwardedHeaders,
  rejectCrossSite,
} from "@/lib/server/backend";

/**
 * Everything else the portal reads or changes, passed to the backend with
 * the session from the cookie. Only the staff API is reachable: sign-in and
 * sign-up have their own handlers (they set the cookie), and Endod's
 * platform endpoints are never exposed through the portal.
 */
const ALLOWED: RegExp[] = [
  /^auth\/me$/,
  /^auth\/password$/,
  /^hospital$/,
  /^departments(\/[A-Za-z0-9_-]+)?$/,
  /^staff(\/[A-Za-z0-9_-]+(\/reset-password)?)?$/,
  /^patients(\/stats|\/[A-Za-z0-9_-]+(\/alerts(\/[A-Za-z0-9_-]+)?)?)?$/,
  /^doctors(\/[A-Za-z0-9_-]+(\/(profile|duty))?)?$/,
  /^bookings(\/[A-Za-z0-9_-]+(\/(approve|reject|cancel|complete|video))?)?$/,
  // Patient history. File uploads and downloads have their own routes
  // (app/api/upload, app/api/download): this one only passes JSON.
  /^patients\/[A-Za-z0-9_-]+\/(link|records|visits)$/,
  /^records\/[A-Za-z0-9_-]+(\/retract)?$/,
  /^visits\/[A-Za-z0-9_-]+$/,
  /^queue(\/check-in|\/[A-Za-z0-9_-]+\/call-next|\/entries\/[A-Za-z0-9_-]+\/(done|skip|cancel))?$/,
  /^shared$/,
  /^imports\/[A-Za-z0-9_-]+\/confirm$/,
  // The onboarding application (its documents go through app/api/upload and app/api/download).
  /^onboarding\/(status|application|contact|facility|location|documents|demo-slots|demo|submit)$/,
];

async function handle(request: NextRequest, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (!ALLOWED.some((pattern) => pattern.test(joined))) {
    return errorResponse(404, "Not found.");
  }
  const refused = rejectCrossSite(request);
  if (refused) return refused;
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return errorResponse(401, "Authentication required.");

  const headers = forwardedHeaders(request, token);
  let body: string | undefined;
  if (request.method !== "GET" && request.method !== "DELETE") {
    body = (await request.text()) || "{}";
    headers.set("Content-Type", "application/json");
  }
  const result = await callBackend(`${joined}${request.nextUrl.search}`, {
    method: request.method,
    headers,
    body,
  });
  const response =
    result.status === 204
      ? new NextResponse(null, { status: 204 })
      : NextResponse.json(result.body, { status: result.status });
  response.headers.set("Cache-Control", "no-store");
  // The session ended (expired, revoked, signed out elsewhere): forget it.
  if (result.status === 401) clearSessionCookie(response);
  return response;
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
