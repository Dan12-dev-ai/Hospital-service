import { expect, test } from "@playwright/test";
import { enterCode, seedHospital, seedPrices, signIn, signInThroughForm, type SeededHospital } from "./helpers";

// The developer dashboard: overview, docs, playground (Test mode), settings and team.

let hospital: SeededHospital;

test.describe.configure({ timeout: 120_000 });

test.beforeAll(() => {
  hospital = seedHospital("dash");
  seedPrices(hospital.hospital_id);
});

test("sign in lands on the overview: the checklist and the mode summary", async ({ page }) => {
  await signInThroughForm(page, hospital.accounts.admin.email, hospital.password);
  await enterCode(page, hospital.accounts.admin.email);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  const checklist = page.getByTestId("checklist");
  await expect(checklist.getByTestId("checklist-item").filter({ hasText: "Approved by Endod" })).toHaveAttribute("data-done", "true");
  await expect(checklist.getByTestId("checklist-item").filter({ hasText: "Listed in the Endod app" })).toHaveAttribute("data-done", "true");
  await expect(checklist.getByTestId("checklist-item").filter({ hasText: "Test key created" })).toHaveAttribute("data-done", "false");
  await expect(page.getByTestId("test-keys")).toHaveText("0");
  await expect(page.getByTestId("live-keys")).toHaveText("0");
  await expect(page.getByTestId("openapi-link")).toHaveAttribute("href", /\/hospital\/v1\/openapi\.json$/);
  // Every section is in the sidebar; Team for administrators.
  const nav = page.getByRole("navigation", { name: "Dashboard" });
  for (const name of ["Overview", "Getting started", "API keys", "Webhooks", "Logs", "Playground", "Docs", "Settings", "Team"]) {
    await expect(nav.getByRole("link", { name, exact: true })).toBeVisible();
  }
  // None of the old portal's clinical pages.
  for (const path of ["/patients", "/appointments", "/queue", "/visit/x", "/billing", "/pharmacy"]) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(404);
  }
  await page.goto("/getting-started");
  await expect(page.getByTestId("getting-started").getByRole("heading")).toHaveCount(5);
});

test("the docs: every section in the sidebar, a page per record type, code to copy", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await signIn(page, hospital.accounts.developer.email, hospital.password);
  await page.goto("/docs");
  await expect(page.getByRole("heading", { level: 1, name: "Introduction" })).toBeVisible();
  const nav = page.getByTestId("docs-nav").filter({ visible: true });
  for (const name of [
    "Authentication",
    "Patients",
    "Lab results",
    "Imaging reports",
    "Prescriptions",
    "Diagnoses",
    "Visit notes",
    "Documents",
    "Bookings",
    "Follow-ups",
    "Queue",
    "Pricing",
    "Webhooks",
    "Errors",
    "Limits",
    "Test mode",
  ]) {
    await expect(nav.getByRole("link", { name, exact: true }).first()).toBeVisible();
  }

  await nav.getByRole("link", { name: "Authentication", exact: true }).click();
  await expect(page).toHaveURL(/\/docs\/authentication$/);
  const article = page.getByTestId("docs-article").filter({ visible: true });
  await expect(article.getByRole("heading", { level: 1 })).toHaveText("Authentication");
  // cURL, Node.js and Python, each with a copy button.
  await expect(article.getByTestId("code-block").filter({ hasText: "curl -s" }).first()).toBeVisible();
  await expect(article.getByTestId("code-block").filter({ hasText: "URLSearchParams" })).toBeVisible();
  await expect(article.getByTestId("code-block").filter({ hasText: "requests.post" }).first()).toBeVisible();
  await article.getByTestId("copy-code").first().click();
  await expect(article.getByTestId("copy-code").first()).toHaveText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("oauth/token");

  await nav.getByRole("link", { name: "Lab results", exact: true }).click();
  await expect(page).toHaveURL(/\/docs\/records\/lab-results$/);
  await expect(article).toContainText("records.labs.write");

  await nav.getByRole("link", { name: "Pricing", exact: true }).click();
  await expect(article).toContainText("PUT /prices/consultation");
  // Video visits are off: never in the docs.
  await nav.getByRole("link", { name: "Bookings", exact: true }).click();
  await expect(article).toContainText("POST /bookings/{id}/cancel");
  await expect(article).not.toContainText("approve");
  await expect(article).not.toContainText("video");
});

test("the playground sends requests in Test mode, from the server", async ({ page }) => {
  await signIn(page, hospital.accounts.developer.email, hospital.password);
  await page.goto("/playground");
  await expect(page.getByTestId("playground-mode")).toHaveText("Test mode");
  const endpoint = page.getByLabel("Endpoint");
  await expect(endpoint).toHaveValue("GET /bookings");
  await page.getByRole("button", { name: "Send request" }).click();
  const response = page.getByTestId("playground-response");
  await expect(response.getByTestId("response-status")).toHaveText("200");
  await expect(response.getByTestId("response-body")).toContainText('"sample": true');
  await expect(response.getByTestId("response-headers")).toContainText("content-type");

  // The body comes from the API reference's example.
  await endpoint.selectOption("PUT /prices/lab-tests");
  await expect(page.getByLabel("Body (from the API reference's example)")).toHaveValue(/"CBC"/);
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(response.getByTestId("response-status")).toHaveText("200");
  await expect(response.getByTestId("response-body")).toContainText('"sample": true');

  // Video visits are off: approving one is not an endpoint here.
  const options = await endpoint.locator("option").allTextContents();
  expect(options.some((o) => o.includes("/approve") || o.includes("/oauth/token"))).toBe(false);

  // A bad body is caught before it is sent; nothing secret ever reaches the page.
  await page.getByLabel("Body (from the API reference's example)").fill("{not json");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByTestId("form-error")).toHaveText("The body is not valid JSON.");
  expect(await page.content()).not.toMatch(/ehs_[A-Za-z0-9_-]{20,}/);

  // The playground's own key is never listed with the hospital's keys, and the token endpoint is not reachable.
  const keys = await (await page.request.get("/api/connections")).json();
  expect(JSON.stringify(keys)).not.toContain("playground");
  const refused = await page.request.post("/api/playground/send", { data: { method: "POST", path: "/oauth/token", body: "" } });
  expect(refused.status()).toBe(400);
  expect((await page.request.post("/api/playground/credentials", { data: {} })).status()).toBe(404);
});

test("settings: the consultation price and the synced price list; no video", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await expect(page.getByTestId("listing-status")).toContainText("Listed in the Endod app");
  await expect(page.getByLabel("Video visit price (birr)")).toHaveCount(0);
  await expect(page.getByText("Offer video visits")).toHaveCount(0);

  const priceList = page.getByTestId("price-list");
  await expect(priceList.getByTestId("consultation-price")).toHaveText("ETB 150.00");
  await expect(priceList.getByTestId("prices-lab_tests")).toContainText("Complete blood count");
  await expect(priceList.getByTestId("prices-lab_tests")).toContainText("ETB 350.00");
  await expect(priceList.getByTestId("prices-imaging")).toContainText("Chest X-ray");
  await expect(priceList.getByTestId("prices-procedures")).toContainText("Nothing synced yet.");

  await page.getByLabel("In-person visit price (birr)").fill("175.50");
  await page.getByLabel("City").fill("Adama");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByTestId("toast")).toHaveText("Hospital settings saved");
  const hospitalNow = await (await page.request.get("/api/hospital")).json();
  expect(hospitalNow).toMatchObject({ price_in_person: "175.50", city: "Adama", video_visits_offered: false });
  await page.reload();
  await expect(page.getByTestId("consultation-price")).toHaveText("ETB 175.50");
});

test("developers read the settings but cannot change them, and have no team page", async ({ page }) => {
  await signIn(page, hospital.accounts.developer.email, hospital.password);
  await page.goto("/settings");
  await expect(page.getByTestId("read-only-note")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save settings" })).toHaveCount(0);
  await expect(page.getByLabel("City")).toBeDisabled();
  await expect(page.getByRole("navigation", { name: "Dashboard" }).getByRole("link", { name: "Team" })).toHaveCount(0);
  await page.goto("/team");
  await expect(page.getByTestId("no-access")).toBeVisible();
  expect((await page.request.patch("/api/hospital", { data: { city: "Hawassa" } })).status()).toBe(403);
});

test("team: an admin invites a developer, who signs in with the temporary password, and removes them", async ({ page, browser }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  await page.goto("/team");
  const team = page.getByTestId("team");
  await expect(team.getByTestId("team-member").filter({ hasText: hospital.accounts.developer.email })).toContainText("Developer");
  await expect(team).not.toContainText(hospital.accounts.nurse.email);

  await page.getByRole("button", { name: "Invite member" }).click();
  const dialog = page.getByRole("dialog", { name: "Invite a member" });
  const email = `invited-${Date.now()}@dash.example`;
  await dialog.getByLabel("Email").fill(email);
  await dialog.getByLabel("Full name").fill("Invited Developer");
  await dialog.getByRole("button", { name: "Invite" }).click();
  const invited = page.getByTestId("invited");
  const temporary = ((await invited.getByTestId("temporary-password").textContent()) ?? "").trim();
  expect(temporary.length).toBeGreaterThanOrEqual(10);
  await invited.getByRole("button", { name: "Done" }).click();
  const member = team.getByTestId("team-member").filter({ hasText: email });
  await expect(member).toContainText("Invited");

  // They sign in with it and must change it first (then set up two-step verification).
  const other = await browser.newContext();
  const theirs = await other.newPage();
  await signInThroughForm(theirs, email, temporary);
  await expect(theirs).toHaveURL(/\/account\/password$/);
  await other.close();

  await member.getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog", { name: "Remove Invited Developer?" }).getByRole("button", { name: "Remove" }).click();
  await expect(member).toHaveCount(0);
  const refused = await page.request.post("/api/auth/login", { data: { email, password: temporary } });
  expect(refused.status()).toBe(401);
});
