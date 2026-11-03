# Endod developer dashboard

The dashboard of the hospital service (Next.js App Router), at
`hospital.endod-health.com`. Every client hospital keeps its own hospital
system; Endod is the integration layer between it and the Endod patient app.
Hospitals apply and are approved here, and their administrators and
developers connect their system: API keys, webhooks, logs, a playground and
the docs.

It talks to `../backend-hospital` through its own server: the browser only
calls `/api/*` on this origin, and the route handlers in `app/api/` pass the
calls on to the hospital service with the staff member's session.

## Run locally

```sh
npm ci
HOSPITAL_API_URL=http://127.0.0.1:8020 npm run dev   # the backend's address (default shown)
```

| Variable | Meaning |
| --- | --- |
| `HOSPITAL_API_URL` | Where the hospital service listens (server side only). Default `http://127.0.0.1:8020`. |
| `INTEGRATIONS_API_URL` | Where the playground calls the integration API (server side only). Default `https://api.endod-health.com/hospital/v1`. |
| `NEXT_PUBLIC_INTEGRATIONS_PUBLIC_URL` | The integration API's public URL for the Swagger and `openapi.json` links (build time). Default `https://api.endod-health.com/hospital/v1`. |
| `SESSION_COOKIE_SECURE` | `true`/`false` to force the session cookie's `Secure` flag; by default it is set in production. |

## Who sees what

- Signed out: `/login`, `/signup`, `/onboarding` (its first step creates the
  account). `proxy.ts` sends every other page to `/login`.
- A hospital Endod has not approved: only its application (`/onboarding`)
  and, once submitted, `/under-review`. A suspended one sees why.
- An approved hospital's **administrators and developers**: the dashboard.
  The old portal's clinical roles (doctor, nurse, reception, pharmacist,
  billing, records) are refused at sign-in by the backend, with a message.
  Administrators also change Settings and manage the Team; developers read
  Settings.
- Staff with a temporary password are sent to `/account/password`, then set
  up two-step verification (`/enroll`).

## Sections

| Page | What |
| --- | --- |
| `/` Overview | Approval and listing checklist, Test and Live keys, quick links. |
| `/getting-started` | Five steps from a key to the first record. |
| `/keys` API keys | Create Test or Live keys with scopes, rotate the secret, public-key auth, IP allow-list, revoke (each change asks for a fresh authenticator code). `/keys/<id>/setup-guide` prints a key's details (never the secret). |
| `/webhooks` | A key's webhook URL and signing secret, a test event, recent deliveries. |
| `/logs` | A key's recent API requests. |
| `/playground` | Try any endpoint in Test mode (below). |
| `/docs` | The integration guide (`backend-hospital/app/integrations/guide.md`, served by `GET /developer/guide`) as pages: one per section, one per record type, code blocks with a copy button. |
| `/settings` | The hospital's listing (contact, hours, services, location, the in-person consultation price) and the price list its system synced, read-only. No video settings while video visits are off. |
| `/team` | Invite or remove administrators and developers (temporary password, then two-step verification). |

The sidebar links to the API reference: Swagger (`/docs` of the integration
API) and `openapi.json`.

## The playground

The browser never holds a client secret or an access token. `POST
/api/playground/send` (`app/api/playground/send/route.ts`) checks the
signed-in staff member (an administrator or developer of an approved
hospital), limits them to 30 requests a minute, and calls the integration API
with the hospital's **playground connection**: a Test connection the
hospital service creates and manages (`POST /playground/credentials`, never
listed or changeable by staff, every scope but webhooks). Its secret is new
on each such call, exchanged at once for an access token kept in the
server's memory until shortly before it expires. Being a Test connection,
every request is checked as in Live and nothing is stored. The endpoints and
example bodies come from the API's OpenAPI document (`/api/playground/spec`);
the token endpoint is never reachable.

## Sessions

- Sign-in (`/api/auth/login`) and hospital sign-up (`/api/onboarding`) put the
  backend's session token into the `hp_session` cookie: httpOnly, SameSite=Lax,
  Secure in production. Page code never sees the token.
- `app/api/[...path]/route.ts` forwards only what the dashboard uses
  (`auth/*`, `hospital`, `staff`, `connections`, `developer/guide`, `prices`,
  `onboarding/*`) with the token as a bearer header; anything else is a 404,
  so Endod's `/platform/*` endpoints and the old clinical staff API are never
  reachable. Changes must be JSON and, when the browser sends an `Origin`,
  from this origin.
- Onboarding documents have their own upload and download routes
  (`app/api/upload`, `app/api/download`).
- The handlers forward the caller's `X-Forwarded-For` unchanged. Set the
  backend's `HOSPITAL_TRUSTED_PROXY_HOPS` only when a proxy in front of the
  dashboard appends the real client address (the sign-up rate limit uses it).
- The old portal installed a service worker; `public/sw.js` now replaces it
  with one that clears its caches and removes itself.

## Browser tests

The Playwright tests run against the real hospital service and integration
API (uvicorn with a throwaway SQLite database, started by
`playwright.config.ts`) and the built dashboard (`next start`), in the system
Chrome:

```sh
npx next build
npx playwright test             # or E2E_NEXT_DEV=1 npx playwright test (no build)
```

The backend's Python is `../.venv` by default; set `E2E_PYTHON` to use another
one. Test data is written by `e2e/seed.py`.
