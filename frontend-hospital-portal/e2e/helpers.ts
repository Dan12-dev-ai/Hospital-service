import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { BACKEND_URL, PLATFORM_KEY, backendDir, backendEnv, python } from "./env";

export type Account = { email: string; name: string };
export type SeededHospital = {
  hospital_id: string;
  name: string;
  password: string;
  temporary_password: string;
  accounts: Record<"admin" | "doctor" | "doctor2" | "nurse" | "reception" | "billing" | "newdoc", Account>;
};
export type SeededBooking = { id: string; status: string; dedan_id: string };

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

/** An approved hospital with one staff account per role. */
export function seedHospital(prefix: string, options: { unlisted?: boolean } = {}): SeededHospital {
  return seed<SeededHospital>("hospital", uniqueTag(prefix), ...(options.unlisted ? ["--unlisted"] : []));
}

/** A booking arriving from the Endod app, as the event worker would store it. */
export function seedBooking(
  hospitalId: string,
  mode: "video" | "in_person",
  minutesFromNow: number,
  patientName: string
): SeededBooking {
  return seed<SeededBooking>("booking", hospitalId, mode, String(minutesFromNow), patientName);
}

/** Signs in through the portal's own API, so the page gets the session cookie. */
export async function signIn(page: Page, email: string, password: string) {
  const response = await page.request.post("/api/auth/login", { data: { email, password } });
  expect(response.status(), await response.text()).toBe(200);
}

export async function signInThroughForm(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** Endod's platform API (not reachable through the portal). */
export async function platform(request: APIRequestContext, method: "GET" | "POST", pathname: string) {
  const response = await request.fetch(`${BACKEND_URL}${pathname}`, {
    method,
    headers: { "X-Platform-Key": PLATFORM_KEY },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

export function bookingRow(page: Page, patientName: string) {
  return page.getByTestId("booking-row").filter({ hasText: patientName });
}
