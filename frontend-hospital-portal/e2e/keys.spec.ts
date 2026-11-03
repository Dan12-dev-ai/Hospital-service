import { expect, test, type Page } from "@playwright/test";
import {
  confirmWithCode,
  platform,
  seedApplicant,
  seedHospital,
  signIn,
  signInThroughForm,
  type SeededHospital,
} from "./helpers";
import { BACKEND_URL } from "./env";

// API keys, webhooks and logs: the hospital's own systems and the integration API.

let hospital: SeededHospital;

// Each sign-in and each fresh confirmation uses a new authenticator code; the
// test clock may wait for the next 30-second step.
test.describe.configure({ timeout: 120_000 });

test.beforeAll(() => {
  hospital = seedHospital("key");
});

const API = `${BACKEND_URL}/integrations/v1`;

function basic(clientId: string, secret: string) {
  return { Authorization: `Basic ${Buffer.from(`${clientId}:${secret}`).toString("base64")}` };
}

/** Creates a key through the dialog (a fresh code from the authenticator). Returns its client ID and secret. */
async function createKey(page: Page, email: string, name: string, scopes: string[], mode: "Live" | "Test" = "Test") {
  await page.goto("/keys");
  await page.getByRole("button", { name: "Create API key" }).click();
  const dialog = page.getByRole("dialog", { name: "Create API key" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByText(mode, { exact: true }).click();
  for (const scope of scopes) await dialog.getByText(scope, { exact: true }).click();
  await dialog.getByRole("button", { name: "Create key" }).click();
  await confirmWithCode(page, email, "Create key");
  const done = page.getByTestId("connect-done");
  await expect(done).toContainText("Save the secret now");
  const clientId = (await done.getByTestId("client-id").textContent()) ?? "";
  const secret = (await done.getByTestId("client-secret").textContent()) ?? "";
  return { clientId, secret, done };
}

test("an admin creates a Test key; the secret is shown once", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  await page.goto("/");
  await page.getByRole("navigation", { name: "Dashboard" }).getByRole("link", { name: "API keys" }).click();
  await expect(page).toHaveURL(/\/keys$/);
  await expect(page.getByRole("heading", { name: "API keys" })).toBeVisible();
  await expect(page.getByTestId("swagger-link").filter({ visible: true })).toHaveAttribute("href", /\/hospital\/v1\/docs$/);

  // A wrong code is refused and nothing is created.
  await page.getByRole("button", { name: "Create API key" }).click();
  const dialog = page.getByRole("dialog", { name: "Create API key" });
  await dialog.getByLabel("Name").fill("Wrong code system");
  await dialog.getByText("records.labs.write", { exact: true }).click();
  await dialog.getByRole("button", { name: "Create key" }).click();
  const confirm = page.getByTestId("confirm-code");
  await confirm.getByLabel("Confirm it's you: enter the code from your authenticator app").fill("000000");
  await confirm.getByRole("button", { name: "Create key" }).click();
  await expect(confirm.getByTestId("form-error")).toContainText("That code is not valid");
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Close dialog" }).click();
  expect((await (await page.request.get("/api/connections")).json()).items).toHaveLength(0);

  const { clientId, secret, done } = await createKey(page, hospital.accounts.admin.email, "Main lab system", [
    "records.labs.write",
    "prices.write",
  ]);
  expect(clientId).toMatch(/^endod_test_[0-9a-f]{24}$/);
  expect(secret.length).toBeGreaterThanOrEqual(40);

  // The printable setup guide: the details, never the secret.
  const href = (await done.getByRole("link", { name: "Download setup guide" }).getAttribute("href")) ?? "";
  expect(href).toMatch(/^\/keys\/[0-9a-f]{32}\/setup-guide$/);
  const guide = await page.context().newPage();
  await guide.goto(href);
  await expect(guide.getByTestId("setup-guide")).toContainText(clientId);
  await expect(guide.getByTestId("setup-guide")).toContainText("prices.write");
  expect(await guide.content()).not.toContain(secret);
  await guide.close();

  await page.getByRole("button", { name: "I saved the secret" }).click();
  const row = page.getByTestId("connection").filter({ hasText: "Main lab system" });
  await expect(row).toContainText("records.labs.write");
  await expect(row.getByTestId("mode-badge")).toHaveText("Test");
  await expect(row.getByTestId("last-used")).toHaveText("Not used yet");
  // Shown once: never again, on the page or from the API.
  expect(await page.content()).not.toContain(secret);
  expect(await (await page.request.get("/api/connections")).text()).not.toContain(secret);
});

test("a developer manages a key: allowed addresses, a webhook with a test event, the logs", async ({ page }) => {
  const email = hospital.accounts.developer.email;
  await signIn(page, email, hospital.password);
  const { clientId, secret } = await createKey(page, email, "Pharmacy system", ["records.prescriptions.write"], "Test");
  await page.getByRole("button", { name: "I saved the secret" }).click();

  // A token from the system's side: the key shows as used, and the call is in the logs.
  const token = await page.request.post(`${API}/oauth/token`, {
    form: { grant_type: "client_credentials" },
    headers: basic(clientId, secret),
  });
  expect(token.status()).toBe(200);
  await page.reload();
  const row = page.getByTestId("connection").filter({ hasText: "Pharmacy system" });
  await expect(row.getByTestId("last-used")).toHaveText(/Used/);

  await row.getByRole("button", { name: /Pharmacy system/ }).click();
  const settings = row.getByTestId("advanced");
  await settings.getByLabel("Allowed IP addresses").fill("196.188.10.0/24\n127.0.0.1");
  // The code given to create the key is fresh for 10 minutes: no new one asked.
  await settings.getByRole("button", { name: "Save addresses" }).click();
  await expect(page.getByTestId("confirm-code")).toHaveCount(0);
  await expect(page.getByTestId("toast")).toHaveText("Allowed addresses saved");

  await page.getByRole("navigation", { name: "Dashboard" }).getByRole("link", { name: "Webhooks" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Webhooks" })).toBeVisible();
  await page.getByLabel("API key").filter({ visible: true }).selectOption({ label: "Pharmacy system (Test)" });
  await page.getByLabel("Webhook URL").filter({ visible: true }).fill("https://hooks.example.com/endod");
  await page.getByRole("button", { name: "Save webhook" }).click();
  await expect(page.getByTestId("revealed-secret")).toContainText("whsec_");
  await page.getByRole("button", { name: "I saved it" }).click();
  await page.getByRole("button", { name: "Send test event" }).click();
  await expect(page.getByTestId("delivery-log")).toContainText("endpoint.test");

  await page.getByRole("navigation", { name: "Dashboard" }).getByRole("link", { name: "Logs" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Logs" })).toBeVisible();
  // The page left behind is kept, hidden, by the router: only the visible picker counts.
  await expect(page.getByLabel("API key").filter({ visible: true })).toHaveCount(1);
  await page.getByLabel("API key").filter({ visible: true }).selectOption({ label: "Pharmacy system (Test)" });
  await expect(page.getByTestId("request-log").filter({ visible: true })).toContainText(/POST\s*\/integrations\/v1\/oauth\/token/);
});

test("revoking asks for confirmation and stops the system", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  const { clientId, secret } = await createKey(page, hospital.accounts.admin.email, "Old radiology system", [
    "records.imaging.write",
  ], "Live");
  await page.getByRole("button", { name: "I saved the secret" }).click();
  const row = page.getByTestId("connection").filter({ hasText: "Old radiology system" });
  await expect(row.getByTestId("mode-badge")).toHaveText("Live");
  await row.getByRole("button", { name: "Revoke" }).click();
  const dialog = page.getByRole("dialog", { name: "Revoke Old radiology system?" });
  await expect(dialog).toContainText("stops working immediately");
  await dialog.getByRole("button", { name: "Revoke key" }).click();
  await expect(row).toHaveCount(0);

  const token = await page.request.post(`${API}/oauth/token`, {
    form: { grant_type: "client_credentials", client_id: clientId, client_secret: secret },
  });
  expect(token.status()).toBe(401);
});

test("hospitals not approved never reach the dashboard; suspended ones see why", async ({ page }) => {
  // A hospital still applying: sent to its application.
  const applicant = seedApplicant("kna");
  await signInThroughForm(page, applicant.email, applicant.password);
  await page.waitForURL(/\/onboarding/);
  await page.goto("/keys");
  await expect(page).toHaveURL(/\/onboarding/);
  expect((await page.request.get("/api/connections")).status()).toBe(403);
  await page.context().clearCookies();

  // A suspended hospital: no page.
  const suspended = seedHospital("kns");
  await platform(page.request, "POST", `/platform/hospitals/${suspended.hospital_id}/suspend`);
  await signIn(page, suspended.accounts.admin.email, suspended.password);
  await page.goto("/keys");
  await expect(page.getByTestId("hospital-status-banner")).toHaveAttribute("data-status", "suspended");
  await expect(page.getByRole("heading", { name: "API keys" })).toHaveCount(0);
  expect((await page.request.get("/api/connections")).status()).toBe(403);
});
