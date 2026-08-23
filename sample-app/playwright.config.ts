import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./generated-tests",
  outputDir: "../evidence/test-results",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    ["json", { outputFile: "../evidence/results.json" }],
    ["html", { outputFolder: "../evidence/html-report", open: "never" }],
  ],
  use: {
    baseURL: "http://localhost:3000",
    // Captured on every test, not just failures. A PASS comment that reports
    // "0 screenshots, 0 traces" is not an audit trail, and proving a green
    // run is the whole point of the evidence phase.
    trace: "on",
    screenshot: "on",
    video: "retain-on-failure",
  },
  webServer: {
    command: "npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
