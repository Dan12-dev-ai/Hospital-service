import { expect, test, type Page } from "@playwright/test";
import {
  platform,
  registerPatient,
  seedApplicant,
  seedHospital,
  signIn,
  signInThroughForm,
  totpCode,
  type SeededHospital,
} from "./helpers";
import { BACKEND_URL } from "./env";

// "Connect your system": the hospital's own systems and the integration API.

let hospital: SeededHospital;

// Each sign-in and each fresh confirmation uses a new authenticator code; the
// test clock may wait for the next 30-second step.
test.describe.configure({ timeout: 120_000 });

test.beforeAll(() => {
  hospital = seedHospital("con");
});

async function asAdmin(page: Page) {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
}

/** The 3 steps, through a fresh code from the admin's authenticator. Returns the client ID and secret. */
async function connectSystem(page: Page, name: string, abilities: string[], mode: "Live" | "Test" = "Live") {
  await page.goto("/connect");
  await page.getByRole("button", { name: "Connect a system" }).click();
  const dialog = page.getByRole("dialog", { name: "Connect a system" });
  await expect(dialog.getByTestId("connect-step")).toHaveText("Step 1 of 3");
  await dialog.getByLabel("What is the system called?").fill(name);
  await dialog.getByRole("button", { name: "Next" }).click();
  await expect(dialog.getByTestId("connect-step")).toHaveText("Step 2 of 3");
  for (const ability of abilities) await dialog.getByText(ability, { exact: true }).click();
  await dialog.getByText(mode, { exact: true }).click();
  await dialog.getByRole("button", { name: "Connect" }).click();

  // Re-authentication: a fresh code from the admin's authenticator app.
  const confirm = page.getByTestId("confirm-code");
  await expect(confirm).toBeVisible();
  await confirm.getByLabel("Confirm it's you: enter the code from your authenticator app").fill(
    totpCode(hospital.accounts.admin.email)
  );
  await confirm.getByRole("button", { name: "Connect" }).click();

  const done = page.getByTestId("connect-done");
  await expect(page.getByTestId("connect-step")).toHaveText("Step 3 of 3");
  await expect(done).toContainText("Save the secret now");
  const clientId = (await done.getByTestId("client-id").textContent()) ?? "";
  const secret = (await done.getByTestId("client-secret").textContent()) ?? "";
  return { clientId, secret, done };
}

test("an admin connects a system in 3 steps; the secret is shown once", async ({ page }) => {
  await asAdmin(page);
  await page.goto("/");
  await page.getByRole("link", { name: "Connect your system" }).first().click();
  await expect(page).toHaveURL(/\/connect$/);
  await expect(page.getByRole("link", { name: "Developer guide" })).toHaveAttribute("href", /\/integrations\/v1\/docs$/);

  // A wrong code is refused and nothing is connected.
  await page.getByRole("button", { name: "Connect a system" }).click();
  const dialog = page.getByRole("dialog", { name: "Connect a system" });
  await dialog.getByLabel("What is the system called?").fill("Wrong code system");
  await dialog.getByRole("button", { name: "Next" }).click();
  await dialog.getByText("Send lab results", { exact: true }).click();
  await dialog.getByRole("button", { name: "Connect" }).click();
  const confirm = page.getByTestId("confirm-code");
  await confirm.getByLabel("Confirm it's you: enter the code from your authenticator app").fill("000000");
  await confirm.getByRole("button", { name: "Connect" }).click();
  await expect(confirm.getByTestId("form-error")).toContainText("That code is not valid");
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Close dialog" }).click();
  expect((await (await page.request.get("/api/connections")).json()).items).toHaveLength(0);

  const { clientId, secret, done } = await connectSystem(page, "Main lab system", ["Send lab results", "See bookings"]);
  expect(clientId).toMatch(/^endod_live_[0-9a-f]{24}$/);
  expect(secret.length).toBeGreaterThanOrEqual(40);
  await expect(done.getByRole("link", { name: "Download setup guide" })).toHaveAttribute("href", /\/connect\/[0-9a-f]{32}\/setup-guide$/);

  // The printable setup guide: the details, never the secret.
  const href = (await done.getByRole("link", { name: "Download setup guide" }).getAttribute("href")) ?? "";
  const guide = await page.context().newPage();
  await guide.goto(href);
  await expect(guide.getByTestId("setup-guide")).toContainText(clientId);
  await expect(guide.getByTestId("setup-guide")).toContainText("/oauth/token");
  await expect(guide.getByTestId("setup-guide")).toContainText("records.labs.write");
  expect(await guide.content()).not.toContain(secret);
  await guide.close();

  await page.getByRole("button", { name: "I saved the secret" }).click();
  const card = page.getByTestId("connection").filter({ hasText: "Main lab system" });
  await expect(card).toContainText("Send lab results");
  await expect(card).toContainText("See bookings");
  await expect(card.getByTestId("mode-badge")).toHaveText("Live");
  await expect(card.getByTestId("last-used")).toHaveText("Not used yet");
  // Shown once: never again, on the page or from the API.
  expect(await page.content()).not.toContain(secret);
  expect(await (await page.request.get("/api/connections")).text()).not.toContain(secret);
  // No jargon on the main page.
  const main = await page.locator("main").innerText();
  for (const word of ["OAuth", "scope", "webhook"]) expect(main.toLowerCase()).not.toContain(word.toLowerCase());
});

test("the Advanced panel: IP restriction, webhook with a test event, logs", async ({ page }) => {
  await asAdmin(page);
  const { clientId, secret } = await connectSystem(page, "Pharmacy system", ["Send prescriptions"], "Test");
  await page.getByRole("button", { name: "I saved the secret" }).click();
  const card = page.getByTestId("connection").filter({ hasText: "Pharmacy system" });
  await expect(card.getByTestId("mode-badge")).toHaveText("Test");

  // A token from the system's side, then it shows as used.
  const token = await page.request.post(`${BACKEND_URL}/integrations/v1/oauth/token`, {
    form: { grant_type: "client_credentials" },
    headers: { Authorization: `Basic ${Buffer.from(`${clientId}:${secret}`).toString("base64")}` },
  });
  expect(token.status()).toBe(200);

  await page.reload();
  await card.getByRole("button", { name: "Advanced" }).click();
  const advanced = card.getByTestId("advanced");
  await expect(advanced.getByTestId("request-log")).toContainText("POST /integrations/v1/oauth/token");
  await expect(card.getByTestId("last-used")).toHaveText(/Last used/);

  await advanced.getByLabel("Allowed IP addresses").fill("196.188.10.0/24\n127.0.0.1");
  // The code given to connect is fresh for 10 minutes: no new one asked.
  await advanced.getByRole("button", { name: "Save addresses" }).click();
  await expect(page.getByTestId("confirm-code")).toHaveCount(0);
  await expect(advanced.getByLabel("Allowed IP addresses")).toHaveValue("196.188.10.0/24\n127.0.0.1");

  await advanced.getByLabel("Webhook URL").fill("https://hooks.example.com/endod");
  await advanced.getByRole("button", { name: "Save webhook" }).click();
  await expect(page.getByTestId("revealed-secret")).toContainText("whsec_");
  await page.getByRole("button", { name: "I saved it" }).click();

  await advanced.getByRole("button", { name: "Send test event" }).click();
  await advanced.getByRole("button", { name: "Refresh" }).click();
  await expect(advanced.getByTestId("delivery-log")).toContainText("endpoint.test");
});

test("disconnecting asks for confirmation (and a fresh code), and stops the system", async ({ page }) => {
  await asAdmin(page);
  const { clientId, secret } = await connectSystem(page, "Old radiology system", ["Send imaging reports"]);
  await page.getByRole("button", { name: "I saved the secret" }).click();
  const card = page.getByTestId("connection").filter({ hasText: "Old radiology system" });
  await card.getByRole("button", { name: "Disconnect" }).click();
  const dialog = page.getByRole("dialog", { name: "Disconnect Old radiology system?" });
  await expect(dialog).toContainText("It stops working immediately");
  await dialog.getByRole("button", { name: "Disconnect" }).click();
  await expect(card).toHaveCount(0);

  const token = await page.request.post(`${BACKEND_URL}/integrations/v1/oauth/token`, {
    form: { grant_type: "client_credentials", client_id: clientId, client_secret: secret },
  });
  expect(token.status()).toBe(401);
});

test("hospitals not approved, and staff who are not admins, do not see the page", async ({ page }) => {
  // A hospital still applying: sent to its application.
  const applicant = seedApplicant("cna");
  await signInThroughForm(page, applicant.email, applicant.password);
  await page.waitForURL(/\/onboarding/);
  await page.goto("/connect");
  await expect(page).toHaveURL(/\/onboarding/);
  expect((await page.request.get("/api/connections")).status()).toBe(403);
  await page.context().clearCookies();

  // A suspended hospital: no nav item, no page.
  const suspended = seedHospital("cns");
  await platform(page.request, "POST", `/platform/hospitals/${suspended.hospital_id}/suspend`);
  await signIn(page, suspended.accounts.admin.email, suspended.password);
  await page.goto("/connect");
  await expect(page.getByTestId("connect-not-approved")).toBeVisible();
  await expect(page.getByRole("link", { name: "Connect your system" })).toHaveCount(0);
  expect((await page.request.get("/api/connections")).status()).toBe(403);
  await page.context().clearCookies();

  // Not an admin.
  await signIn(page, hospital.accounts.doctor.email, hospital.password);
  await page.goto("/connect");
  await expect(page.getByTestId("no-access")).toBeVisible();
  await expect(page.getByRole("link", { name: "Connect your system" })).toHaveCount(0);
});

test("end to end: a token, a lab result Bundle, and the record in the portal", async ({ page }) => {
  await asAdmin(page);
  const patient = await registerPatient(page, "Selam Integration");
  const { clientId, secret } = await connectSystem(page, "Hospital LIS", ["Send lab results"]);
  await page.getByRole("button", { name: "I saved the secret" }).click();
  const about = await (await page.request.get("/api/connections")).json();

  // The hospital's system, as curl would: a token, then the Bundle.
  const api = `${BACKEND_URL}/integrations/v1`;
  const tokenResponse = await page.request.post(`${api}/oauth/token`, {
    form: { grant_type: "client_credentials", scope: "records.labs.write" },
    headers: { Authorization: `Basic ${Buffer.from(`${clientId}:${secret}`).toString("base64")}` },
  });
  expect(tokenResponse.status(), await tokenResponse.text()).toBe(200);
  const { access_token: accessToken, expires_in: expiresIn } = await tokenResponse.json();
  expect(expiresIn).toBe(300);

  const bundle = {
    resourceType: "Bundle",
    type: "transaction",
    entry: [
      {
        request: { method: "PUT", url: "Observation/hb-e2e-1" },
        resource: {
          resourceType: "Observation",
          id: "hb-e2e-1",
          meta: { versionId: "1" },
          status: "final",
          category: [{ coding: [{ code: "laboratory" }] }],
          code: { text: "Hemoglobin E2E" },
          subject: { identifier: { system: about.mrn_system, value: patient.mrn } },
          effectiveDateTime: new Date(Date.now() - 3600_000).toISOString(),
          valueQuantity: { value: 13.2, unit: "g/dL" },
        },
      },
    ],
  };
  const posted = await page.request.post(`${api}/fhir`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/fhir+json",
      "Idempotency-Key": "e2e-lab-0001",
    },
    data: JSON.stringify(bundle),
  });
  expect(posted.status(), await posted.text()).toBe(200);
  const answer = await posted.json();
  expect(answer.type).toBe("transaction-response");
  expect(answer.entry[0].response.status).toBe("201 Created");

  await page.goto(`/patients/${patient.id}`);
  const card = page.getByTestId("record-card").filter({ hasText: "Hemoglobin E2E" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("13.2");
});
