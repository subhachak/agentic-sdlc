import { NextRequest, NextResponse } from "next/server";
import data from "@/lib/data-store.json";

export async function GET(req: NextRequest) {
  const status = req.nextUrl.searchParams.get("status");
  const claims = status
    ? data.claims.filter((c) => c.status.toLowerCase() === status.toLowerCase())
    : data.claims;
  return NextResponse.json({ claims });
}
