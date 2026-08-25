"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getConfig,
  listProjects,
  preflightConfig,
  saveConfig,
  updateProject,
  type ProjectList,
} from "@/lib/api";
import AgentCheck from "@/components/agent-check";
import type { ConfigData, SettingEntry } from "@/lib/types";

export type SettingsView = "engagement" | "automation" | "security" | "advanced";

function valueFor(entry: SettingEntry, draft: Record<string, unknown>) {
  return entry.key in draft ? draft[entry.key] : entry.value;
}

function Control({ entry, draft, onChange }: {
  entry: SettingEntry;
  draft: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  const value = valueFor(entry, draft);
  if (entry.kind === "secret") return <span className={`pill ${entry.configured ? "ok" : "crit"}`}>{entry.configured ? "Configured" : "Not configured"}</span>;
  if (entry.kind === "static") return <code className="derived-value">{String(entry.value ?? "—")}</code>;
  if (entry.type === "bool") {
    return (
      <label className="toggle-control">
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(entry.key, event.target.checked)} />
        <span>{value ? "Enabled" : "Disabled"}</span>
      </label>
    );
  }
  if (entry.options.length > 0) {
    return <select aria-label={entry.label} value={String(value ?? "")} onChange={(event) => onChange(entry.key, event.target.value)}>{entry.options.map((option) => <option value={option} key={option}>{option.replaceAll("-", " ")}</option>)}</select>;
  }
  return (
    <input
      aria-label={entry.label}
      type={entry.type === "int" || entry.type === "float" ? "number" : "text"}
      step={entry.type === "float" ? "any" : undefined}
      value={value === null || value === undefined ? "" : String(value)}
      placeholder={entry.placeholder}
      onChange={(event) => onChange(entry.key, entry.type === "int" || entry.type === "float" ? Number(event.target.value) : event.target.value)}
    />
  );
}

function SettingRow({ entry, draft, onChange, technical = false }: {
  entry: SettingEntry;
  draft: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  technical?: boolean;
}) {
  return (
    <div className="row">
      <div className="row-main">
        <div className="row-label">{entry.label}{entry.overridden && <span className="pill info" style={{ marginLeft: 8 }}>Override</span>}</div>
        <div className="row-help">{entry.help || (technical ? <code>{entry.key}</code> : "Uses the platform default unless changed here.")}</div>
      </div>
      <div className="row-end"><Control entry={entry} draft={draft} onChange={onChange} /></div>
    </div>
  );
}

function DerivedRow({ entry }: { entry: SettingEntry }) {
  return (
    <div className="row">
      <div className="row-main">
        <div className="row-label">{entry.label}</div>
        <div className="row-help">{entry.owned_by === "operations" ? "Resolved when the repository is synchronized." : entry.derived_from ? `Inherited from ${entry.derived_from.replaceAll("_", " ")}.` : "Resolved by the platform."}</div>
      </div>
      <div className="row-end"><code className="derived-value">{entry.value === null || entry.value === "" ? "—" : String(entry.value)}</code></div>
    </div>
  );
}

function groupBy(entries: SettingEntry[]) {
  return entries.reduce<Record<string, SettingEntry[]>>((groups, entry) => {
    (groups[entry.group || "Configuration"] ??= []).push(entry);
    return groups;
  }, {});
}

export default function SettingsPanel({ reloadKey, view }: { reloadKey?: number; view: SettingsView }) {
  const [data, setData] = useState<ConfigData | null>(null);
  const [projects, setProjects] = useState<ProjectList | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [configuration, projectData] = await Promise.all([getConfig(), listProjects()]);
      setData(configuration);
      setProjects(projectData);
      setDraft({});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  useEffect(() => { void load(); }, [reloadKey, view]);

  const settingsByKey = useMemo(
    () => new Map((data?.settings ?? []).map((entry) => [entry.key, entry])),
    [data]
  );

  async function onSave() {
    if (!data || !projects) return;
    setSaving(true);
    setError(null);
    setResult(null);
    try {
      const platform: Record<string, unknown> = {};
      const engagement: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(draft)) {
        const entry = settingsByKey.get(key);
        if (entry?.section === "engagement") engagement[key] = value;
        else if (key !== "active_project") platform[key] = value;
      }

      if (Object.keys(platform).length) {
        const preflight = await preflightConfig(platform);
        if (!preflight.ok) throw new Error(preflight.problems.join(" "));
        await saveConfig(platform);
      }
      if (Object.keys(engagement).length) {
        await updateProject(projects.active, { engagement });
      }
      const count = Object.keys(draft).length;
      await load();
      setResult(`${count} change${count === 1 ? "" : "s"} validated and applied without a restart.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  if (!data) {
    return <section className="panel"><div className="panel-body"><p className="muted">{error || "Loading configuration…"}</p></div></section>;
  }

  const applicable = data.settings.filter((entry) => entry.relevant !== false && entry.key !== "active_project");
  const derived = applicable.filter((entry) => entry.owned_by || entry.derived);
  const editable = applicable.filter((entry) => !entry.owned_by && !entry.derived && entry.kind === "mutable");
  const credentials = data.settings.filter((entry) => entry.section === "credential");
  const engagement = editable.filter((entry) => entry.section === "engagement" && !entry.advanced);
  const automation = editable.filter((entry) => entry.section === "platform" && !entry.advanced);
  const advanced = editable.filter((entry) => entry.advanced);
  const onChange = (key: string, value: unknown) => setDraft((current) => ({ ...current, [key]: value }));
  const dirty = Object.keys(draft).length;

  const groups = view === "engagement" ? groupBy(engagement) : view === "automation" ? groupBy(automation) : view === "advanced" ? groupBy(advanced) : {};

  return (
    <>
      {(data.incoherent ?? []).map((finding) => (
        <div className="notice warn" key={finding.id}><h3>Configuration needs attention</h3><p>{finding.problem} — {finding.consequence}. {finding.remedies.join(" ")}</p></div>
      ))}
      {data.problem && <div className="notice crit" role="alert"><h3>Saved configuration is not active</h3><p>{data.problem}</p></div>}

      {view === "engagement" && (
        <>
          {Object.entries(groups).map(([group, entries]) => (
            <section className="panel" key={group}>
              <div className="panel-head"><div><h2>{group}</h2><p>Values a client administrator owns because they cannot be inferred from source control.</p></div><span className="pill info">This engagement</span></div>
              <div className="panel-body flush">{entries.map((entry) => <SettingRow key={entry.key} entry={entry} draft={draft} onChange={onChange} />)}</div>
            </section>
          ))}
          {derived.length > 0 && (
            <section className="panel">
              <div className="panel-head"><div><h2>Resolved delivery context</h2><p>Inherited and derived values are visible for trust, but do not need to be re-entered.</p></div><span className="pill ok">Automatic</span></div>
              <div className="panel-body flush">{derived.map((entry) => <DerivedRow key={entry.key} entry={entry} />)}</div>
              <details className="disclosure"><summary>Override an inherited value</summary><div className="panel-body flush">{derived.filter((entry) => entry.kind === "mutable" && !entry.owned_by).map((entry) => <SettingRow key={entry.key} entry={entry} draft={draft} onChange={onChange} />)}</div></details>
            </section>
          )}
        </>
      )}

      {view === "automation" && (
        <>
          <div className="config-summary">
            <div className="config-summary-item"><span>Model provider</span><strong>{data.active.model_provider || "—"}</strong></div>
            <div className="config-summary-item"><span>Execution target</span><strong>{data.active.execution_target || "—"}</strong></div>
            <div className="config-summary-item"><span>Approval policy</span><strong>{data.active.gates === "human" ? "Human gated" : data.active.gates || "—"}</strong></div>
          </div>
          {Object.entries(groups).map(([group, entries]) => (
            <section className="panel" key={group}>
              <div className="panel-head"><div><h2>{group}</h2><p>Deployment-wide behavior shared by all active engagements.</p></div><span className="pill idle">Platform</span></div>
              <div className="panel-body flush">{entries.map((entry) => <SettingRow key={entry.key} entry={entry} draft={draft} onChange={onChange} />)}{group === "Implementation" && <div className="row"><div className="row-main"><div className="row-label">Implementation agent connectivity</div><div className="row-help">Non-mutating reachability check against the configured agent.</div></div><div className="row-end"><AgentCheck /></div></div>}</div>
            </section>
          ))}
        </>
      )}

      {view === "security" && (
        <section className="panel elevated">
          <div className="panel-head"><div><h2>Credentials and connection health</h2><p>Secrets stay in the runtime environment. Their values are never returned to this console or written to its audit log.</p></div><span className={`pill ${credentials.every((entry) => entry.configured) ? "ok" : "warn"}`}>{credentials.filter((entry) => entry.configured).length} of {credentials.length} ready</span></div>
          <div className="credentials-grid">
            {credentials.map((entry) => (
              <div className="credential-card" key={entry.key}>
                <div><strong>{entry.label}</strong><span>{entry.help || "Runtime-managed credential"}</span></div>
                <span className={`pill ${entry.configured ? "ok" : "crit"}`}>{entry.configured ? "Configured" : "Missing"}</span>
              </div>
            ))}
          </div>
          <div className="row"><div className="row-main"><div className="row-label">Implementation agent</div><div className="row-help">Verify access and entitlement without creating a branch or consuming an agent task.</div></div><div className="row-end"><AgentCheck /></div></div>
        </section>
      )}

      {view === "advanced" && (
        <>
          {Object.entries(groups).map(([group, entries]) => (
            <section className="panel" key={group}>
              <div className="panel-head"><div><h2>{group}</h2><p>Operational tuning with safe working defaults.</p></div><span className="pill warn">Advanced</span></div>
              <div className="panel-body flush">{entries.map((entry) => <SettingRow key={entry.key} entry={entry} draft={draft} onChange={onChange} technical />)}</div>
            </section>
          ))}
          <section className="panel">
            <details className="disclosure">
              <summary>Configuration change history · {data.history.length} recorded changes</summary>
              {data.history.length === 0 ? <div className="panel-body"><p className="muted">No configuration changes have been recorded.</p></div> : (
                <div className="table-wrap"><table><thead><tr><th>Setting</th><th>Previous</th><th>New value</th><th>Changed by</th><th>Time</th></tr></thead><tbody>{data.history.slice(0, 20).map((change, index) => <tr key={`${change.key}-${change.at}-${index}`}><td><strong>{change.label}</strong><br /><code>{change.key}</code></td><td><code>{String(change.previous ?? "—")}</code></td><td><code>{String(change.value ?? "—")}</code></td><td>{change.changed_by}</td><td>{new Date(change.at).toLocaleString()}</td></tr>)}</tbody></table></div>
              )}
            </details>
          </section>
        </>
      )}

      {(dirty > 0 || result || error) && (
        <section className="panel settings-savebar" aria-live="polite">
          <div className="row">
            <div className="row-main"><div className="row-label">{dirty ? `${dirty} unsaved change${dirty === 1 ? "" : "s"}` : error ? "Changes not applied" : "Configuration updated"}</div><div className="row-help" style={{ color: error ? "var(--danger)" : undefined }}>{error || result || "Changes will be validated before they are applied."}</div></div>
            <div className="row-end">{dirty > 0 && <button type="button" className="secondary" disabled={saving} onClick={() => setDraft({})}>Discard</button>}<button type="button" disabled={saving || dirty === 0} onClick={() => void onSave()}>{saving ? "Validating…" : "Validate and save"}</button></div>
          </div>
        </section>
      )}
    </>
  );
}
