import { NextResponse, type NextRequest } from "next/server";
import {
  callBackend,
  errorResponse,
  forwardedHeaders,
  isRecord,
  rejectCrossSite,
  setSessionCookie,
} from "@/lib/server/backend";

/** Sign in: the token goes into the httpOnly cookie, never to the page. */
export async function POST(request: NextRequest) {
  const refused = rejectCrossSite(request);
  if (refused) return refused;
  const body = await request.text();
  const headers = forwardedHeaders(request);
  headers.set("Content-Type", "application/json");
  const result = await callBackend("auth/login", { method: "POST", headers, body });
  if (result.status !== 200 || !isRecord(result.body)) {
    return NextResponse.json(result.body ?? { error: "Sign-in failed." }, { status: result.status });
  }
  const { access_token: token, expires_in: expiresIn, staff } = result.body;
  if (typeof token !== "string") return errorResponse(502, "Unexpected response from the hospital service.");
  const response = NextResponse.json({ staff });
  setSessionCookie(response, token, typeof expiresIn === "number" ? expiresIn : 43200);
  return response;
}
