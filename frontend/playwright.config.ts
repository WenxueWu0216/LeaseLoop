import { defineConfig, devices } from "@playwright/test";

// Expects the stack to be running: Django (webhook token set, Celery eager or a worker),
// seeded demo data, and the Vite dev server proxying /api. CI starts these first.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{
    name: "chromium",
    use: {
      ...devices["Desktop Chrome"],
      launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
    },
  }],
});
