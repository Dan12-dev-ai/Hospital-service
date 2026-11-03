import { expect, test } from "@playwright/test";
import {
  enterCode,
  seedHospital,
  signIn,
  signInThroughForm,
  totpCode,
  totpFromSecret,
  type SeededHospital,
} from "./helpers";

let hospital: SeededHospital;

test.beforeAll(() => {
  hospital = seedHospital("auth");
});

test("signed-out visitors are sent to the sign-in page", async ({ page }) => {
  await page.goto("/keys");
  await expect(page).toHaveURL(/\/login\?next=%2Fkeys$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  // The BFF refuses portal API calls without a session.
  const response = await page.request.get("/api/hospital");
  expect(response.status()).toBe(401);
});

test("a wrong code is refused and nobody is signed out; the right one signs in", async ({ page }) => {
  await signInThroughForm(page, hospital.accounts.developer.email, hospital.password);
  await page.getByLabel("Authentication code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByTestId("form-error")).toContainText("That code is not valid");
  await page.getByLabel("Authentication code").fill(totpCode(hospital.accounts.developer.email));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByTestId("signed-in-name")).toHaveText(hospital.accounts.developer.name);
});

test("clinical roles are refused with a clear message", async ({ page }) => {
  await signInThroughForm(page, hospital.accounts.nurse.email, hospital.password);
  await expect(page.getByTestId("form-error")).toContainText("Only administrators and developers sign in");
  await expect(page).toHaveURL(/\/login/);
  const me = await page.request.get("/api/auth/me");
  expect(me.status()).toBe(401);
});

test("a wrong password is refused", async ({ page }) => {
  await signInThroughForm(page, hospital.accounts.admin.email, "Not-the-password-1");
  await expect(page.getByTestId("form-error")).toHaveText("Incorrect email or password.");
  await expect(page).toHaveURL(/\/login/);
});

test("sign in, then sign out from the sidebar", async ({ page, context }) => {
  await page.goto("/webhooks");
  await expect(page).toHaveURL(/\/login\?next=%2Fwebhooks/);
  await page.getByLabel("Email").fill(hospital.accounts.admin.email);
  await page.getByLabel("Password").fill(hospital.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Two-step verification: the code from the authenticator app.
  await expect(page.getByTestId("code-step")).toBeVisible();
  await enterCode(page, hospital.accounts.admin.email);

  // Back where the visitor was going.
  await expect(page).toHaveURL(/\/webhooks$/);
  await expect(page.getByTestId("signed-in-name")).toHaveText(hospital.accounts.admin.name);
  await expect(page.getByTestId("signed-in-email")).toContainText(hospital.accounts.admin.email);

  // The backend's token is in an httpOnly cookie the page cannot read.
  const cookie = (await context.cookies()).find((c) => c.name === "hp_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Lax");
  expect(await page.evaluate(() => document.cookie)).not.toContain("hp_session");
  const me = await page.request.get("/api/auth/me");
  expect(JSON.stringify(await me.json())).not.toContain("access_token");

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await context.cookies()).find((c) => c.name === "hp_session")).toBeUndefined();
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("a stale session is dropped and the visitor signs in again", async ({ page, context }) => {
  await signIn(page, hospital.accounts.developer.email, hospital.password);
  const cookie = (await context.cookies()).find((c) => c.name === "hp_session");
  expect(cookie).toBeDefined();
  // Sign out elsewhere (ends the session on the backend), keep the cookie here.
  await context.addCookies([{ ...cookie!, value: "no-longer-valid-token" }]);
  await page.goto("/logs");
  await expect(page).toHaveURL(/\/login\?next=%2Flogs/);
});

test("a temporary password must be changed before anything else", async ({ page }) => {
  await signInThroughForm(page, hospital.accounts.newdev.email, hospital.temporary_password);
  await expect(page).toHaveURL(/\/account\/password$/);
  await expect(page.getByTestId("must-change-password")).toBeVisible();

  // The rest of the dashboard sends them back here.
  await page.goto("/keys");
  await expect(page).toHaveURL(/\/account\/password$/);

  await page.getByLabel("Temporary password").fill(hospital.temporary_password);
  await page.getByLabel("New password", { exact: true }).fill("short");
  await page.getByLabel("Confirm new password").fill("short");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByTestId("form-error")).toContainText("at least 10 characters");

  await page.getByLabel("New password", { exact: true }).fill("My-own-password-9");
  await page.getByLabel("Confirm new password").fill("My-own-password-9");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByTestId("password-changed")).toBeVisible();
  await page.getByRole("link", { name: "Continue to the portal" }).click();

  // Then the authenticator app: a QR code (and the key as text), a first code, recovery codes.
  await expect(page).toHaveURL(/\/enroll$/);
  await expect(page.getByTestId("totp-qr")).toBeVisible();
  const secret = ((await page.getByTestId("totp-secret").textContent()) ?? "").replace(/\s/g, "");
  await page.getByLabel("Code from the app").fill("000000");
  await page.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByTestId("form-error")).toContainText("That code is not valid");
  await page.getByLabel("Code from the app").fill(totpFromSecret(secret));
  await page.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByTestId("recovery-code")).toHaveCount(10);
  const recovery = (await page.getByTestId("recovery-code").first().textContent()) ?? "";
  await page.getByLabel("I have saved my recovery codes").check();
  await page.getByRole("button", { name: "Continue to the portal" }).click();
  await expect(page.getByTestId("signed-in-name")).toHaveText(hospital.accounts.newdev.name);

  // The next sign-in asks for a code; a recovery code works once.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await signInThroughForm(page, hospital.accounts.newdev.email, "My-own-password-9");
  await page.getByRole("button", { name: "Use a recovery code" }).click();
  await page.getByLabel("Recovery code").fill(recovery);
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByTestId("signed-in-name")).toHaveText(hospital.accounts.newdev.name);
});

test("change password from the sidebar", async ({ page }) => {
  await signIn(page, hospital.accounts.developer.email, hospital.password);
  await page.goto("/");
  await page.getByRole("link", { name: "Change password" }).click();
  await expect(page).toHaveURL(/\/account\/password$/);
  await page.getByLabel("Current password").fill("Wrong-password-1");
  await page.getByLabel("New password", { exact: true }).fill("Developer-pass-22");
  await page.getByLabel("Confirm new password").fill("Developer-pass-22");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByTestId("form-error")).toHaveText("Current password is incorrect.");

  await page.getByLabel("Current password").fill(hospital.password);
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByTestId("password-changed")).toBeVisible();

  const again = await page.request.post("/api/auth/login", {
    data: { email: hospital.accounts.developer.email, password: "Developer-pass-22" },
  });
  expect(again.status()).toBe(200);
});

for (const next of ["/%09/evil.example", "//evil.example", "/%5Cevil.example", "https://evil.example"]) {
  test(`after sign-in, never leaves the dashboard (next=${next})`, async ({ page }) => {
    await page.goto(`/login?next=${next}`);
    await page.getByLabel("Email").fill(hospital.accounts.admin.email);
    await page.getByLabel("Password").fill(hospital.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await enterCode(page, hospital.accounts.admin.email);
    await expect(page.getByTestId("signed-in-name")).toBeVisible();
    expect(new URL(page.url()).host).toBe(new URL(test.info().project.use.baseURL ?? "http://localhost").host);
  });
}
