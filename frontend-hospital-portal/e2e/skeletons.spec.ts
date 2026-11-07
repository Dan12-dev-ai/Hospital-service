import { expect, test, type Locator, type Page } from "@playwright/test";
import { seedApplicant, seedHospital, signIn, type SeededHospital } from "./helpers";

// While data loads (a first visit, a reload, a section change), the dashboard
// and the onboarding pages show a skeleton of what is coming (grey blocks
// shaped like the page), never a spinner. Screen readers hear "Loading".

test.describe.configure({ timeout: 90_000 });

let hospital: SeededHospital;

test.beforeAll(() => {
  hospital = seedHospital("skel");
});

/** Holds every request matching `pattern` until the returned function is called (a slow server). */
async function hold(page: Page, pattern: string): Promise<() => Promise<void>> {
  let release!: () => void;
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(pattern, async (route) => {
    await released;
    await route.continue().catch(() => undefined);
  });
  return async () => {
    release();
    await page.unroute(pattern);
  };
}

async function expectSkeleton(page: Page, skeleton: Locator, label: string | RegExp) {
  await expect(skeleton).toBeVisible();
  await expect(skeleton).toHaveAttribute("role", "status");
  await expect(skeleton).toHaveAttribute("aria-busy", "true");
  // One visually hidden "Loading" for screen readers; the blocks are hidden from them.
  await expect(skeleton.locator(".sr-only")).toHaveText(label);
  await expect(skeleton.locator("[data-skeleton-block]").first()).toBeVisible();
  expect(await skeleton.locator("[data-skeleton-block]").count()).toBeGreaterThan(3);
  // No spinner anywhere.
  await expect(page.locator(".animate-spin")).toHaveCount(0);
}

test("the dashboard shows the page's shape while the session loads", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  for (const [path, heading] of [
    ["/settings", "Settings"],
    ["/", "Overview"],
    ["/team", "Team"],
  ] as const) {
    const release = await hold(page, "**/api/auth/me");
    await page.goto(path);
    const skeleton = page.getByTestId("page-skeleton");
    await expectSkeleton(page, skeleton, "Loading…");
    await expect(page.getByRole("heading", { name: heading, exact: true })).toHaveCount(0);
    await release();
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await expect(skeleton).toHaveCount(0);
  }
});

test("a section that loads its own data shows its skeleton under the page header", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);

  // API keys: the list of keys.
  let release = await hold(page, "**/api/connections");
  await page.goto("/keys");
  await expect(page.getByRole("heading", { name: "API keys" })).toBeVisible();
  await expectSkeleton(page, page.getByTestId("skeleton"), "Loading your keys…");
  await release();
  await expect(page.getByText("No API keys yet")).toBeVisible();
  await expect(page.getByTestId("skeleton")).toHaveCount(0);

  // Logs and Webhooks: the key picker and the panels.
  for (const [path, heading] of [
    ["/logs", "Logs"],
    ["/webhooks", "Webhooks"],
  ] as const) {
    release = await hold(page, "**/api/connections");
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expectSkeleton(page, page.getByTestId("skeleton"), "Loading your keys…");
    await release();
    await expect(page.getByTestId("skeleton")).toHaveCount(0);
  }

  // Docs: the section list and the page.
  release = await hold(page, "**/api/developer/guide");
  await page.goto("/docs");
  await expectSkeleton(page, page.getByTestId("skeleton"), "Loading the docs…");
  await release();
  await expect(page.getByTestId("docs-nav")).toBeVisible();

  // Settings: the price list under the form.
  release = await hold(page, "**/api/prices");
  await page.goto("/settings");
  await expect(page.getByTestId("settings-form")).toBeVisible();
  await expectSkeleton(page, page.getByTestId("price-list").getByTestId("skeleton"), "Loading the price list…");
  await release();
  await expect(page.getByTestId("prices-lab_tests")).toBeVisible();
});

test("the shimmer stops for people who ask for less motion", async ({ page }) => {
  await signIn(page, hospital.accounts.admin.email, hospital.password);
  const shimmer = (block: Locator) => block.evaluate((el) => getComputedStyle(el, "::after").animationName);

  let release = await hold(page, "**/api/connections");
  await page.goto("/keys");
  const block = page.getByTestId("skeleton").locator("[data-skeleton-block]").first();
  await expect(block).toBeVisible();
  expect(await shimmer(block)).toBe("skeleton-shimmer");
  await release();

  await page.emulateMedia({ reducedMotion: "reduce" });
  release = await hold(page, "**/api/connections");
  await page.reload();
  await expect(block).toBeVisible();
  expect(await shimmer(block)).toBe("none");
  await release();
});

test("the onboarding pages show the step's shape while the application loads", async ({ page }) => {
  // The wizard.
  const draft = seedApplicant("skw");
  await signIn(page, draft.email, draft.password);
  let release = await hold(page, "**/api/onboarding/application");
  await page.goto("/onboarding");
  const skeleton = page.getByTestId("onboarding-skeleton");
  await expectSkeleton(page, skeleton, "Loading your application…");
  await release();
  await expect(page.getByTestId("step-facility")).toBeVisible();
  await expect(skeleton).toHaveCount(0);

  // The demo calendar.
  const complete = seedApplicant("skd", "complete");
  await page.context().clearCookies();
  await signIn(page, complete.email, complete.password);
  release = await hold(page, "**/api/onboarding/demo-slots");
  await page.goto("/onboarding");
  await expect(page.getByTestId("step-demo")).toBeVisible();
  await expectSkeleton(page, page.getByTestId("demo-skeleton"), "Loading the calendar…");
  await release();
  await expect(page.getByTestId("demo-slot").first()).toBeVisible();

  // Under review.
  const submitted = seedApplicant("sku", "submitted");
  await page.context().clearCookies();
  await signIn(page, submitted.email, submitted.password);
  release = await hold(page, "**/api/onboarding/status");
  await page.goto("/under-review");
  await expectSkeleton(page, page.getByTestId("onboarding-skeleton"), "Loading your application's status…");
  await release();
  await expect(page.getByTestId("under-review")).toBeVisible();
});
