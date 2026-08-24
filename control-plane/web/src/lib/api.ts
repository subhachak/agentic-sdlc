import type {
  AuditEntry,
  ModuleEntry,
  ConfigData,
  DashboardData,
  RunDetail,
  RunSummary,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function createRun(text: string): Promise<{ run_id: string; status: string }> {
  const form = new FormData();
  form.set("text", text);
  const res = await fetch(`${API_URL}/api/runs`, { method: "POST", body: form });
  return json(res);
}

export async function listRuns(): Promise<RunSummary[]> {
  const res = await fetch(`${API_URL}/api/runs`, { cache: "no-store" });
  return json(res);
}

export async function getRun(runId: string): Promise<RunDetail> {
  const res = await fetch(`${API_URL}/api/runs/${runId}`, { cache: "no-store" });
  return json(res);
}

export async function getAuditTrail(runId: string): Promise<AuditEntry[]> {
  const res = await fetch(`${API_URL}/api/runs/${runId}/audit`, { cache: "no-store" });
  return json(res);
}

export async function approveGate(
  runId: string,
  gate: string,
  approved: boolean,
  feedback?: string
): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`${API_URL}/api/runs/${runId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ gate, approved, feedback: feedback ?? null }),
  });
  return json(res);
}

export async function nudgeDispatch(runId: string): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`${API_URL}/api/runs/${runId}/dispatch-nudge`, { method: "POST" });
  return json(res);
}

export async function getDashboard(): Promise<DashboardData> {
  const res = await fetch(`${API_URL}/api/dashboard`, { cache: "no-store" });
  return json(res);
}

export async function getConfig(): Promise<ConfigData> {
  const res = await fetch(`${API_URL}/api/config`, { cache: "no-store" });
  return json(res);
}

export async function saveConfig(
  changes: Record<string, unknown>
): Promise<{ applied: Record<string, unknown>; active_runs: number; warning: string | null }> {
  const res = await fetch(`${API_URL}/api/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ changes }),
  });
  return json(res);
}

export async function listModules(): Promise<{ modules: ModuleEntry[] }> {
  const res = await fetch(`${API_URL}/api/graph/modules`, { cache: "no-store" });
  return json(res);
}

export async function seedGraph(
  repo: string,
  ref: string
): Promise<Record<string, number | string>> {
  const res = await fetch(`${API_URL}/api/graph/seed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo, ref }),
  });
  return json(res);
}

export function eventsUrl(runId: string): string {
  return `${API_URL}/api/runs/${runId}/events`;
}
