import { NextResponse, type NextRequest } from "next/server";
import {
  callBackend,
  errorResponse,
  forwardedHeaders,
  isRecord,
  rejectCrossSite,
  setSessionCookie,
} from "@/lib/server/backend";

/** Hospital self sign-up. The new admin is signed in straight away. */
export async function POST(request: NextRequest) {
  const refused = rejectCrossSite(request);
  if (refused) return refused;
  const body = await request.text();
  const headers = forwardedHeaders(request);
  headers.set("Content-Type", "application/json");
  const result = await callBackend("onboarding", { method: "POST", headers, body });
  if (result.status !== 201 || !isRecord(result.body)) {
    return NextResponse.json(result.body ?? { error: "Sign-up failed." }, { status: result.status });
  }
  const { access_token: token, expires_in: expiresIn, staff, hospital } = result.body;
  if (typeof token !== "string") return errorResponse(502, "Unexpected response from the hospital service.");
  const response = NextResponse.json({ staff, hospital }, { status: 201 });
  setSessionCookie(response, token, typeof expiresIn === "number" ? expiresIn : 43200);
  return response;
}
