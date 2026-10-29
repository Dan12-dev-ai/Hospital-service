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
  accounts: Record<"admin" | "doctor" | "doctor2" | "nurse" | "reception" | "billing" | "records" | "newdoc", Account>;
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

export type SeededApplicant = { hospital_id: string; name: string; email: string; password: string; demo_at: string | null };

/**
 * A hospital applying to join Endod (pending). `complete`: every step done
 * but the demo; `submitted`: the demo booked and the application submitted.
 */
export function seedApplicant(prefix: string, stage: "draft" | "complete" | "submitted" = "draft"): SeededApplicant {
  const flags = stage === "complete" ? ["--complete"] : stage === "submitted" ? ["--submitted"] : [];
  return seed<SeededApplicant>("applicant", uniqueTag(prefix), ...flags);
}

/** Another staff member of an applying hospital, who must change a temporary password. */
export function seedApplicantStaff(hospitalId: string, email: string, role: "admin" | "nurse") {
  return seed<{ id: string; email: string; temporary_password: string }>("applicant-staff", hospitalId, email, role);
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

/** Endod answering the patient's pending link request (patient.linked / patient.link_refused). */
export function seedLinkReply(patientId: string, answer: "linked" | "refused", reason?: string) {
  return seed<{ request_id: string; dedan_id: string }>("link-reply", patientId, answer, ...(reason ? [reason] : []));
}

/** The patient already linked to Endod. */
export function seedLink(patientId: string, dedanId: string) {
  return seed<{ patient_id: string; dedan_id: string }>("link", patientId, dedanId);
}

/** A walk-in checked in to the doctor's queue yesterday (hospital time), still waiting. */
export function seedQueueYesterday(hospitalId: string, doctorEmail: string, patientName: string) {
  return seed<{ entry_id: string; ticket: number; day: string }>("queue-yesterday", hospitalId, doctorEmail, patientName);
}

/** A patient sharing one record (with a PDF) with the hospital through Endod. */
export function seedShare(hospitalId: string, dedanId: string, patientName: string, title: string) {
  return seed<{ share_id: string; record_id: string; file_id: string }>("share", hospitalId, dedanId, patientName, title);
}

export type SeededDispenseItem = {
  item_index: number;
  amount: number | null;
  complete: boolean;
  given_total: number | null;
  status: "not_given" | "partly_given" | "given";
};

/** A pharmacy giving medicine from a prescription record through Endod (prescription.dispensed). */
export function seedDispense(
  recordId: string,
  pharmacy: string,
  at: string,
  status: "open" | "completed",
  items: SeededDispenseItem[]
) {
  return seed<{ dispense_id: string }>("dispense", recordId, pharmacy, at, status, JSON.stringify(items));
}

/** Registers a patient through the portal (the page must be signed in as a registrar). */
export async function registerPatient(page: Page, name: string, phone = "0911 234 567") {
  const response = await page.request.post("/api/patients", {
    data: { full_name: name, sex: "female", age_years: 34, phone, confirm_duplicate: true },
  });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as { id: string; mrn: string; full_name: string };
}

/** A fresh Endod ID (DE + 6 digits). */
export function newDedanId(): string {
  return `DE${String(Math.floor(Math.random() * 1_000_000)).padStart(6, "0")}`;
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
 * Signs in through the portal's own API, so the page gets the session
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

/** Endod's platform API (not reachable through the portal). */
export async function platform(request: APIRequestContext, method: "GET" | "POST", pathname: string, data?: unknown) {
  const response = await request.fetch(`${BACKEND_URL}${pathname}`, {
    method,
    headers: { "X-Platform-Key": PLATFORM_KEY },
    ...(data === undefined ? {} : { data }),
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

export function bookingRow(page: Page, patientName: string) {
  return page.getByTestId("booking-row").filter({ hasText: patientName });
}

/**
 * Picks an option in one of the portal's selects (Base UI comboboxes, not
 * native <select>s): opens the combobox by its role, then clicks the option
 * by its accessible name. A string matches the whole name.
 */
export async function chooseOption(combobox: Locator, option: string | RegExp) {
  const page = combobox.page();
  await combobox.click();
  await page.getByRole("option", { name: option, exact: typeof option === "string" }).click();
  await expect(page.getByRole("option")).toHaveCount(0);
}
