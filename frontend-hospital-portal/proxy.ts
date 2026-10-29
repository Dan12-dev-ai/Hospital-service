import { NextResponse, type NextRequest } from "next/server";

// Kept in sync with lib/server/backend.ts (the proxy bundle stays small).
const SESSION_COOKIE = "hp_session";
// /onboarding starts signed out (its first step creates the account).
const PUBLIC_PAGES = new Set(["/login", "/signup", "/onboarding"]);

/**
 * An optimistic check only: signed-out visitors are sent to /login before a
 * portal page renders. The backend still checks the session on every call,
 * and the BFF drops a cookie the backend no longer accepts.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const signedIn = Boolean(request.cookies.get(SESSION_COOKIE)?.value);

  if (PUBLIC_PAGES.has(pathname)) {
    return NextResponse.next();
  }
  if (!signedIn) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    if (pathname !== "/") url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Pages only: not the BFF (it answers 401 itself), Next's assets or public
  // files. The PWA's files (service worker, manifest, icons) must load signed
  // out too, so they are named one by one rather than by extension.
  matcher: [
    "/((?!api/|_next/static|_next/image|favicon\\.ico$|sw\\.js$|service-worker\\.js$|manifest\\.json$|apple-touch-icon\\.png$|icons/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
