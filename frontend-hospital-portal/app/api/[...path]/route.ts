import { NextResponse, type NextRequest } from "next/server";
import {
  SESSION_COOKIE,
  callBackend,
  clearSessionCookie,
  errorResponse,
  forwardedHeaders,
  isRecord,
  rejectCrossSite,
  setSessionCookie,
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
  // Two-step verification: the code after the password, setting up the
  // authenticator, and a fresh code for sensitive actions.
  /^auth\/(totp|reauth|enroll\/(start|confirm))$/,
  /^hospital$/,
  /^departments(\/[A-Za-z0-9_-]+)?$/,
  /^staff(\/[A-Za-z0-9_-]+(\/(reset-password|reset-2fa))?)?$/,
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
  // "Connect your system": the hospital's own systems (admins of approved hospitals).
  /^connections(\/[a-f0-9]{32}(\/(disconnect|rotate-secret|ip-restriction|public-key|webhook(\/(rotate-secret|test))?|requests|deliveries))?)?$/,
  // The onboarding application (its documents go through app/api/upload and app/api/download).
  /^onboarding\/(status|application|contact|facility|location|documents|demo-slots|demo|submit)$/,
];

/** The sign-in steps whose answer carries a new session's token. */
const SIGN_IN_STEPS = new Set(["auth/totp", "auth/enroll/confirm"]);

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
  // A sign-in step that opens a new session (the code, or the authenticator's
  // set-up): its token goes into the httpOnly cookie, never to the page.
  let renewed: { token: string; maxAge: number } | null = null;
  let payload = result.body;
  if (SIGN_IN_STEPS.has(joined) && result.status === 200 && isRecord(payload) && typeof payload.access_token === "string") {
    const { access_token: token, expires_in: expiresIn, token_type: _type, ...rest } = payload;
    void _type;
    renewed = { token: token as string, maxAge: typeof expiresIn === "number" ? expiresIn : 43200 };
    payload = rest;
  }
  const response =
    result.status === 204
      ? new NextResponse(null, { status: 204 })
      : NextResponse.json(payload, { status: result.status });
  if (renewed) setSessionCookie(response, renewed.token, renewed.maxAge);
  response.headers.set("Cache-Control", "no-store");
  // The session ended (expired, revoked, signed out elsewhere): forget it.
  if (result.status === 401) clearSessionCookie(response);
  return response;
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
