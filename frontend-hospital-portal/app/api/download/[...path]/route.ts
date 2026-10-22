import { NextResponse, type NextRequest } from "next/server";
import {
  SESSION_COOKIE,
  backendUrl,
  clearSessionCookie,
  errorResponse,
  forwardedHeaders,
} from "@/lib/server/backend";

/**
 * Record files, streamed from the backend to the browser: a hospital record's
 * file, or a file of records a patient shared (which the backend fetches from
 * Endod). Only these paths and only these types; never cached, never
 * sniffed, and sandboxed so a file cannot run anything on the portal's origin.
 * `?download=1` saves the file instead of showing it.
 */
const ALLOWED: RegExp[] = [
  /^records\/[0-9a-f]{32}\/files\/[0-9a-f]{32}$/,
  /^shared\/[0-9a-f]{32}\/files\/[0-9a-f]{32}$/,
  // The hospital's own onboarding documents (the backend takes the hospital from the session).
  /^onboarding\/documents\/(moh_license|trade_license|tin_certificate|owner_id)$/,
];
const TYPES = new Set(["application/pdf", "image/jpeg", "image/png", "image/webp"]);

export async function GET(request: NextRequest, ctx: RouteContext<"/api/download/[...path]">) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (!ALLOWED.some((pattern) => pattern.test(joined))) return errorResponse(404, "Not found.");
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return errorResponse(401, "Authentication required.");

  const headers = forwardedHeaders(request, token);
  headers.set("Accept", "*/*");
  let upstream: Response;
  try {
    upstream = await fetch(backendUrl(joined), { headers, cache: "no-store", redirect: "manual" });
  } catch {
    return errorResponse(502, "The hospital service is not reachable. Try again shortly.", "UPSTREAM_UNAVAILABLE");
  }
  if (!upstream.ok) {
    let message = "The file could not be opened.";
    try {
      const body = (await upstream.json()) as { error?: unknown };
      if (typeof body.error === "string") message = body.error;
    } catch {
      // Not JSON: keep the generic message.
    }
    const response = errorResponse(upstream.status >= 400 && upstream.status < 600 ? upstream.status : 502, message);
    if (upstream.status === 401) clearSessionCookie(response);
    return response;
  }
  const type = (upstream.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (!TYPES.has(type) || !upstream.body) {
    await upstream.body?.cancel();
    return errorResponse(502, "Unexpected file from the hospital service.", "UPSTREAM_INVALID");
  }
  const response = new NextResponse(upstream.body, { status: 200 });
  response.headers.set("Content-Type", type);
  const length = upstream.headers.get("content-length");
  if (length && /^\d+$/.test(length)) response.headers.set("Content-Length", length);
  const disposition = upstream.headers.get("content-disposition") ?? "inline";
  const wantsDownload = request.nextUrl.searchParams.get("download") === "1";
  response.headers.set(
    "Content-Disposition",
    wantsDownload ? disposition.replace(/^\s*inline/i, "attachment") : disposition.replace(/^\s*attachment/i, "inline")
  );
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Cross-Origin-Resource-Policy", "same-origin");
  // Images: nothing but the image. PDFs: browsers' PDF viewers are plugins
  // that `default-src 'none'` (object-src) would block, so only the framing
  // rule; nosniff and the type allowlist keep anything else from rendering.
  response.headers.set(
    "Content-Security-Policy",
    type === "application/pdf"
      ? "frame-ancestors 'self'"
      : "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'"
  );
  return response;
}
