import { test, expect } from "@playwright/test";

// Exercises the endpoint directly rather than through the page. The list
// script reaches it too, but only incidentally — a response shape change that
// the page happens to tolerate would pass there and fail a real consumer.

test("the endpoint returns an object with a claims array, never a bare array", async ({
  request,
}) => {
  const response = await request.get("/api/claims");
  expect(response.status()).toBe(200);

  const body = await response.json();
  expect(Array.isArray(body)).toBe(false);
  expect(Array.isArray(body.claims)).toBe(true);
  expect(body.claims.length).toBeGreaterThan(0);

  for (const claim of body.claims) {
    expect(claim).toHaveProperty("id");
    expect(claim).toHaveProperty("policyholder");
    expect(claim).toHaveProperty("status");
    expect(claim).toHaveProperty("lastUpdated");
  }
});

test("the status parameter filters, and does so case-insensitively", async ({ request }) => {
  const { claims } = await (await request.get("/api/claims")).json();
  const status = claims[0].status;
  const expected = claims.filter((c: { status: string }) => c.status === status);

  const exact = await (await request.get(`/api/claims?status=${encodeURIComponent(status)}`)).json();
  expect(exact.claims).toHaveLength(expected.length);
  for (const claim of exact.claims) {
    expect(claim.status).toBe(status);
  }

  // The contract says case-insensitive, so a change to a strict comparison is
  // a breaking change for any caller passing a lowercased value.
  const lowered = await (
    await request.get(`/api/claims?status=${encodeURIComponent(status.toLowerCase())}`)
  ).json();
  expect(lowered.claims).toHaveLength(expected.length);
});

test("a status matching nothing returns an empty list with 200, not an error", async ({
  request,
}) => {
  const response = await request.get("/api/claims?status=NoSuchStatus");

  expect(response.status()).toBe(200);
  expect((await response.json()).claims).toEqual([]);
});

test("an omitted or empty status parameter returns every claim", async ({ request }) => {
  const all = await (await request.get("/api/claims")).json();
  const empty = await (await request.get("/api/claims?status=")).json();

  expect(empty.claims).toHaveLength(all.claims.length);
});
