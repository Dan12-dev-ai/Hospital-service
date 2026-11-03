import { callBackend, forwardedHeaders, isRecord } from "@/lib/server/backend";
import type { NextRequest } from "next/server";

/**
 * The playground's server side: it calls the integration API with the
 * hospital's own playground connection (a Test connection the hospital
 * service manages: backend app/api/playground.py), never from the browser.
 *
 * Its secret never leaves this server: new credentials are asked for only
 * when no access token is cached for the hospital, exchanged at once for an
 * access token (kept here, in memory, until shortly before it expires), and
 * dropped. Neither the secret nor the token is ever sent to the browser.
 */

const DEFAULT_INTEGRATIONS_URL = "https://api.endod-health.com/hospital/v1";

export function integrationsUrl(path = ""): string {
  const base = (process.env.INTEGRATIONS_API_URL || DEFAULT_INTEGRATIONS_URL).replace(/\/+$/, "");
  return `${base}${path}`;
}

// --- who is asking ---------------------------------------------------------------------------------

export type PlaygroundUser = { staffId: string; hospitalId: string };

/**
 * The signed-in staff member, if they may use the playground: a full
 * session (not half-way through signing in, no temporary password) of an
 * administrator or developer of a hospital Endod approved.
 */
export async function playgroundUser(request: NextRequest, sessionToken: string): Promise<PlaygroundUser | { status: number; error: string }> {
  const me = await callBackend("auth/me", { method: "GET", headers: forwardedHeaders(request, sessionToken) });
  if (me.status !== 200 || !isRecord(me.body)) {
    const error = isRecord(me.body) && typeof me.body.error === "string" ? me.body.error : "Authentication required.";
    return { status: me.status === 200 ? 502 : me.status, error };
  }
  const staff = me.body;
  const hospital = isRecord(staff.hospital) ? staff.hospital : null;
  if (staff.stage !== "full" || staff.must_change_password) return { status: 403, error: "Finish signing in first." };
  if (staff.role !== "admin" && staff.role !== "developer") return { status: 403, error: "You do not have access to this." };
  if (!hospital || hospital.locked || hospital.status !== "approved") {
    return { status: 403, error: "Only hospitals approved by Endod can use the playground." };
  }
  return { staffId: String(staff.id), hospitalId: String(hospital.id) };
}

// --- rate limit ------------------------------------------------------------------------------------

const WINDOW_MS = 60_000;
export const REQUESTS_PER_MINUTE = 30;
const MAX_TRACKED = 10_000;
const hits = new Map<string, number[]>();

/** Seconds to wait when this staff member sent too many playground requests this minute, else null. */
export function rateLimited(key: string, now = Date.now()): number | null {
  const recent = (hits.get(key) ?? []).filter((t) => t > now - WINDOW_MS);
  if (recent.length >= REQUESTS_PER_MINUTE) {
    hits.set(key, recent);
    return Math.max(1, Math.ceil((recent[0] + WINDOW_MS - now) / 1000));
  }
  recent.push(now);
  hits.delete(key);
  hits.set(key, recent);
  // Forget the oldest keys rather than grow without bound.
  while (hits.size > MAX_TRACKED) {
    const oldest = hits.keys().next().value;
    if (oldest === undefined) break;
    hits.delete(oldest);
  }
  return null;
}

// --- access tokens ---------------------------------------------------------------------------------

type CachedToken = { token: string; expiresAt: number };
const tokens = new Map<string, CachedToken>();
const pending = new Map<string, Promise<CachedToken>>();

async function newToken(request: NextRequest, sessionToken: string): Promise<CachedToken> {
  const headers = forwardedHeaders(request, sessionToken);
  headers.set("Content-Type", "application/json");
  const credentials = await callBackend("playground/credentials", { method: "POST", headers, body: "{}" });
  if (credentials.status !== 200 || !isRecord(credentials.body)) {
    const message = isRecord(credentials.body) && typeof credentials.body.error === "string"
      ? credentials.body.error
      : "The playground is not available right now.";
    throw new PlaygroundError(credentials.status === 200 ? 502 : credentials.status, message);
  }
  const { client_id: clientId, client_secret: secret } = credentials.body;
  if (typeof clientId !== "string" || typeof secret !== "string" || !clientId.startsWith("endod_test_")) {
    // Never anything but a Test connection.
    throw new PlaygroundError(502, "The playground is not available right now.");
  }
  let response: Response;
  try {
    response = await fetch(integrationsUrl("/oauth/token"), {
      method: "POST",
      headers: {
        Authorization: `Basic ${Buffer.from(`${clientId}:${secret}`).toString("base64")}`,
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/json",
      },
      body: new URLSearchParams({ grant_type: "client_credentials" }).toString(),
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    throw new PlaygroundError(502, "The integration API is not reachable. Try again shortly.");
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.status === 401) throw new RefusedSecret(502, "The playground could not get an access token. Try again shortly.");
  if (response.status !== 200 || !isRecord(body) || typeof body.access_token !== "string") {
    throw new PlaygroundError(502, "The playground could not get an access token. Try again shortly.");
  }
  const lifetime = typeof body.expires_in === "number" ? body.expires_in : 300;
  // Renewed a minute early, so a request never goes out with a token about to expire.
  return { token: body.access_token, expiresAt: Date.now() + Math.max(30, lifetime - 60) * 1000 };
}

/**
 * New credentials exchanged for a token; once more if the exchange is refused
 * (another dashboard server asked for newer credentials in between: that
 * replaces the secret, but never revokes tokens already issued).
 */
async function newTokenWithRetry(request: NextRequest, sessionToken: string): Promise<CachedToken> {
  try {
    return await newToken(request, sessionToken);
  } catch (error) {
    if (!(error instanceof RefusedSecret)) throw error;
    return newToken(request, sessionToken);
  }
}

/** The hospital's playground access token (cached; one renewal at a time per hospital). */
export async function accessToken(request: NextRequest, sessionToken: string, hospitalId: string, renew = false): Promise<string> {
  const cached = tokens.get(hospitalId);
  if (!renew && cached && cached.expiresAt > Date.now()) return cached.token;
  let inFlight = pending.get(hospitalId);
  if (!inFlight) {
    inFlight = newTokenWithRetry(request, sessionToken).finally(() => pending.delete(hospitalId));
    pending.set(hospitalId, inFlight);
  }
  const fresh = await inFlight;
  tokens.set(hospitalId, fresh);
  return fresh.token;
}

export function forgetToken(hospitalId: string) {
  tokens.delete(hospitalId);
}

export class PlaygroundError extends Error {
  constructor(
    readonly status: number,
    message: string
  ) {
    super(message);
  }
}

/** The token endpoint refused a secret that was replaced in the meantime. */
class RefusedSecret extends PlaygroundError {}

// --- which requests ---------------------------------------------------------------------------------

export const METHODS = new Set(["GET", "POST", "PUT", "DELETE"]);

/**
 * Only API operations: never the token endpoint, the keys, or anything
 * outside the API. API paths are plain ids, numbers and names: no percent
 * encoding at all, so nothing decodes into a refused path at the API.
 */
export function allowedPath(path: string): boolean {
  if (!path.startsWith("/") || path.startsWith("//") || path.length > 300) return false;
  if (!/^\/[A-Za-z0-9._~\-/]*$/.test(path) || path.includes("..")) return false;
  const lower = path.toLowerCase();
  return !(lower.startsWith("/oauth") || lower.startsWith("/.well-known") || lower === "/docs" || lower === "/openapi.json");
}

/** The answer's headers worth showing (never a cookie or anything about the edge). */
export const SHOWN_HEADERS = [
  "content-type",
  "location",
  "etag",
  "idempotent-replayed",
  "retry-after",
  "www-authenticate",
  "cache-control",
];
