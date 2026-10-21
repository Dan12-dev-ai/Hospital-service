import { expect, test, type Page } from "@playwright/test";
import {
  newDedanId,
  registerPatient,
  seedBooking,
  seedHospital,
  seedLink,
  seedLinkReply,
  seedQueueYesterday,
  seedShare,
  signIn,
  type SeededHospital,
} from "./helpers";
import { PORTAL_PORT } from "./env";

// Dates (follow-ups, "today's" queue) are the hospital's: Addis Ababa time.
test.use({ timezoneId: "Africa/Addis_Ababa" });

const PDF = Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n");

let hospital: SeededHospital;

test.beforeAll(() => {
  hospital = seedHospital("hist");
});

async function as(page: Page, account: keyof SeededHospital["accounts"]) {
  await signIn(page, hospital.accounts[account].email, hospital.password);
}

/** "YYYY-MM-DD" in Addis Ababa, `days` from today. */
function addisDay(days: number): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Addis_Ababa" }).format(new Date());
  const [y, m, d] = today.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

test("reception links a patient by Endod ID and phone, Endod confirms, and reception unlinks", async ({ page }) => {
  await as(page, "reception");
  const patient = await registerPatient(page, "Meron Linked");
  const dedanId = newDedanId();
  await page.goto(`/patients/${patient.id}`);
  const status = page.getByTestId("endod-link-status");
  await expect(status).toContainText("Not linked");
  // Reception identifies patients but does not read clinical records.
  await expect(page.getByText("Clinical records are shown to clinical and records staff only.")).toBeVisible();

  await page.getByLabel("Endod ID").fill(dedanId);
  await page.getByLabel("Phone on the Endod account").fill("0911 234 567");
  await page.getByRole("button", { name: "Link to Endod" }).click();
  await expect(status).toContainText("Pending");
  await expect(status).toContainText(dedanId);

  // The platform's reply, handled as the event worker would.
  seedLinkReply(patient.id, "linked");
  await expect(status).toContainText(`Linked to Endod ${dedanId}`);
  await expect(page.getByText(`Endod ${dedanId}`, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Unlink" }).click();
  await expect(status).toContainText("Not linked");
});

test("a health card link is sent to Endod, and a refusal shows why", async ({ page }) => {
  await as(page, "reception");
  const patient = await registerPatient(page, "Kebede Refused");
  await page.goto(`/patients/${patient.id}`);
  await page.getByRole("tab", { name: "Scan health card" }).click();
  await page.getByLabel(/card.s link/).fill("https://evil.example/card/DE123456?s=abcdefgh");
  await page.getByRole("button", { name: "Link with card" }).click();
  await expect(page.getByTestId("form-error")).toContainText("not an Endod health card");

  await page.getByLabel(/card.s link/).fill(`https://endod-health.com/card/${newDedanId()}?s=abcdefgh12345`);
  await page.getByRole("button", { name: "Link with card" }).click();
  const status = page.getByTestId("endod-link-status");
  await expect(status).toContainText("health card");

  seedLinkReply(patient.id, "refused", "not_verified");
  await expect(status).toContainText("Refused");
  await expect(status).toContainText("did not match");
});

test("a doctor adds a diagnosis with a file, opens the file, and retracts the record", async ({ page }) => {
  await as(page, "doctor");
  const patient = await registerPatient(page, "Almaz Records");
  seedLink(patient.id, newDedanId());
  await page.goto(`/patients/${patient.id}`);

  await page.getByRole("button", { name: "Add record" }).click();
  const dialog = page.getByRole("dialog", { name: "Add record" });
  await dialog.locator("#record-category").selectOption("diagnosis");
  await dialog.locator("#record-title").fill("Malaria");
  await dialog.locator("#record-condition").fill("Plasmodium falciparum malaria");
  await dialog.locator("#record-code").fill("B50.9");
  await dialog.locator("#record-files").setInputFiles({ name: "smear.pdf", mimeType: "application/pdf", buffer: PDF });
  await expect(dialog.getByTestId("chosen-files")).toContainText("smear.pdf");
  await dialog.getByRole("button", { name: "Save record" }).click();
  await expect(dialog).toHaveCount(0);

  const card = page.getByTestId("record-card").filter({ hasText: "Malaria" });
  await expect(card).toContainText("Sent to Endod");
  await expect(card).toContainText("B50.9");
  const link = card.getByRole("link", { name: "smear.pdf", exact: true });
  const href = await link.getAttribute("href");
  expect(href).toMatch(/^\/api\/download\/records\/[0-9a-f]{32}\/files\/[0-9a-f]{32}$/);
  const file = await page.request.get(href!);
  expect(file.status()).toBe(200);
  expect(file.headers()["content-type"]).toBe("application/pdf");
  expect(file.headers()["x-content-type-options"]).toBe("nosniff");
  expect(file.headers()["content-security-policy"]).toContain("frame-ancestors 'self'");
  expect((await file.body()).subarray(0, 5).toString()).toBe("%PDF-");
  const saved = await page.request.get(`${href}?download=1`);
  expect(saved.headers()["content-disposition"]).toMatch(/^attachment/);

  await card.getByRole("button", { name: "Retract" }).click();
  const retract = page.getByRole("dialog", { name: "Retract record" });
  await retract.getByLabel("Reason").fill("Wrong patient");
  await retract.getByRole("button", { name: "Retract" }).click();
  await expect(card).toContainText("Retracted");
  await expect(card).toContainText("Wrong patient");
});

test("a doctor opens a visit with a follow-up and cancels it", async ({ page }) => {
  await as(page, "doctor");
  const patient = await registerPatient(page, "Tsion Followup");
  seedLink(patient.id, newDedanId());
  await page.goto(`/patients/${patient.id}`);
  await page.getByRole("tab", { name: "Visits and follow-ups" }).click();

  await page.getByRole("button", { name: "Open visit" }).click();
  const dialog = page.getByRole("dialog", { name: "Open visit" });
  await dialog.getByLabel(/Follow-up date/).fill(addisDay(14));
  await dialog.getByLabel(/Note for the patient/).fill("Bring the lab results");
  await dialog.getByRole("button", { name: "Save" }).click();

  const followUp = page.getByTestId("visit-row").getByTestId("follow-up");
  await expect(followUp).toContainText("Bring the lab results");
  await expect(followUp).toContainText("sent to Endod");

  await page.getByRole("button", { name: "Cancel follow-up" }).click();
  await expect(page.getByTestId("visit-row")).toContainText("No follow-up");
});

test("reception checks in a booking and a walk-in; the doctor calls the next patient", async ({ page }) => {
  await as(page, "reception");
  const doctor = hospital.accounts.doctor.name;
  const record = await registerPatient(page, "Bekele Queue");
  seedBooking(hospital.hospital_id, "in_person", 5, "Bekele Queue");
  await page.goto("/queue");

  // The Endod booking, with the patient's hospital record (which this links to Endod).
  await page.getByRole("button", { name: "Check in" }).click();
  let dialog = page.getByRole("dialog", { name: "Check in" });
  const bookingValue = await dialog.locator("#checkin-booking option", { hasText: "Bekele Queue" }).getAttribute("value");
  await dialog.locator("#checkin-booking").selectOption(bookingValue!);
  await dialog.locator("#checkin-search").fill("Bekele Queue");
  await dialog.getByText(record.mrn).click();
  const doctorValue = await dialog.locator("#checkin-doctor option", { hasText: doctor }).getAttribute("value");
  await dialog.locator("#checkin-doctor").selectOption(doctorValue!);
  await dialog.getByRole("button", { name: "Check in" }).click();
  await expect(dialog).toHaveCount(0);

  // A walk-in with a phone number.
  await page.getByRole("button", { name: "Check in" }).click();
  dialog = page.getByRole("dialog", { name: "Check in" });
  await dialog.getByRole("tab", { name: "Walk-in" }).click();
  await dialog.getByLabel("Name", { exact: true }).fill("Hirut Walkin");
  await dialog.getByLabel(/Phone/).fill("0922 345 678");
  await dialog.locator("#checkin-doctor").selectOption(doctorValue!);
  await dialog.getByRole("button", { name: "Check in" }).click();
  await expect(dialog).toHaveCount(0);

  const queue = page.getByTestId("queue-card").filter({ hasText: doctor });
  await expect(queue.getByTestId("queue-entry")).toHaveCount(2);
  await expect(queue).toContainText("2 waiting");
  await expect(queue.getByTestId("queue-entry").filter({ hasText: "Hirut Walkin" })).toContainText("1 ahead");

  // The booking linked the hospital record to Endod.
  const linked = await page.request.get(`/api/patients/${record.id}/link`);
  expect((await linked.json()).dedan_id).toMatch(/^DE\d{6}$/);

  // The doctor sees only their own queue and calls the next patient.
  await as(page, "doctor");
  await page.goto("/queue");
  await expect(page.getByRole("heading", { name: "My queue" })).toBeVisible();
  await expect(page.getByTestId("queue-card")).toHaveCount(1);
  await page.getByRole("button", { name: "Call next" }).click();
  const first = page.getByTestId("queue-entry").filter({ hasText: "Bekele Queue" });
  await expect(first).toContainText("called");
  await expect(page.getByRole("button", { name: "Call next" })).toBeDisabled();
  await first.getByRole("button", { name: "Done" }).click();
  await expect(page.getByTestId("queue-entry").filter({ hasText: "Bekele Queue" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Call next" })).toBeEnabled();
});

test("an admin sets when the queue's get-ready SMS goes out", async ({ page }) => {
  await as(page, "admin");
  await page.goto("/settings");
  await page.locator("#h-queue-ahead").fill("2");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Hospital settings saved")).toBeVisible();
  await page.goto("/queue");
  await expect(page.getByText(/SMS when 2 people are ahead/)).toBeVisible();
});

test("records staff import a CSV: the preview shows what is imported and skipped, then confirm", async ({ page }) => {
  await as(page, "records");
  const patient = await registerPatient(page, "Yonas Import");
  seedLink(patient.id, newDedanId());
  await page.goto("/import");

  const csv = [
    "mrn,endod_id,category,title,occurred_at,recorded_by,condition,icd10_code,status",
    `${patient.mrn},,diagnosis,Type 2 diabetes,2025-03-01,Dr. Hana Bekele,Type 2 diabetes mellitus,E11,chronic`,
    "NOPE-000001,,diagnosis,Asthma,2025-03-01,Dr. Hana Bekele,Asthma,J45,active",
  ].join("\n");
  await page.locator("#import-file").setInputFiles({ name: "history.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Preview" }).click();

  const preview = page.getByTestId("import-preview");
  await expect(preview.getByTestId("import-item")).toHaveCount(1);
  await expect(preview.getByTestId("import-item")).toContainText("Type 2 diabetes");
  await expect(preview.getByTestId("import-skipped")).toHaveCount(1);
  await expect(preview.getByTestId("import-skipped")).toContainText("row 3");
  await preview.getByRole("button", { name: "Import 1 record" }).click();
  await expect(page.getByTestId("import-result")).toContainText("Imported 1 record");

  await page.goto(`/patients/${patient.id}`);
  const card = page.getByTestId("record-card").filter({ hasText: "Type 2 diabetes" });
  await expect(card).toContainText("imported");
  await expect(card).toContainText("Sent to Endod");
});

test("records a patient shared through Endod show read-only, overall and on the patient", async ({ page }) => {
  await as(page, "doctor");
  const patient = await registerPatient(page, "Selam Shared");
  const dedanId = newDedanId();
  seedLink(patient.id, dedanId);
  seedShare(hospital.hospital_id, dedanId, "Selam Shared", "Complete blood count");

  await page.goto("/shared");
  const share = page.getByTestId("share-card").filter({ hasText: "Complete blood count" });
  await expect(share).toContainText("Tikur Anbessa Hospital");
  await expect(share.getByRole("link", { name: "cbc.pdf", exact: true })).toHaveAttribute(
    "href",
    /^\/api\/download\/shared\/[0-9a-f]{32}\/files\/[0-9a-f]{32}$/
  );
  await share.getByRole("link", { name: /Selam Shared/ }).click();

  await expect(page.getByTestId("patient-name")).toContainText("Selam Shared");
  await page.getByRole("tab", { name: "Shared with us" }).click();
  // Scoped to the page shown: Next keeps the previous page (the Shared list)
  // in the document, hidden, for fast back navigation.
  const sharedHere = page.getByRole("main").getByTestId("shared-record");
  await expect(sharedHere).toContainText("Complete blood count");
  await expect(sharedHere).toContainText("Hemoglobin");
  await expect(page.getByRole("button", { name: "Retract" })).toHaveCount(0);
});

test("file routes refuse cross-site uploads and paths outside their allowlist", async ({ page }) => {
  await as(page, "doctor");
  const patient = await registerPatient(page, "Guard Files");
  const upload = `/api/upload/patients/${patient.id}/uploads`;
  const file = { name: "x.pdf", mimeType: "application/pdf", buffer: PDF };

  // No Origin and no portal header (a cross-site form): refused.
  let response = await page.request.post(upload, { multipart: { file } });
  expect(response.status()).toBe(403);
  // A foreign Origin, even with the header: refused.
  response = await page.request.post(upload, {
    multipart: { file },
    headers: { Origin: "https://evil.example", "X-Portal-Upload": "1" },
  });
  expect(response.status()).toBe(403);
  // Not an upload path.
  response = await page.request.post("/api/upload/patients", { multipart: { file } });
  expect(response.status()).toBe(404);

  for (const path of [
    "/api/download/records/..%2F..%2Fetc/files/passwd",
    "/api/download/platform/records/0123456789abcdef0123456789abcdef/files/0123456789abcdef0123456789abcdef",
    "/api/platform/records/0123456789abcdef0123456789abcdef/files/0123456789abcdef0123456789abcdef",
  ]) {
    expect((await page.request.get(path)).status(), path).toBe(404);
  }
});

test("a doctor corrects a record: a new version, shown as corrected and sent to Endod again", async ({ page }) => {
  await as(page, "doctor");
  const patient = await registerPatient(page, "Hana Corrected");
  seedLink(patient.id, newDedanId());
  await page.goto(`/patients/${patient.id}`);

  await page.getByRole("button", { name: "Add record" }).click();
  const add = page.getByRole("dialog", { name: "Add record" });
  await add.locator("#record-category").selectOption("diagnosis");
  await add.locator("#record-title").fill("Typhoid");
  await add.locator("#record-condition").fill("Typhoid fever");
  await add.locator("#record-code").fill("A01.0");
  await add.getByRole("button", { name: "Save record" }).click();
  await expect(add).toHaveCount(0);

  const card = page.getByTestId("record-card").filter({ hasText: "Typhoid" });
  await expect(card).toContainText("Sent to Endod");
  await expect(card.getByTestId("record-corrected")).toHaveCount(0);

  await card.getByRole("button", { name: "Edit / correct" }).click();
  const correct = page.getByRole("dialog", { name: "Correct record" });
  // The form opens with the record as it is; the category cannot change.
  await expect(correct.locator("#record-title")).toHaveValue("Typhoid");
  await expect(correct.locator("#record-condition")).toHaveValue("Typhoid fever");
  await expect(correct.locator("#record-category")).toBeDisabled();
  await correct.locator("#record-title").fill("Paratyphoid");
  await correct.locator("#record-condition").fill("Paratyphoid fever A");
  await correct.locator("#record-code").fill("A01.1");
  await correct.getByRole("button", { name: "Save correction" }).click();
  await expect(correct).toHaveCount(0);

  const corrected = page.getByTestId("record-card").filter({ hasText: "Paratyphoid" });
  await expect(corrected.getByTestId("record-corrected")).toContainText("Corrected • version 2");
  await expect(corrected).toContainText("A01.1");
  await expect(corrected).toContainText("Sent to Endod");
  const listed = await page.request.get(`/api/patients/${patient.id}/records`);
  const [record] = (await listed.json()).items;
  expect(record.version).toBe(2);
  expect(record.published_version).toBe(2);
});

test("an Endod ID typed at registration is only a claim until Endod confirms it", async ({ page }) => {
  await as(page, "reception");
  const claimed = newDedanId();
  const response = await page.request.post("/api/patients", {
    // Older clients still send the typed ID as dedan_id: it becomes a claim.
    data: { full_name: "Abel Claimed", sex: "male", age_years: 30, phone: "0911 234 567", dedan_id: claimed, confirm_duplicate: true },
  });
  expect(response.status()).toBe(201);
  const patient = await response.json();
  expect(patient.dedan_id).toBeNull();
  expect(patient.claimed_dedan_id).toBe(claimed);

  await page.goto(`/patients/${patient.id}`);
  await expect(page.getByTestId("claimed-endod-id")).toContainText(`Endod ID given, not yet linked: ${claimed}`);
  await expect(page.getByTestId("endod-link-status")).toContainText("Not linked");
  await page.getByTestId("endod-claim").getByRole("button", { name: "Use this ID" }).click();
  await expect(page.getByLabel("Endod ID")).toHaveValue(claimed);
});

test("uploads stream through the portal and keep their size limit", async ({ page }) => {
  await as(page, "records");
  const upload = "/api/upload/imports/preview";
  const headers = { Origin: `http://localhost:${PORTAL_PORT}`, "X-Portal-Upload": "1" };
  // A multipart form is not how the portal uploads.
  let response = await page.request.post(upload, { headers, multipart: { file: { name: "x.csv", mimeType: "text/csv", buffer: Buffer.from("a") } } });
  expect(response.status()).toBe(415);
  // Over the limit: refused before anything reaches the backend.
  response = await page.request.post(upload, {
    headers: { ...headers, "Content-Type": "text/csv", "X-Filename": "big.csv" },
    data: Buffer.alloc(10 * 1024 * 1024 + 1, 0x61),
  });
  expect(response.status()).toBe(413);
  // Within it: streamed to the backend, which answers.
  response = await page.request.post(upload, {
    headers: { ...headers, "Content-Type": "text/csv", "X-Filename": "small.csv" },
    data: Buffer.from("name,date\nAlmaz,2025-01-01\n"),
  });
  expect(response.status()).toBe(400);
  expect((await response.json()).error).toContain("header");
});

test("yesterday's leftovers show on the queue page and are called first", async ({ page }) => {
  // doctor2 has a queue of their own, so earlier tests do not get in the way.
  const doctor = hospital.accounts.doctor2;
  seedQueueYesterday(hospital.hospital_id, doctor.email, "Lemlem Leftover");
  await as(page, "doctor2");
  await page.goto("/queue");
  const leftovers = page.getByTestId("queue-leftovers");
  await expect(leftovers).toContainText("From yesterday: 1 still open");
  await expect(leftovers.getByTestId("queue-entry")).toContainText("Lemlem Leftover");
  await page.getByRole("button", { name: "Call next" }).click();
  await expect(leftovers.getByTestId("queue-entry")).toContainText("called");
  await leftovers.getByRole("button", { name: "Done" }).click();
  await expect(page.getByTestId("queue-leftovers")).toHaveCount(0);
});
