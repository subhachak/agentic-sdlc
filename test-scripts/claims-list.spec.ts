import { test, expect } from "@playwright/test";

// Row count is derived from the API rather than hard-coded: nodes/test_data.py
// appends fixtures when the plan references a status the store is missing, so
// any literal count here would turn a seeded run into a false defect.
test("claims table renders all claims with id, policyholder, status, last updated", async ({
  page,
  request,
}) => {
  const { claims } = await (await request.get("/api/claims")).json();
  expect(claims.length).toBeGreaterThan(0);

  await page.goto("/claims");

  const rows = page.getByTestId("claim-row");
  await expect(rows).toHaveCount(claims.length);

  const first = claims[0];
  const firstRow = rows.first();
  await expect(firstRow).toContainText(first.id);
  await expect(firstRow).toContainText(first.policyholder);
  await expect(firstRow).toContainText(first.status);
  await expect(firstRow).toContainText(first.lastUpdated);
});
