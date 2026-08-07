import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env["CI"],
  retries: process.env["CI"] ? 2 : 0,
  reporter: process.env["CI"] ? "github" : "list",
  // `next dev` compiles a route on its first request, and this suite opens
  // several cold routes at once across two device projects. The 30s default is
  // ample against a built app and routinely short of a cold dev compile — the
  // resulting `page.goto` timeouts look like product failures and are not.
  timeout: 90_000,
  use: {
    baseURL: process.env["WEB_BASE_URL"] ?? "http://localhost:3000",
    trace: "on-first-retry",
    navigationTimeout: 60_000,
  },
  projects: [
    { name: "chromium", use: devices["Desktop Chrome"] },
    { name: "iphone", use: devices["iPhone 14"] },
  ],
});
