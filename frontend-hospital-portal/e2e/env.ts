import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/** Settings shared by playwright.config.ts and the specs. */

export const BACKEND_PORT = 8120;
export const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
export const PORTAL_PORT = 3210;
export const PLATFORM_KEY = "e2e-platform-key";
export const JITSI_DOMAIN = "meet.e2e.example";

// The backend's Python: E2E_PYTHON (CI), else the repo's virtualenv.
export const python =
  process.env.E2E_PYTHON ??
  path.join(__dirname, "..", "..", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
export const backendDir = path.join(__dirname, "..", "..", "backend-hospital");

// A fresh database per run. Set once in the main process (which also clears
// earlier runs' files); test workers inherit it, so they use the same one.
if (!process.env.E2E_DB) {
  for (const name of fs.readdirSync(os.tmpdir())) {
    if (name.startsWith("hospital-e2e-")) fs.rmSync(path.join(os.tmpdir(), name), { force: true });
  }
  process.env.E2E_DB = path.join(os.tmpdir(), `hospital-e2e-${Date.now()}.db`).replace(/\\/g, "/");
}
export const E2E_DATABASE_URL = `sqlite:///${process.env.E2E_DB}`;

/** The backend's settings for the run (the seed script runs with them too). */
export const backendEnv: Record<string, string> = {
  HOSPITAL_ENVIRONMENT: "development",
  HOSPITAL_DATABASE_URL: E2E_DATABASE_URL,
  HOSPITAL_SIGNUP_ENABLED: "true",
  HOSPITAL_PLATFORM_ADMIN_KEY: PLATFORM_KEY,
  HOSPITAL_JITSI_DOMAIN: JITSI_DOMAIN,
  HOSPITAL_JITSI_APP_SECRET: "e2e-jitsi-secret",
  HOSPITAL_CORS_ORIGINS: `http://localhost:${PORTAL_PORT}`,
};

