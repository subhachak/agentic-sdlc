import { test, expect } from "@playwright/test";

// Every expectation is derived from the API rather than from the fixture
// file. orchestrator/nodes/test_data.py appends claims when a plan references
// a status the store is missing, so a literal count or a literal policyholder
// name here would turn a seeded run into a false defect.

test("the filter defaults to All and shows every claim", async ({ page, request }) => {
  const { claims } = await (await request.get("/api/claims")).json();
  expect(claims.length).toBeGreaterThan(0);

  await page.goto("/claims");

  await expect(page.getByTestId("status-filter")).toHaveValue("All");
  await expect(page.getByTestId("claim-row")).toHaveCount(claims.length);
});

test("selecting a status shows only rows carrying that status", async ({ page, request }) => {
  const { claims } = await (await request.get("/api/claims")).json();
  // Whichever status the store actually holds, rather than assuming one is
  // present: the seeder decides what exists, and asserting on a status with
  // no claims would fail for a reason that is not the filter's fault.
  const status = claims[0].status;
  const expected = claims.filter((c: { status: string }) => c.status === status);

  await page.goto("/claims");
  await page.getByTestId("status-filter").selectOption(status);

  const rows = page.getByTestId("claim-row");
  await expect(rows).toHaveCount(expected.length);
  // The attribute rather than the cell text, so a change to how the status is
  // rendered does not read as a filtering defect.
  await expect(rows.filter({ hasNot: page.locator(`[data-status="${status}"]`) })).toHaveCount(
    expected.length,
  );
  for (const row of await rows.all()) {
    await expect(row).toHaveAttribute("data-status", status);
  }
});

test("a status with no matching claims shows the empty state instead of an empty table", async ({
  page,
}) => {
  // Interception rather than seeding, per the API contract: the data store is
  // shared by every test in the run, so a scenario that reshapes it for
  // itself breaks the others. This gives the scenario its own response
  // without touching anyone else's data.
  await page.route("**/api/claims?status=*", async (route) => {
    await route.fulfill({ status: 200, json: { claims: [] } });
  });

  await page.goto("/claims");
  await page.getByTestId("status-filter").selectOption("Denied");

  await expect(page.getByTestId("claim-row")).toHaveCount(0);
  await expect(page.getByTestId("empty-state")).toBeVisible();
  await expect(page.getByTestId("empty-state")).toContainText("No claims match");
});
