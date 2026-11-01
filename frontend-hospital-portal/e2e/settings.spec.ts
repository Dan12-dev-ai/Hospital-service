import { expect, test } from "@playwright/test";
import { chooseOption, seedHospital, signIn, type SeededHospital } from "./helpers";

let hospital: SeededHospital;

test.beforeAll(() => {
  // Approved by Endod, but without a price or a location yet.
  hospital = seedHospital("set", { unlisted: true });
});

test.use({ permissions: ["geolocation"], geolocation: { latitude: 8.9806, longitude: 38.7578 } });

test("an admin completes the listing, prices included", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  // Opening the portal sends an admin of an unlisted hospital to Settings, once,
  // with the price field focused and what is missing at the top.
  await page.goto("/");
  await expect(page).toHaveURL(/\/settings\?focus=price_in_person$/);
  await expect(page.getByLabel("In-person visit price (birr)")).toBeFocused();

  const status = page.getByTestId("listing-status");
  await expect(status).toContainText("Approved, not listed yet");
  await expect(page.getByTestId("listing-explainer")).toContainText(
    `Patients can't find ${hospital.name} in the Endod app until you set the in-person visit price`
  );
  await expect(page.getByTestId("missing-for-listing")).toContainText("The in-person visit price");
  await expect(page.getByTestId("missing-for-listing")).toContainText("location");
  await expect(page.getByTestId("hospital-status-banner")).toHaveCount(0); // Settings says it itself
  // The missing fields are highlighted; 0 is a valid price.
  await expect(page.locator('section[data-needed="true"]')).toHaveCount(2);
  await expect(page.getByText("0 is allowed")).toBeVisible();

  // Once only: the dashboard now shows the call to action instead.
  await page.goto("/");
  await expect(page).toHaveURL(/\/$/);
  const banner = page.getByTestId("hospital-status-banner");
  await expect(banner).toHaveAttribute("data-status", "unlisted");
  await expect(banner).toContainText(`Patients can't find ${hospital.name} yet`);
  await banner.getByRole("link", { name: "Fix it in Settings" }).click();
  await expect(page).toHaveURL(/\/settings\?focus=price_in_person$/);

  await page.getByLabel("Name in Amharic").fill("ሰላም ሆስፒታል");
  await chooseOption(page.getByRole("combobox", { name: "Kind" }), "Public");
  await page.getByLabel("Address").fill("Bole Road, near Edna Mall");
  await page.getByLabel("Phone", { exact: true }).fill("011 551 7611");
  await page.getByLabel("Ambulance phone").fill("907");
  // Opening hours: days and times, not free text.
  await page.getByRole("button", { name: "Add opening hours" }).click();
  await chooseOption(page.getByRole("combobox", { name: "To", exact: true }), "Saturday");
  await page.getByLabel("Opens at", { exact: true }).fill("08:00");
  await page.getByLabel("Closes at", { exact: true }).fill("08:00");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByTestId("form-error")).toContainText("the closing time must differ");
  await page.getByLabel("Closes at", { exact: true }).fill("17:00");
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
    open_hours: "Mon-Sat 08:00-17:00",
    listed: true,
    missing_for_listing: [],
  });

  await page.reload();
  await expect(page.getByLabel("In-person visit price (birr)")).toHaveValue("150.50");
  await expect(page.getByLabel("Video visit price (birr)")).toHaveValue("99.90");
  await expect(page.getByLabel("Address")).toHaveValue("Bole Road, near Edna Mall");
  await expect(page.getByLabel("Pediatrics")).toBeChecked();
  await expect(page.getByLabel("Opens at", { exact: true })).toHaveValue("08:00");

  // Open around the clock instead.
  await page.getByLabel("Open 24 hours, 7 days a week").check();
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByTestId("form-error")).toHaveCount(0);
  await expect.poll(async () => (await (await page.request.get("/api/hospital")).json()).open_hours).toBe("24/7");
});

test("staff who are not admins are told who can list the hospital", async ({ page }) => {
  const other = seedHospital("ask", { unlisted: true });
  await signIn(page, other.accounts.nurse.email, other.password);
  await page.goto("/");
  await expect(page).toHaveURL(/\/$/); // only admins are sent to Settings
  const banner = page.getByTestId("hospital-status-banner");
  await expect(banner).toContainText(`Patients can't find ${other.name} yet`);
  await expect(banner.getByTestId("ask-admin")).toHaveText("Ask your hospital's admin to set this in Settings.");
  await expect(banner.getByRole("link")).toHaveCount(0);
});

test("a free visit (price 0) lists the hospital; nonsense hours are refused", async ({ page }) => {
  const other = seedHospital("free", { unlisted: true });
  await signIn(page, other.accounts.admin.email, other.password);
  const refused = await page.request.patch("/api/hospital", { data: { open_hours: "100:00" } });
  expect(refused.status()).toBe(422);
  expect((await refused.json()).error).toContain("is not a period of opening hours");

  await page.goto("/settings");
  await page.getByLabel("Latitude").fill("9.0105");
  await page.getByLabel("Longitude").fill("38.7612");
  await page.getByLabel("In-person visit price (birr)").fill("0");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByTestId("listing-status")).toContainText("Listed in the Endod app");
  expect((await (await page.request.get("/api/hospital")).json()).price_in_person).toBe("0.00");
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
