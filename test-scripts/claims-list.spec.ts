import { test, expect } from "@playwright/test";

test("claims table renders all seeded claims", async ({ page }) => {
  await page.goto("/claims");
  const rows = page.getByTestId("claim-row");
  await expect(rows).toHaveCount(5);
  await expect(page.getByText("CLM-1001")).toBeVisible();
});
