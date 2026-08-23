import { NextRequest, NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import path from "node:path";

// The data store is read per request, not imported. A static
// `import data from "@/lib/data-store.json"` is inlined at build time, so
// fixtures that orchestrator/nodes/test_data.py appends after `next build`
// would never reach the running app.
export const dynamic = "force-dynamic";

type Claim = {
  id: string;
  policyholder: string;
  status: string;
  lastUpdated: string;
};

const DATA_STORE = path.join(process.cwd(), "lib", "data-store.json");

async function readClaims(): Promise<Claim[]> {
  const raw = await readFile(DATA_STORE, "utf8");
  return (JSON.parse(raw) as { claims: Claim[] }).claims;
}

export async function GET(req: NextRequest) {
  const status = req.nextUrl.searchParams.get("status");
  const all = await readClaims();
  const claims = status
    ? all.filter((c) => c.status.toLowerCase() === status.toLowerCase())
    : all;
  return NextResponse.json({ claims });
}
