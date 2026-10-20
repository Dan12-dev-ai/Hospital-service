import { expect, test } from "@playwright/test";
import { seedHospital, signIn, uniqueTag, type SeededHospital } from "./helpers";

let hospital: SeededHospital;

test.beforeAll(() => {
  hospital = seedHospital("dir");
});

test("an admin adds a doctor and sets their duty status", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  await page.goto("/doctors");
  const rows = page.getByTestId("doctor-row");
  // The seeded doctors, from the API.
  await expect(rows.filter({ hasText: hospital.accounts.doctor.name })).toHaveCount(1);
  await expect(rows.filter({ hasText: hospital.accounts.doctor2.name })).toHaveCount(1);

  const email = `${uniqueTag("doc")}@dir.example`;
  await page.getByRole("button", { name: /Add Doctor/ }).click();
  const dialog = page.getByRole("dialog", { name: "Add doctor" });
  await dialog.getByLabel("Full name").fill("Dr. Yonas Bekele");
  await dialog.getByLabel("Email").fill(email);
  await dialog.getByRole("button", { name: "Add doctor" }).click();
  const done = page.getByRole("dialog", { name: "Doctor added" });
  await expect(done.getByTestId("temporary-password")).not.toBeEmpty();
  await done.getByRole("button", { name: "Done" }).click();

  const yonas = rows.filter({ hasText: "Dr. Yonas Bekele" });
  await expect(yonas.getByTestId("duty-status")).toHaveText("Off Duty");
  await yonas.getByRole("button", { name: "Set duty status of Dr. Yonas Bekele" }).click();
  const duty = page.getByRole("dialog", { name: /Duty status/ });
  await duty.getByLabel("Status").selectOption("on-duty");
  await duty.getByLabel("Where (optional)").fill("OPD Rm 204");
  await duty.getByRole("button", { name: "Save" }).click();
  await expect(yonas.getByTestId("duty-status")).toHaveText("On Duty • OPD Rm 204");

  // The tab counts and the search come from the API.
  await page.getByRole("button", { name: /^On Duty \(1\)$/ }).click();
  await expect(rows).toHaveCount(1);
  await page.getByRole("button", { name: /^All Doctors/ }).click();
  await page.getByPlaceholder(/Search by doctor name/).fill("Yonas");
  await expect(rows).toHaveCount(1);
});

test("a doctor can only change their own duty status", async ({ page }) => {
  await signIn(page, hospital.accounts.doctor.email, hospital.password);
  await page.goto("/doctors");
  const own = page.getByTestId("doctor-row").filter({ hasText: hospital.accounts.doctor.name });
  const other = page.getByTestId("doctor-row").filter({ hasText: hospital.accounts.doctor2.name });
  await expect(own.getByRole("button", { name: /Set duty status/ })).toBeVisible();
  await expect(other.getByRole("button", { name: /Set duty status/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Add Doctor/ })).toHaveCount(0);
});

test("reception registers a patient", async ({ page }) => {
  await signIn(page, hospital.accounts.reception.email, hospital.password);
  await page.goto("/patients");
  await expect(page.getByText("No patients registered yet")).toBeVisible();

  await page.getByRole("button", { name: /Register Patient/ }).click();
  const dialog = page.getByRole("dialog", { name: /Register New Patient/ });
  await dialog.getByLabel("Full name").fill("Almaz Tefera");
  await dialog.getByLabel("Birth", { exact: true }).selectOption("age");
  await dialog.getByLabel("Age (years)").fill("48");
  await dialog.getByLabel("Mobile").fill("0911 234 567");
  await dialog.getByRole("button", { name: "Complete Registration" }).click();

  const row = page.getByTestId("patient-row").filter({ hasText: "Almaz Tefera" });
  await expect(row).toContainText(/[A-Z0-9]+-000001/);
  await expect(row).toContainText("48y F");
  await expect(row).toContainText("Outpatient");

  // The same name and phone again needs a confirmation.
  await page.getByRole("button", { name: /Register Patient/ }).click();
  await dialog.getByLabel("Full name").fill("Almaz Tefera");
  await dialog.getByLabel("Mobile").fill("0911234567");
  await dialog.getByRole("button", { name: "Complete Registration" }).click();
  await expect(dialog.getByTestId("form-error")).toContainText("already registered");
  await expect(dialog.getByRole("button", { name: "Register anyway" })).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("patient-row")).toHaveCount(1);
});

test("clinical staff move a patient through care", async ({ page }) => {
  await signIn(page, hospital.accounts.nurse.email, hospital.password);
  await page.goto("/patients");
  const row = page.getByTestId("patient-row").filter({ hasText: "Almaz Tefera" });
  await row.getByLabel("Change status of Almaz Tefera").selectOption("emergency");
  await expect(row).toContainText("Emergency");
  await page.getByRole("button", { name: /^Emergency \(1\)$/ }).click();
  await expect(page.getByTestId("patient-row")).toHaveCount(1);
});
