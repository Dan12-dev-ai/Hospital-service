import { expect, test, type Page } from "@playwright/test";
import { BACKEND_URL } from "./env";
import { platform, seedApplicant, seedHospital, signIn, signInThroughForm, uniqueTag } from "./helpers";

// Demo times are Addis Ababa time; the browser is there too.
test.use({
  timezoneId: "Africa/Addis_Ababa",
  permissions: ["geolocation"],
  geolocation: { latitude: 9.0105, longitude: 38.7612 },
});

test.beforeEach(async ({ page }) => {
  // The map works without its tiles; the tests do not depend on OpenStreetMap.
  await page.route("https://tile.openstreetmap.org/**", (route) => route.abort());
});

const FAKE_PDF = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from(`%PDF-1.4\n% ${name}\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n`),
});

const DOCUMENTS = ["moh_license", "trade_license", "tin_certificate", "owner_id"] as const;

function stepOf(page: Page) {
  return page.getByTestId("onboarding-step-of");
}

async function uploadDocument(page: Page, kind: string, file: { name: string; mimeType: string; buffer: Buffer }) {
  const row = page.locator(`[data-testid="document-row"][data-kind="${kind}"]`);
  await row.locator('input[type="file"]').setInputFiles(file);
  return row;
}

test("a clinic applies step by step, resumes after a reload, and waits for Endod's review", async ({ page, request }) => {
  test.setTimeout(120_000);
  const tag = uniqueTag("ob");
  const name = `Selam ${tag} Clinic`;
  await page.goto("/signup");
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(stepOf(page)).toHaveText("Step 1 of 6");

  // 1. The account (the contact person).
  await page.getByRole("radio", { name: /Clinic/ }).click();
  await page.getByLabel("Facility name").fill(name);
  await page.getByLabel("Your full name").fill("Meron Tadesse");
  await page.getByLabel("Your role or title").fill("Clinic Manager");
  await page.getByLabel("Your mobile number").fill("0911 223 344");
  await page.getByLabel("Work email").fill(`admin@${tag}.example`);
  await page.getByLabel("Password", { exact: true }).fill("Signup-password-1");
  await page.getByLabel("Confirm password").fill("Signup-password-2");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByTestId("form-error")).toHaveText("The two passwords do not match.");
  await page.getByLabel("Confirm password").fill("Signup-password-1");
  await page.getByRole("button", { name: "Create account" }).click();

  // 2. The facility.
  await expect(stepOf(page)).toHaveText("Step 2 of 6");
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue(name);
  await expect(page.getByRole("radio", { name: /Clinic/ })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("radio", { name: "Public" }).click();
  await page.getByLabel("Name in Amharic (optional)").fill("ሰላም ክሊኒክ");
  await page.getByLabel("City").fill("Addis Ababa");
  await page.getByLabel("Facility phone").fill("011 551 7611");
  await page.getByLabel("General medicine").check();
  await page.getByLabel("Pediatrics").check();
  await page.getByLabel("Opening hours").fill("Mon–Sat 08:00–18:00");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(stepOf(page)).toHaveText("Step 3 of 6");

  // Saved as it goes: a reload comes back to the same step.
  await page.reload();
  await expect(stepOf(page)).toHaveText("Step 3 of 6");

  // 3. The location: the browser's position, then the pin dragged a little.
  await expect(page.getByTestId("location-map")).toHaveAttribute("data-ready", "true");
  await page.getByRole("button", { name: "Use my location" }).click();
  await expect(page.getByLabel("Latitude")).toHaveValue("9.010500");
  await expect(page.getByLabel("Longitude")).toHaveValue("38.761200");
  await expect(page.getByTestId("location-note")).toContainText("Location found");
  const pin = page.locator(".leaflet-marker-icon");
  const box = await pin.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width / 2 + 60, box!.y + box!.height / 2 + 40, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByLabel("Latitude")).not.toHaveValue("9.010500");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("form-error")).toHaveText("Enter the address.");
  await page.getByLabel("Address").fill("Bole Road, near Edna Mall");
  await page.getByRole("button", { name: "Continue" }).click();

  // 4. Documents: all four are required, and only real PDFs or images pass.
  await expect(stepOf(page)).toHaveText("Step 4 of 6");
  await page.getByLabel("Ministry of Health facility license number").fill("MOH/AA/7781");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("form-error")).toContainText("Upload every document first");
  const fake = await uploadDocument(page, "tin_certificate", {
    name: "tin.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("not really a PDF"),
  });
  await expect(fake.getByRole("alert")).toHaveText("Only PDF, JPEG, PNG or WebP files can be attached.");
  for (const kind of DOCUMENTS) {
    const row = await uploadDocument(page, kind, FAKE_PDF(`${kind}.pdf`));
    await expect(row).toHaveAttribute("data-uploaded", "true");
    await expect(row.getByTestId("document-status")).toContainText(`Uploaded: ${kind}.pdf`);
  }
  // Replacing one keeps one document of that kind.
  const replaced = await uploadDocument(page, "owner_id", FAKE_PDF("manager-id-clearer.pdf"));
  await expect(replaced.getByTestId("document-status")).toContainText("Uploaded: manager-id-clearer.pdf");
  await expect(replaced.getByRole("button", { name: "Replace" })).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();

  // 5. The demo.
  await expect(stepOf(page)).toHaveText("Step 5 of 6");
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
  const firstSlot = page.getByTestId("demo-slot").first();
  const firstTime = (await firstSlot.textContent())!.trim();
  await firstSlot.click();
  await page.getByRole("button", { name: "Book this time" }).click();
  await expect(page.getByTestId("demo-current")).toContainText(firstTime);
  await page.getByRole("button", { name: "Continue" }).click();

  // 6. Review and submit.
  await expect(stepOf(page)).toHaveText("Step 6 of 6");
  const summary = page.getByTestId("review-summary");
  await expect(summary).toContainText(name);
  await expect(summary).toContainText("Public clinic in Addis Ababa");
  await expect(summary).toContainText("Bole Road, near Edna Mall");
  await expect(summary).toContainText("MOH/AA/7781");
  await page.getByRole("button", { name: "Submit application" }).click();

  // Under review: the facility, the demo in Addis Ababa time, what happens next.
  await expect(page).toHaveURL(/\/under-review$/);
  await expect(page.getByTestId("under-review")).toHaveAttribute("data-status", "submitted");
  await expect(page.getByTestId("under-review-name")).toHaveText(name);
  await expect(page.getByTestId("under-review-demo")).toContainText(`${firstTime} (Addis Ababa time)`);
  await expect(page.getByText("What happens next")).toBeVisible();

  // Nothing else of the portal opens, through pages or the API.
  await page.goto("/patients");
  await expect(page).toHaveURL(/\/under-review$/);
  expect((await page.request.get("/api/hospital")).status()).toBe(403);

  // The demo can be moved until Endod approves.
  await page.getByRole("button", { name: "Change time" }).click();
  const later = page.getByTestId("demo-slot").filter({ hasNot: page.getByText("yours") }).nth(3);
  const laterTime = (await later.textContent())!.trim();
  await later.click();
  await page.getByRole("button", { name: "Move my demo" }).click();
  await expect(page.getByTestId("under-review-demo")).toContainText(`${laterTime} (Addis Ababa time)`);

  // Endod sends it back with a reason; the clinic fixes it and resubmits.
  const applications = (await platform(request, "GET", "/platform/applications?status=submitted")) as {
    hospital_id: string;
    name: string;
  }[];
  const mine = applications.find((a) => a.name === name);
  expect(mine).toBeDefined();
  await platform(request, "POST", `/platform/hospitals/${mine!.hospital_id}/reject`, {
    reason: "The TIN certificate is unreadable; upload a clearer scan.",
  });
  await page.reload();
  await expect(page.getByTestId("rejection-reason")).toContainText("The TIN certificate is unreadable");
  await page.getByRole("link", { name: "Fix and resubmit" }).click();
  await expect(page).toHaveURL(/\/onboarding\?fix=1$/);
  await expect(stepOf(page)).toHaveText("Step 6 of 6");
  await expect(page.getByTestId("rejection-note")).toContainText("unreadable");
  await page.getByTestId("review-summary").getByRole("button", { name: "Edit" }).nth(3).click();
  await expect(stepOf(page)).toHaveText("Step 4 of 6");
  await uploadDocument(page, "tin_certificate", FAKE_PDF("tin-clear.pdf"));
  await expect(page.locator('[data-kind="tin_certificate"]').getByTestId("document-status")).toContainText("tin-clear.pdf");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Resubmit application" }).click();
  await expect(page.getByTestId("under-review")).toHaveAttribute("data-status", "submitted");

  // Approved: the whole portal, as for any hospital.
  await platform(request, "POST", `/platform/hospitals/${mine!.hospital_id}/approve`);
  await page.goto("/under-review");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("hospital-status-banner")).toHaveAttribute("data-status", "unlisted");
  expect((await page.request.get("/api/hospital")).status()).toBe(200);
});

test("a demo time goes to one hospital only", async ({ page, request }) => {
  const mine = seedApplicant("sa", "complete");
  const rival = seedApplicant("sb", "complete");
  await signIn(page, mine.email, mine.password);
  await page.goto("/onboarding");
  await expect(stepOf(page)).toHaveText("Step 5 of 6");

  const slot = page.getByTestId("demo-slot").nth(2);
  const wanted = await slot.getAttribute("data-slot");
  await slot.click();

  // Meanwhile the other hospital books that very time.
  const login = await request.post(`${BACKEND_URL}/auth/login`, { data: { email: rival.email, password: rival.password } });
  const token = ((await login.json()) as { access_token: string }).access_token;
  const booked = await request.post(`${BACKEND_URL}/onboarding/demo`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { demo_at: wanted },
  });
  expect(booked.status(), await booked.text()).toBe(200);

  await page.getByRole("button", { name: "Book this time" }).click();
  await expect(page.getByTestId("form-error")).toHaveText("Another hospital has just booked that time. Choose another one.");
  // The calendar reloads without it.
  await expect(page.locator(`[data-slot="${wanted}"]`)).toHaveCount(0);
  await page.getByTestId("demo-slot").first().click();
  await page.getByRole("button", { name: "Book this time" }).click();
  await expect(page.getByTestId("demo-current")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled();
});

test("a hospital that is not approved sees only its application", async ({ page }) => {
  test.setTimeout(120_000);
  const draft = seedApplicant("lk");
  await signIn(page, draft.email, draft.password);
  for (const path of ["/", "/patients", "/settings", "/doctors", "/queue"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByTestId("step-facility")).toBeVisible();
  }
  for (const path of ["/api/hospital", "/api/patients", "/api/staff", "/api/bookings"]) {
    const response = await page.request.get(path);
    expect(response.status(), path).toBe(403);
  }
  // A sign-in goes straight back to the application.
  await page.request.post("/api/auth/logout");
  await signInThroughForm(page, draft.email, draft.password);
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(stepOf(page)).toHaveText("Step 2 of 6");

  // Once submitted, every page leads to Under review.
  const submitted = seedApplicant("lu", "submitted");
  await signIn(page, submitted.email, submitted.password);
  for (const path of ["/", "/billing", "/onboarding"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/under-review$/);
  }
  await expect(page.getByTestId("under-review-name")).toHaveText(submitted.name);

  // An approved hospital never sees the application.
  const approved = seedHospital("lv");
  await signIn(page, approved.accounts.admin.email, approved.password);
  await page.goto("/onboarding");
  await expect(page).toHaveURL(/\/$/);
});

test("Endod's platform endpoints are not reachable through the portal", async ({ page }) => {
  for (const path of ["/api/platform/hospitals", "/api/platform/applications"]) {
    const response = await page.request.get(path, { headers: { "X-Platform-Key": "e2e-platform-key" } });
    expect(response.status()).toBe(404);
  }
});
