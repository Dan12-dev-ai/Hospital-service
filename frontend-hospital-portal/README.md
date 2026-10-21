# Endod hospital portal

The staff portal of the hospital service (Next.js App Router). It talks to
`../backend-hospital` through its own server: the browser only calls `/api/*`
on this origin, and the route handlers in `app/api/` pass the calls on to the
hospital service with the staff member's session.

## Run locally

```sh
npm ci
HOSPITAL_API_URL=http://127.0.0.1:8020 npm run dev   # the backend's address (default shown)
```

| Variable | Meaning |
| --- | --- |
| `HOSPITAL_API_URL` | Where the hospital service listens (server side only). Default `http://127.0.0.1:8020`. |
| `SESSION_COOKIE_SECURE` | `true`/`false` to force the session cookie's `Secure` flag; by default it is set in production. |

## Sessions

- Sign-in (`/api/auth/login`) and hospital sign-up (`/api/onboarding`) put the
  backend's session token into the `hp_session` cookie: httpOnly, SameSite=Lax,
  Secure in production. Page code never sees the token.
- `app/api/[...path]/route.ts` forwards the staff API (`auth/me`,
  `auth/password`, `hospital`, `departments`, `staff`, `patients`, `doctors`,
  `bookings`, and the patient history: Endod links, records, visits, queues,
  shared records, import confirmation) with the token as a bearer header; anything else is a 404, so
  Endod's `/platform/*` endpoints are never reachable through the portal.
  Changes must be JSON and, when the browser sends an `Origin`, from this origin.
- Files have their own routes, as that one is JSON only.
  `app/api/upload/[...path]` takes one multipart file (field `file`) for
  `patients/<id>/uploads` (20 MB) or `imports/preview` (10 MB), refuses a
  missing or excessive `Content-Length` before reading, and requires an
  `Origin` of this portal plus the `X-Portal-Upload: 1` header (which a
  cross-site form cannot send). `app/api/download/[...path]` streams
  `records/<id>/files/<id>` and `shared/<id>/files/<id>` only, PDF, JPEG, PNG
  or WebP only, with `nosniff`, `no-store` and a restrictive CSP;
  `?download=1` saves instead of showing.
- `proxy.ts` sends signed-out visitors to `/login`. A session the backend no
  longer accepts gets a 401, the cookie is dropped and the page goes to `/login`.
- Staff with a temporary password are sent to `/account/password` until they
  change it.
- The handlers forward the caller's `X-Forwarded-For` unchanged. Set the
  backend's `HOSPITAL_TRUSTED_PROXY_HOPS` only when a proxy in front of the
  portal appends the real client address (the sign-up rate limit uses it).

## What is real

Real: sign-in, sign-out, password change, hospital sign-up (pending until
Endod approves), hospital settings, Endod bookings and video visits, the
doctors and patients directories, each patient's page (linking to Endod by
health card QR or Endod ID and phone, clinical records with files, visits and
follow-ups, records the patient shared), the doctors' queues, shared records
and record imports (FHIR R4 or the CSV template in `public/import-template.csv`,
documented in `docs/imports.md`), and the dashboard's patient, booking and
doctor counts. Billing, pharmacy, reports and the rest of the dashboard are
sample data and carry a "Sample data" badge.

## Browser tests

The Playwright tests run against the real hospital service (uvicorn with a
throwaway SQLite database, started by `playwright.config.ts`) and the built
portal (`next start`), in the system Chrome:

```sh
npx next build
npx playwright test             # or E2E_NEXT_DEV=1 npx playwright test (no build)
```

The backend's Python is `../.venv` by default; set `E2E_PYTHON` to use another
one. Test data is written by `e2e/seed.py`, which stores bookings the way the
event worker does (`app.bookings.on_requested`), and Endod's replies the same
way: link confirmations and refusals, and records a patient shares.
