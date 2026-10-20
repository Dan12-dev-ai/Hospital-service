import { expect, test } from "@playwright/test";
import { platform, uniqueTag } from "./helpers";

test("a hospital signs up, waits for Endod, and is approved", async ({ page, request }) => {
  const tag = uniqueTag("su");
  const hospitalName = `Selam ${tag} Hospital`;
  await page.goto("/signup");
  await page.getByLabel("Hospital name").fill(hospitalName);
  await page.getByLabel("Kind").selectOption("private");
  await page.getByLabel("City").fill("Bahir Dar");
  await page.getByLabel("Hospital phone (optional)").fill("058 220 0000");
  await page.getByLabel("Your full name").fill("Meron Admin");
  await page.getByLabel("Work email").fill(`admin@${tag}.example`);
  await page.getByLabel("Password", { exact: true }).fill("Signup-password-1");
  await page.getByLabel("Confirm password").fill("Signup-password-2");
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByTestId("form-error")).toHaveText("The two passwords do not match.");

  await page.getByLabel("Confirm password").fill("Signup-password-1");
  await page.getByRole("button", { name: "Sign up" }).click();

  // Signed in straight away, pending Endod's approval.
  const pending = page.getByTestId("signup-pending");
  await expect(pending).toContainText("Pending approval by Endod");
  await expect(pending).toContainText(hospitalName);

  // Every portal page says so while the hospital waits.
  await pending.getByRole("link", { name: "Go to the dashboard" }).click();
  const banner = page.getByTestId("hospital-status-banner");
  await expect(banner).toHaveAttribute("data-status", "pending");
  await expect(banner).toContainText("Pending approval by Endod");
  await page.goto("/doctors");
  await expect(page.getByTestId("hospital-status-banner")).toHaveAttribute("data-status", "pending");
  await page.goto("/settings");
  await expect(page.getByTestId("listing-status")).toContainText("Pending approval by Endod");

  // Endod approves it through the platform API.
  const hospitals = (await platform(request, "GET", "/platform/hospitals?status=pending")) as {
    id: string;
    name: string;
  }[];
  const mine = hospitals.find((h) => h.name === hospitalName);
  expect(mine).toBeDefined();
  const approved = await platform(request, "POST", `/platform/hospitals/${mine!.id}/approve`);
  expect(approved.status).toBe("approved");

  // Approved, but patients cannot see it until the listing is complete.
  await page.reload();
  const after = page.getByTestId("hospital-status-banner");
  await expect(after).toHaveAttribute("data-status", "unlisted");
  await expect(after).toContainText("an in-person visit price");
  await expect(after).toContainText("location");
});

test("Endod's platform endpoints are not reachable through the portal", async ({ page }) => {
  const response = await page.request.get("/api/platform/hospitals", {
    headers: { "X-Platform-Key": "e2e-platform-key" },
  });
  expect(response.status()).toBe(404);
});
