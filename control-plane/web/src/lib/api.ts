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
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: string | { message?: string } };
      detail = typeof parsed.detail === "string"
        ? parsed.detail
        : parsed.detail?.message || text;
    } catch {
      // Plain-text error responses are already suitable for display.
    }
    throw new Error(detail || `${res.status} ${res.statusText}`);
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

export interface GraphExportData {
  export_version: number;
  project: string;
  scope: string;
  generated: boolean;
  provenance: {
    repo: string | null;
    commit_sha: string | null;
    indexer_version: string | null;
    indexed_at: string | null;
    pinned: boolean;
    internal_capture_rate: number | null;
    most_missed: [string, number][];
    units: string[];
  };
  routes: Record<string, string[]>;
  modules: { id: string; paths: string[] }[];
  depends_on: { from: string; to: string; weight: number }[];
}

export async function getGraphExport(scope = ""): Promise<GraphExportData> {
  const query = new URLSearchParams({ scope });
  const res = await fetch(`${API_URL}/api/graph/export?${query.toString()}`, { cache: "no-store" });
  return json(res);
}

export interface SeedSummary {
  repo: string;
  ref: string;
  commit_sha: string | null;
  pinned: boolean;
  indexer_version: string;
  modules: number;
  files: number;
  dependencies: number;
  file_imports: number;
  edges_written: number;
  removed: { edges: number; nodes: number };
  resolution: {
    total_imports: number;
    resolved: number;
    external_package: number;
    unresolved_relative: number;
    unresolved_internal: number;
    internal_capture_rate: number;
    most_missed: [string, number][];
  };
  skipped_files: number;
}

export interface HydrationStep {
  id: string;
  title: string;
  detail: string;
  ready: boolean;
  blocked_by: string | null;
  quality: {
    internal_capture_rate: number;
    sufficient: boolean;
    most_missed: [string, number][];
  } | null;
}

export interface HydrationStatus {
  hydrated: boolean;
  provenance: {
    repo: string | null;
    commit_sha: string | null;
    indexer_version: string | null;
    indexed_at: string | null;
    pinned: boolean;
    internal_capture_rate: number | null;
  };
  counts: { nodes: Record<string, number>; edges: Record<string, number> };
  steps: HydrationStep[];
}

export interface RefreshSummary extends SeedSummary {
  delta: {
    edges_added: number;
    edges_removed: number;
    nodes_removed: number;
    unchanged: number;
    added_sample: string[];
    removed_sample: string[];
  };
}

export interface ExportSummary {
  path: string;
  scope: string;
  modules: number;
  depends_on: number;
  routes: number;
  commit_sha: string | null;
}

export interface RetrievalStatus {
  built: boolean;
  chunks: number;
  built_for: string | null;
  current_commit: string | null;
  stale: boolean;
}

export interface ProjectRecord {
  id: string;
  name: string;
  description: string;
  engagement: Record<string, string | number | null>;
  archived: boolean;
  created_at: string | null;
}

export interface ProjectList {
  active: string;
  defaults: Record<string, string | number | null>;
  engagement_keys: string[];
  projects: ProjectRecord[];
}

export async function listProjects(): Promise<ProjectList> {
  const res = await fetch(`${API_URL}/api/projects`, { cache: "no-store" });
  return json(res);
}

/**
 * Fired when the set of projects changes. The switcher lives in the nav and
 * the editor lives on the configuration page, so without this a project
 * created in one is invisible in the other until a reload.
 */
export const PROJECTS_CHANGED = "agentic-sdlc:projects-changed";

function announceProjectsChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(PROJECTS_CHANGED));
  }
}

export async function createProject(
  id: string,
  name: string,
  description: string
): Promise<ProjectRecord> {
  const res = await fetch(`${API_URL}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, name, description }),
  });
  const created = await json<ProjectRecord>(res);
  announceProjectsChanged();
  return created;
}

export async function updateProject(
  id: string,
  changes: { name?: string; description?: string; engagement?: Record<string, unknown> }
): Promise<ProjectRecord> {
  const res = await fetch(`${API_URL}/api/projects/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  return json(res);
}

export async function activateProject(
  id: string
): Promise<{ active: string; active_runs: number; warning: string | null }> {
  const res = await fetch(`${API_URL}/api/projects/${id}/activate`, { method: "POST" });
  return json(res);
}

export async function archiveProject(id: string): Promise<{ archived: string }> {
  const res = await fetch(`${API_URL}/api/projects/${id}/archive`, { method: "POST" });
  const result = await json<{ archived: string }>(res);
  announceProjectsChanged();
  return result;
}

export async function preflightConfig(
  changes: Record<string, unknown>
): Promise<{ ok: boolean; problems: string[] }> {
  const res = await fetch(`${API_URL}/api/config/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ changes }),
  });
  return json(res);
}

export async function checkImplementationAgent(): Promise<{
  ok: boolean;
  agent: string;
  detail: string;
}> {
  const res = await fetch(`${API_URL}/api/config/check-agent`, { method: "POST" });
  return json(res);
}


export type RepositoryOption = {
  full_name: string;
  default_branch: string;
  private: boolean;
  description: string;
  updated_at: string;
};

export type RepositoryList = {
  available: boolean;
  reason?: string;
  current?: string | null;
  repositories: RepositoryOption[];
};

export type ScopeCandidate = {
  path: string;
  files: number;
  marker: string;
  label: string;
  nested: string[];
};

export type SyncStep = {
  step: "index" | "retrieval" | "export";
  status: "ok" | "failed" | "skipped" | "needs_choice";
  summary: string;
  candidates?: ScopeCandidate[];
  selected?: string | null;
  must_choose?: boolean;
  scope?: string;
};

export type SyncResult = {
  ok: boolean;
  repo: string;
  ref: string;
  first_time: boolean;
  steps: SyncStep[];
};

export async function listRepositories(): Promise<RepositoryList> {
  const res = await fetch(`${API_URL}/api/graph/repositories`, { cache: "no-store" });
  return json(res);
}

/** Index or update, ground the agent, and export — in one call. */
export async function syncGraph(repo: string, scope?: string | null, ref?: string | null): Promise<SyncResult> {
  const res = await fetch(`${API_URL}/api/graph/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo, ...(scope ? { scope } : {}), ...(ref ? { ref } : {}) }),
  });
  return json(res);
}

export async function hydrationStatus(): Promise<HydrationStatus> {
  const res = await fetch(`${API_URL}/api/graph/status`, { cache: "no-store" });
  return json(res);
}

export async function refreshGraph(repo: string, ref: string): Promise<RefreshSummary> {
  const res = await fetch(`${API_URL}/api/graph/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo, ref }),
  });
  return json(res);
}

export async function exportGraph(scope: string): Promise<ExportSummary> {
  const res = await fetch(`${API_URL}/api/graph/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope }),
  });
  return json(res);
}

export async function rebuildRetrieval(): Promise<RetrievalStatus> {
  const res = await fetch(`${API_URL}/api/graph/retrieval/rebuild`, { method: "POST" });
  return json(res);
}

export async function seedGraph(repo: string, ref: string): Promise<SeedSummary> {
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
