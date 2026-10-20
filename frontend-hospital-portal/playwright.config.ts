import path from "node:path";
import { defineConfig } from "@playwright/test";

import {
  BACKEND_PORT,
  BACKEND_URL,
  PORTAL_PORT,
  backendDir,
  backendEnv,
  python,
} from "./e2e/env";

// Browser tests run the real stack: the hospital service (uvicorn, a
// throwaway SQLite database) and the portal built with `next build`, served
// by `next start` and pointed at it. Set E2E_NEXT_DEV=1 to use `next dev`
// instead (no build needed).

export default defineConfig({
  testDir: "e2e",
  timeout: 45_000,
  expect: { timeout: 15_000 },
  // The specs share one backend (and its sign-up rate limit): run them in order.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://localhost:${PORTAL_PORT}`,
    headless: true,
    viewport: { width: 1440, height: 900 },
    // The system Google Chrome (`chrome` channel): no browser download.
    channel: "chrome",
    launchOptions: { args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"] },
    trace: "retain-on-failure",
    actionTimeout: 10_000,
  },
  webServer: [
    {
      command: `"${python}" "${path.join(__dirname, "e2e", "backend.py")}" ${BACKEND_PORT}`,
      cwd: backendDir,
      url: `${BACKEND_URL}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: backendEnv,
    },
    {
      command: process.env.E2E_NEXT_DEV
        ? `npm run dev -- -p ${PORTAL_PORT}`
        : `npm run start -- -p ${PORTAL_PORT}`,
      url: `http://localhost:${PORTAL_PORT}/login`,
      reuseExistingServer: false,
      timeout: 180_000,
      env: { HOSPITAL_API_URL: BACKEND_URL },
    },
  ],
});
