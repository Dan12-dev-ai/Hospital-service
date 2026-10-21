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
 * File uploads from the portal's pages: one file per request, sent as
 * multipart/form-data (field "file"), passed to the backend as the request
 * body. Only these paths, each with its size limit; the backend checks the
 * file's type by its content.
 */
const MB = 1024 * 1024;
const ROUTES: { pattern: RegExp; maxBytes: number }[] = [
  // A record's file (PDF or image): at most 20 MB.
  { pattern: /^patients\/[0-9a-f]{32}\/uploads$/, maxBytes: 20 * MB },
  // An import (FHIR JSON or CSV): at most 10 MB.
  { pattern: /^imports\/preview$/, maxBytes: 10 * MB },
];
/** Room for the multipart boundaries and headers around the file. */
const ENVELOPE = 64 * 1024;

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
  const declared = Number(request.headers.get("content-length") ?? "");
  if (!Number.isFinite(declared) || declared <= 0) {
    return errorResponse(411, "The upload's length is missing.", "LENGTH_REQUIRED");
  }
  const tooBig = `The file is too large (at most ${route.maxBytes / MB} MB).`;
  if (declared > route.maxBytes + ENVELOPE) return errorResponse(413, tooBig, "TOO_LARGE");

  let file: FormDataEntryValue | null;
  try {
    const form = await request.formData();
    if (form.getAll("file").length !== 1) return errorResponse(400, "Send exactly one file.");
    file = form.get("file");
  } catch {
    return errorResponse(400, "The upload could not be read.");
  }
  if (!(file instanceof File)) return errorResponse(400, "Send exactly one file.");
  if (file.size === 0) return errorResponse(400, "The file is empty.");
  if (file.size > route.maxBytes) return errorResponse(413, tooBig, "TOO_LARGE");

  const headers = forwardedHeaders(request, token);
  // The type the browser guessed is only a hint; the backend reads the content.
  headers.set("Content-Type", joined === "imports/preview" ? file.type || "application/octet-stream" : "application/octet-stream");
  headers.set("X-Filename", encodeURIComponent(file.name.slice(0, 200)));
  const result = await callBackend(joined, {
    method: "POST",
    headers,
    body: new Uint8Array(await file.arrayBuffer()),
  });
  const response = NextResponse.json(result.body, { status: result.status });
  response.headers.set("Cache-Control", "no-store");
  if (result.status === 401) clearSessionCookie(response);
  return response;
}
