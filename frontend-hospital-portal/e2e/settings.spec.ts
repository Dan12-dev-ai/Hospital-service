import { expect, test } from "@playwright/test";
import { seedHospital, signIn, type SeededHospital } from "./helpers";

let hospital: SeededHospital;

test.beforeAll(() => {
  // Approved by Endod, but without a price or a location yet.
  hospital = seedHospital("set", { unlisted: true });
});

test.use({ permissions: ["geolocation"], geolocation: { latitude: 8.9806, longitude: 38.7578 } });

test("an admin completes the listing, prices included", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  await page.goto("/settings");

  const status = page.getByTestId("listing-status");
  await expect(status).toContainText("Approved, not listed yet");
  await expect(page.getByTestId("missing-for-listing")).toContainText("an in-person visit price");
  await expect(page.getByTestId("missing-for-listing")).toContainText("location");

  await page.getByLabel("Name in Amharic").fill("ሰላም ሆስፒታል");
  await page.getByLabel("Kind").selectOption("public");
  await page.getByLabel("Address").fill("Bole Road, near Edna Mall");
  await page.getByLabel("Phone", { exact: true }).fill("011 551 7611");
  await page.getByLabel("Ambulance phone").fill("907");
  await page.getByLabel("Open hours").fill("Mon–Sat 8:00–17:00");
  await page.getByLabel("24-hour emergency department").check();
  await page.getByLabel("General medicine").check();
  await page.getByLabel("Pediatrics").check();

  // Location from the browser...
  await page.getByRole("button", { name: "Use my current location" }).click();
  await expect(page.getByLabel("Latitude")).toHaveValue("8.980600");
  await expect(page.getByLabel("Longitude")).toHaveValue("38.757800");
  await expect(page.getByTestId("location-note")).toContainText("Location found");
  // ...or typed by hand.
  await page.getByLabel("Latitude").fill("9.0105");
  await page.getByLabel("Longitude").fill("38.7612");

  // Video visits need a video price first.
  await page.getByLabel("Offer video visits").check();
  await page.getByLabel("In-person visit price (birr)").fill("150.50");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByTestId("form-error")).toHaveText("Set a video visit price before turning video visits on.");

  await page.getByLabel("Video visit price (birr)").fill("12.3456");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByTestId("form-error")).toContainText("Prices are in birr");

  await page.getByLabel("Video visit price (birr)").fill("99.9");
  await page.getByRole("button", { name: "Save settings" }).click();

  await expect(status).toContainText("Listed in the Endod app");
  await expect(page.getByTestId("missing-for-listing")).toHaveText("Nothing is missing for the listing.");
  await expect(page.getByTestId("hospital-status-banner")).toHaveCount(0);

  // Saved on the backend: birr in, santim stored, birr with two decimals back.
  const saved = await (await page.request.get("/api/hospital")).json();
  expect(saved).toMatchObject({
    price_in_person: "150.50",
    price_video: "99.90",
    video_enabled: true,
    emergency: true,
    kind: "public",
    latitude: 9.0105,
    longitude: 38.7612,
    phone: "011 551 7611",
    ambulance_phone: "907",
    services: ["general_medicine", "pediatrics"],
    listed: true,
    missing_for_listing: [],
  });

  await page.reload();
  await expect(page.getByLabel("In-person visit price (birr)")).toHaveValue("150.50");
  await expect(page.getByLabel("Video visit price (birr)")).toHaveValue("99.90");
  await expect(page.getByLabel("Address")).toHaveValue("Bole Road, near Edna Mall");
  await expect(page.getByLabel("Pediatrics")).toBeChecked();
});

test("the backend's validation errors are shown", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  await page.goto("/settings");
  await page.getByLabel("Ambulance phone").fill("call us!");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByTestId("form-error")).toContainText("ambulance_phone");
});

test("only admins see hospital settings", async ({ page }) => {
  await signIn(page, hospital.accounts.nurse.email, hospital.password);
  await page.goto("/");
  await expect(page.getByTestId("signed-in-email")).toHaveText(hospital.accounts.nurse.email);
  await expect(page.getByRole("link", { name: "Settings" })).toHaveCount(0);
  await page.goto("/settings");
  await expect(page.getByTestId("no-access")).toBeVisible();
  // And the backend refuses the change anyway.
  const response = await page.request.patch("/api/hospital", { data: { name: "Taken over" } });
  expect(response.status()).toBe(403);
});
