import { NextResponse, type NextRequest } from "next/server";
import {
  SESSION_COOKIE,
  callBackend,
  clearSessionCookie,
  errorResponse,
  forwardedHeaders,
  rejectCrossSiteUpload,
} from "@/lib/server/backend";

/**
 * File uploads from the portal's pages: one file per request, the file itself
 * as the request body (its name in X-Filename), streamed to the backend as it
 * arrives: nothing is held in memory. Only these paths, each with its size
 * limit, enforced on the declared length first and again on the bytes that
 * actually pass through. The backend checks the file's type by its content.
 */
const MB = 1024 * 1024;
const ROUTES: { pattern: RegExp; maxBytes: number; keepType: boolean }[] = [
  // A record's file (PDF or image): at most 20 MB.
  { pattern: /^patients\/[0-9a-f]{32}\/uploads$/, maxBytes: 20 * MB, keepType: false },
  // An import (FHIR JSON or CSV): at most 10 MB. Its type tells JSON from CSV.
  { pattern: /^imports\/preview$/, maxBytes: 10 * MB, keepType: true },
];

class TooLarge extends Error {}

/** The file name as the page sent it (URI-encoded), shortened; "" when unusable. */
function fileName(header: string | null): string {
  if (!header || header.length > 2000) return "";
  try {
    return decodeURIComponent(header).slice(0, 200);
  } catch {
    return "";
  }
}

export async function POST(request: NextRequest, ctx: RouteContext<"/api/upload/[...path]">) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  const route = ROUTES.find((r) => r.pattern.test(joined));
  if (!route) return errorResponse(404, "Not found.");
  const refused = rejectCrossSiteUpload(request);
  if (refused) return refused;
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return errorResponse(401, "Authentication required.");

  // Checked before the body is read: no length, or too long, is refused.
  const length = request.headers.get("content-length");
  const declared = Number(length ?? "");
  if (length === null || !Number.isFinite(declared) || declared < 0) {
    return errorResponse(411, "The upload's length is missing.", "LENGTH_REQUIRED");
  }
  if (declared === 0 || !request.body) return errorResponse(400, "The file is empty.");
  const tooBig = `The file is too large (at most ${route.maxBytes / MB} MB).`;
  if (declared > route.maxBytes) return errorResponse(413, tooBig, "TOO_LARGE");

  // The bytes are counted as they stream through: a body longer than its
  // declared length, or than the limit, is cut off and refused.
  let seen = 0;
  let exceeded = false;
  const counted = request.body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        seen += chunk.byteLength;
        if (seen > route.maxBytes || seen > declared) {
          exceeded = true;
          controller.error(new TooLarge(tooBig));
          return;
        }
        controller.enqueue(chunk);
      },
    })
  );

  const headers = forwardedHeaders(request, token);
  // The type the browser guessed is only a hint; the backend reads the content.
  const declaredType = (request.headers.get("content-type") ?? "").slice(0, 100);
  headers.set("Content-Type", route.keepType && declaredType ? declaredType : "application/octet-stream");
  headers.set("X-Filename", encodeURIComponent(fileName(request.headers.get("x-filename"))));
  const result = await callBackend(joined, { method: "POST", headers, body: counted });
  if (exceeded) return errorResponse(413, tooBig, "TOO_LARGE");
  const response = NextResponse.json(result.body, { status: result.status });
  response.headers.set("Cache-Control", "no-store");
  if (result.status === 401) clearSessionCookie(response);
  return response;
}
