import { NextResponse, type NextRequest } from "next/server";

/**
 * The portal's server side (BFF) talks to the hospital service. The browser
 * only ever talks to `/api/*` on this origin; the backend's session token
 * lives in an httpOnly cookie that client code cannot read.
 */

export const SESSION_COOKIE = "hp_session";

const DEFAULT_API_URL = "http://127.0.0.1:8020";

export function backendUrl(path: string): string {
  const base = (process.env.HOSPITAL_API_URL || DEFAULT_API_URL).replace(/\/+$/, "");
  return `${base}/${path.replace(/^\/+/, "")}`;
}

/** Secure cookies in production; SESSION_COOKIE_SECURE=true|false overrides. */
function secureCookies(): boolean {
  const override = process.env.SESSION_COOKIE_SECURE;
  if (override === "true") return true;
  if (override === "false") return false;
  return process.env.NODE_ENV === "production";
}

export function setSessionCookie(response: NextResponse, token: string, maxAgeSeconds: number) {
  response.cookies.set({
    name: SESSION_COOKIE,
    value: token,
    httpOnly: true,
    secure: secureCookies(),
    sameSite: "lax",
    path: "/",
    maxAge: Math.max(60, Math.floor(maxAgeSeconds)),
  });
}

export function clearSessionCookie(response: NextResponse) {
  response.cookies.set({
    name: SESSION_COOKIE,
    value: "",
    httpOnly: true,
    secure: secureCookies(),
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}

export function errorResponse(status: number, error: string, errorCode = `HTTP_${status}`) {
  return NextResponse.json({ error, error_code: errorCode }, { status });
}

/**
 * Mutations must come from this portal: a JSON body (a cross-site form
 * cannot send one without a CORS preflight) and, when the browser says
 * where the request came from, the same origin. SameSite=Lax on the
 * session cookie is the other half of the defence.
 */
export function rejectCrossSite(request: NextRequest): NextResponse | null {
  if (request.method === "GET" || request.method === "HEAD") return null;
  const origin = request.headers.get("origin");
  if (origin) {
    const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
    let originHost: string | null = null;
    try {
      originHost = new URL(origin).host;
    } catch {
      originHost = null;
    }
    if (!host || originHost !== host) {
      return errorResponse(403, "Cross-site request refused.", "CSRF");
    }
  }
  const type = request.headers.get("content-type") ?? "";
  const hasBody = request.headers.get("content-length") !== "0" && request.method !== "DELETE";
  if (hasBody && !type.toLowerCase().startsWith("application/json")) {
    return errorResponse(415, "Send JSON.", "UNSUPPORTED_MEDIA_TYPE");
  }
  return null;
}

/** Headers passed on to the backend: the client's address chain and user agent. */
export function forwardedHeaders(request: NextRequest, token?: string): Headers {
  const headers = new Headers({ Accept: "application/json" });
  const userAgent = request.headers.get("user-agent");
  if (userAgent) headers.set("User-Agent", userAgent);
  // The backend only trusts this through HOSPITAL_TRUSTED_PROXY_HOPS.
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) headers.set("X-Forwarded-For", forwardedFor);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

export type BackendResult = { status: number; body: unknown };

export async function callBackend(
  path: string,
  init: { method: string; headers: Headers; body?: string }
): Promise<BackendResult> {
  let response: Response;
  try {
    response = await fetch(backendUrl(path), {
      method: init.method,
      headers: init.headers,
      body: init.body,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return {
      status: 502,
      body: { error: "The hospital service is not reachable. Try again shortly.", error_code: "UPSTREAM_UNAVAILABLE" },
    };
  }
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { error: "Unexpected response from the hospital service.", error_code: "UPSTREAM_INVALID" };
    }
  }
  return { status: response.status, body };
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
