import { expect, test, type Page } from "@playwright/test";
import { JITSI_DOMAIN } from "./env";
import { bookingRow, chooseOption, seedBooking, seedHospital, signIn, type SeededHospital } from "./helpers";

let hospital: SeededHospital;

test.beforeAll(() => {
  hospital = seedHospital("bk");
});

/** Stands in for Jitsi's external_api.js: records what the portal passed it. */
const JITSI_STUB = `
window.JitsiMeetExternalAPI = function (domain, options) {
  window.__jitsi = { domain: domain, roomName: options.roomName, jwt: options.jwt };
  var stub = document.createElement("div");
  stub.setAttribute("data-testid", "jitsi-stub");
  stub.textContent = "Jitsi room " + options.roomName;
  options.parentNode.appendChild(stub);
  this.dispose = function () {};
};`;

async function openBookings(page: Page, email: string) {
  await signIn(page, email, hospital.password);
  await page.goto("/appointments");
  await expect(page.getByRole("heading", { name: /Patient Booking/ })).toBeVisible();
}

test("a doctor approves a video visit and joins it", async ({ page }) => {
  seedBooking(hospital.hospital_id, "video", 10, "Abebe Video");
  await openBookings(page, hospital.accounts.doctor.email);

  const row = bookingRow(page, "Abebe Video");
  await expect(row.getByTestId("booking-status")).toHaveText("Awaiting doctor");
  await expect(row).toContainText("Video visit");
  await expect(row).toContainText("ETB 120.00");
  await row.getByRole("button", { name: "Approve" }).click();
  await expect(row.getByTestId("booking-status")).toHaveText("Confirmed");
  await expect(row).toContainText(hospital.accounts.doctor.name);

  let scriptRequested = false;
  await page.route(`https://${JITSI_DOMAIN}/external_api.js`, async (route) => {
    scriptRequested = true;
    await route.fulfill({ contentType: "application/javascript", body: JITSI_STUB });
  });
  await row.getByRole("link", { name: "Join video" }).click();
  await expect(page).toHaveURL(/\/visit\/[0-9a-f]+$/);
  await expect(page.getByRole("heading", { name: "Abebe Video" })).toBeVisible();
  await expect(page.getByTestId("jitsi-stub")).toContainText("Jitsi room endod-");
  expect(scriptRequested).toBe(true);

  const jitsi = await page.evaluate(
    () => (window as unknown as { __jitsi: { domain: string; roomName: string; jwt: string } }).__jitsi
  );
  expect(jitsi.domain).toBe(JITSI_DOMAIN);
  // The doctor joins as the call's moderator, for this room only.
  const claims = JSON.parse(Buffer.from(jitsi.jwt.split(".")[1], "base64url").toString("utf-8"));
  expect(claims.room).toBe(jitsi.roomName);
  expect(claims.moderator).toBe(true);
  expect(claims.context.user.name).toBe(hospital.accounts.doctor.name);
});

test("a doctor rejects a video visit with a reason", async ({ page }) => {
  seedBooking(hospital.hospital_id, "video", 90, "Kidist Reject");
  await openBookings(page, hospital.accounts.doctor.email);

  const row = bookingRow(page, "Kidist Reject");
  await row.getByRole("button", { name: "Reject" }).click();
  const dialog = page.getByRole("dialog", { name: "Reject booking" });
  await dialog.getByRole("button", { name: "Reject booking" }).click();
  await expect(dialog.getByTestId("form-error")).toContainText("Give the patient a reason");
  await dialog.getByLabel("Reason").fill("No doctor is available at that time.");
  await dialog.getByRole("button", { name: "Reject booking" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row.getByTestId("booking-status")).toHaveText("Rejected");
  await expect(row.getByTestId("booking-reason")).toHaveText("Reason: No doctor is available at that time.");

  // The status filter finds it.
  await page.getByTestId("status-tab-rejected").click();
  await expect(bookingRow(page, "Kidist Reject")).toHaveCount(1);
  await expect(page.getByTestId("booking-row").filter({ hasText: "Abebe Video" })).toHaveCount(0);
});

test("an admin approves on behalf of a chosen doctor", async ({ page }) => {
  seedBooking(hospital.hospital_id, "video", 120, "Tigist Admin");
  await openBookings(page, hospital.accounts.admin.email);

  const row = bookingRow(page, "Tigist Admin");
  await row.getByRole("button", { name: "Approve" }).click();
  const dialog = page.getByRole("dialog", { name: "Approve video visit" });
  await chooseOption(dialog.getByRole("combobox", { name: "Doctor" }), hospital.accounts.doctor2.name);
  await dialog.getByRole("button", { name: "Approve" }).click();
  await expect(row.getByTestId("booking-status")).toHaveText("Confirmed");
  await expect(row).toContainText(hospital.accounts.doctor2.name);
  // An admin is not the visit's doctor: no joining.
  await expect(row.getByText("Join video")).toHaveCount(0);
});

test("reception cancels in-person visits but not video ones", async ({ page }) => {
  seedBooking(hospital.hospital_id, "in_person", 60, "Dawit Walkin");
  seedBooking(hospital.hospital_id, "video", 150, "Hana Waiting");
  await openBookings(page, hospital.accounts.reception.email);

  // In-person visits are confirmed on arrival.
  const inPerson = bookingRow(page, "Dawit Walkin");
  await expect(inPerson.getByTestId("booking-status")).toHaveText("Confirmed");
  // Approving or rejecting a video visit is a doctor's decision.
  const waiting = bookingRow(page, "Hana Waiting");
  await expect(waiting.getByTestId("booking-status")).toHaveText("Awaiting doctor");
  await expect(waiting.getByRole("button")).toHaveCount(0);
  // A confirmed video visit is cancelled by its doctor or an admin.
  await expect(bookingRow(page, "Tigist Admin").getByRole("button", { name: "Cancel" })).toHaveCount(0);

  await inPerson.getByRole("button", { name: "Cancel" }).click();
  const dialog = page.getByRole("dialog", { name: "Cancel booking" });
  await dialog.getByLabel("Reason").fill("The clinic is closed for a holiday.");
  await dialog.getByRole("button", { name: "Cancel booking" }).click();
  await expect(inPerson.getByTestId("booking-status")).toHaveText("Cancelled");

  // The backend agrees: reception cannot approve.
  const booking = await (await page.request.get("/api/bookings?status=awaiting_doctor")).json();
  const id = (booking.items as { id: string; patient: { name: string } }[]).find(
    (b) => b.patient.name === "Hana Waiting"
  )!.id;
  const refused = await page.request.post(`/api/bookings/${id}/approve`, { data: {} });
  expect(refused.status()).toBe(403);
});

test("a nurse completes a visit that has started", async ({ page }) => {
  seedBooking(hospital.hospital_id, "in_person", -20, "Selam Complete");
  await openBookings(page, hospital.accounts.nurse.email);

  const row = bookingRow(page, "Selam Complete");
  await expect(row.getByRole("button", { name: "Cancel" })).toHaveCount(0);
  await row.getByRole("button", { name: "Complete" }).click();
  await expect(row.getByTestId("booking-status")).toHaveText("Completed");
  // Nurses neither approve nor reject.
  await expect(bookingRow(page, "Hana Waiting").getByRole("button")).toHaveCount(0);
});

test("only the visit's doctor joins the video room", async ({ page }) => {
  // Approved by the admin for doctor2 in an earlier test; doctor (the other one) sees no join.
  await openBookings(page, hospital.accounts.doctor.email);
  await expect(bookingRow(page, "Tigist Admin").getByText("Join video")).toHaveCount(0);

  const list = await (await page.request.get("/api/bookings?status=confirmed&mode=video")).json();
  const theirs = (list.items as { id: string; patient: { name: string } }[]).find(
    (b) => b.patient.name === "Tigist Admin"
  )!;
  await page.goto(`/visit/${theirs.id}`);
  await expect(page.getByTestId("error-state")).toContainText("Booking not found.");

  // Staff who are not doctors are not offered the page at all.
  await signIn(page, hospital.accounts.reception.email, hospital.password);
  await page.goto(`/visit/${theirs.id}`);
  await expect(page.getByTestId("no-access")).toBeVisible();
});

test("staff without access to bookings do not see them", async ({ page }) => {
  await signIn(page, hospital.accounts.billing.email, hospital.password);
  await page.goto("/");
  await expect(page.getByTestId("signed-in-email")).toHaveText(hospital.accounts.billing.email);
  const nav = page.getByRole("navigation");
  await expect(nav.getByRole("link", { name: "Patients" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Patient Booking" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Settings" })).toHaveCount(0);
  await page.goto("/appointments");
  await expect(page.getByTestId("no-access")).toBeVisible();
  expect((await page.request.get("/api/bookings")).status()).toBe(403);
});

test("the dashboard shows real counts and flags visits awaiting a doctor", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  await page.goto("/");
  const banner = page.getByTestId("awaiting-banner");
  await expect(banner).toContainText("awaits a doctor");
  await expect(banner).toContainText("Hana Waiting");

  const counts = (await (await page.request.get("/api/bookings")).json()).counts as Record<string, number>;
  const open = counts.awaiting_doctor + counts.confirmed;
  const card = page.locator('[data-testid="kpi-card"][data-label="Open Bookings"]');
  await expect(card).toContainText(String(open));
  await expect(card).toContainText(`${counts.awaiting_doctor} awaiting a doctor`);
  // Billing has no backend yet: its card is marked as sample data.
  await expect(page.locator('[data-testid="kpi-card"][data-label="Invoices"]').getByTestId("sample-badge")).toBeVisible();

  await banner.getByRole("link", { name: "Review" }).click();
  await expect(page).toHaveURL(/\/appointments\?status=awaiting_doctor$/);
  await expect(page.getByTestId("status-tab-awaiting_doctor")).toHaveAttribute("aria-selected", "true");
  await expect(bookingRow(page, "Hana Waiting")).toHaveCount(1);
});
