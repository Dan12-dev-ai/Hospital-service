import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import path from "node:path";
import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";
import { BACKEND_URL, PLATFORM_KEY, backendDir, backendEnv, python } from "./env";

export type Account = { email: string; name: string };
export type SeededHospital = {
  hospital_id: string;
  name: string;
  password: string;
  temporary_password: string;
  /** An administrator, a developer, a nurse (refused at sign-in) and "newdev" (a temporary password). */
  accounts: Record<"admin" | "developer" | "nurse" | "newdev", Account>;
};

function seed<T>(...args: string[]): T {
  const out = execFileSync(python, [path.join(__dirname, "seed.py"), ...args], {
    cwd: backendDir,
    env: { ...process.env, ...backendEnv },
    encoding: "utf-8",
  });
  return JSON.parse(out.trim().split("\n").pop() ?? "") as T;
}

let counter = 0;
/** A unique short tag per seeded hospital (also its code). */
export function uniqueTag(prefix: string): string {
  counter += 1;
  return `${prefix}${Date.now().toString(36).slice(-4)}${counter}`.toLowerCase();
}

/** An approved hospital with an administrator, a developer and a nurse. */
export function seedHospital(prefix: string, options: { unlisted?: boolean } = {}): SeededHospital {
  return seed<SeededHospital>("hospital", uniqueTag(prefix), ...(options.unlisted ? ["--unlisted"] : []));
}

/** A price list, as the hospital's system would sync it. */
export function seedPrices(hospitalId: string) {
  return seed<{ items: number }>("prices", hospitalId);
}

export type SeededApplicant = { hospital_id: string; name: string; email: string; password: string; demo_at: string | null };

/**
 * A hospital applying to join Endod (pending). `complete`: every step done
 * but the demo; `submitted`: the demo booked and the application submitted.
 */
export function seedApplicant(
  prefix: string,
  stage: "draft" | "complete" | "submitted" = "draft",
  options: { noPrice?: boolean; demo?: boolean } = {}
): SeededApplicant {
  const flags = stage === "complete" ? ["--complete"] : stage === "submitted" ? ["--submitted"] : [];
  if (options.noPrice) flags.push("--no-price");
  if (options.demo) flags.push("--demo");
  return seed<SeededApplicant>("applicant", uniqueTag(prefix), ...flags);
}

/** Another staff member of an applying hospital, who must change a temporary password. */
export function seedApplicantStaff(hospitalId: string, email: string, role: "admin" | "developer") {
  return seed<{ id: string; email: string; temporary_password: string }>("applicant-staff", hospitalId, email, role);
}

/** A code from the account's authenticator app (never one used before). */
export function totpCode(email: string): string {
  return seed<{ code: string }>("totp-code", email).code;
}

/** A TOTP code (RFC 6238: SHA-1, 30 s, 6 digits) from a base32 secret, as an authenticator app makes it. */
export function totpFromSecret(secret: string, at: number = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret.replace(/[\s=]/g, "").toUpperCase()) bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((byte) => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const value = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return value.toString().padStart(6, "0");
}

/**
 * Signs in through the dashboard's own API, so the page gets the session
 * cookie: the password, then the code from the authenticator (or, the
 * first time, setting the authenticator up).
 */
export async function signIn(page: Page, email: string, password: string) {
  const response = await page.request.post("/api/auth/login", { data: { email, password } });
  expect(response.status(), await response.text()).toBe(200);
  const { stage, staff } = (await response.json()) as { stage: string; staff: { must_change_password: boolean } };
  if (stage === "totp") {
    const code = await page.request.post("/api/auth/totp", { data: { code: totpCode(email) } });
    expect(code.status(), await code.text()).toBe(200);
  } else if (stage === "enroll" && !staff.must_change_password) {
    const started = await page.request.post("/api/auth/enroll/start", { data: {} });
    expect(started.status(), await started.text()).toBe(200);
    const { secret } = (await started.json()) as { secret: string };
    const done = await page.request.post("/api/auth/enroll/confirm", { data: { code: totpFromSecret(secret) } });
    expect(done.status(), await done.text()).toBe(200);
  }
}

/** The code step of the sign-in form, with a code from the account's authenticator. */
export async function enterCode(page: Page, email: string) {
  await page.getByLabel("Authentication code").fill(totpCode(email));
  await page.getByRole("button", { name: "Verify" }).click();
}

export async function signInThroughForm(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** A fresh code from the authenticator in the "Confirm it's you" dialog, then the action's button. */
export async function confirmWithCode(page: Page, email: string, button: string) {
  const confirm = page.getByTestId("confirm-code");
  await expect(confirm).toBeVisible();
  await confirm.getByLabel("Confirm it's you: enter the code from your authenticator app").fill(totpCode(email));
  await confirm.getByRole("button", { name: button }).click();
}

/** Endod's platform API (not reachable through the dashboard). */
export async function platform(request: APIRequestContext, method: "GET" | "POST", pathname: string, data?: unknown) {
  const response = await request.fetch(`${BACKEND_URL}${pathname}`, {
    method,
    headers: { "X-Platform-Key": PLATFORM_KEY },
    ...(data === undefined ? {} : { data }),
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

/**
 * Picks an option in one of the dashboard's selects (Base UI comboboxes, not
 * native <select>s): opens the combobox by its role, then clicks the option
 * by its accessible name. A string matches the whole name.
 */
export async function chooseOption(combobox: Locator, option: string | RegExp) {
  const page = combobox.page();
  await combobox.click();
  await page.getByRole("option", { name: option, exact: typeof option === "string" }).click();
  await expect(page.getByRole("option")).toHaveCount(0);
}
