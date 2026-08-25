"use client";

import { useEffect, useState } from "react";
import { getConfig, saveConfig } from "@/lib/api";
import AgentCheck from "@/components/agent-check";
import type { ConfigData, SettingEntry } from "@/lib/types";

/**
 * Everything that is a value rather than an action.
 *
 * Grouped by who changes it and how often, not by which module implements
 * it. Anything the platform can work out for itself is shown as a fact and
 * kept out of the way: an empty box is a question, and a question nobody
 * needs to answer is the whole reason this page was confusing.
 */

function Control({
  entry,
  draft,
  onChange,
}: {
  entry: SettingEntry;
  draft: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  const value = entry.key in draft ? draft[entry.key] : entry.value;

  if (entry.kind === "secret") {
    return (
      <span className={`pill ${entry.configured ? "ok" : "crit"}`}>
        {entry.configured ? "Configured" : "Not set"}
      </span>
    );
  }
  if (entry.kind === "static") {
    return <code className="muted">{String(entry.value ?? "—")}</code>;
  }
  if (entry.type === "bool") {
    return (
      <label className="inline" style={{ fontSize: "0.875rem" }}>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(entry.key, e.target.checked)}
        />
        {value ? "On" : "Off"}
      </label>
    );
  }
  if (entry.options.length > 0) {
    return (
      <select value={String(value ?? "")} onChange={(e) => onChange(entry.key, e.target.value)}>
        {entry.options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    );
  }
  return (
    <input
      type="text"
      value={value === null || value === undefined ? "" : String(value)}
      placeholder={entry.placeholder}
      onChange={(e) => onChange(entry.key, e.target.value)}
    />
  );
}

function Row({
  entry,
  draft,
  onChange,
}: {
  entry: SettingEntry;
  draft: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <div className="row">
      <div className="row-main">
        <div className="row-label">
          {entry.label}
          {entry.overridden && (
            <span className="pill busy" style={{ marginLeft: "var(--s2)" }}>
              changed here
            </span>
          )}
        </div>
        <div className="row-help">
          <code>{entry.key}</code>
          {entry.help && <> — {entry.help}</>}
        </div>
      </div>
      <div className="row-end">
        <Control entry={entry} draft={draft} onChange={onChange} />
      </div>
    </div>
  );
}

/** A value the platform worked out. Shown, not asked. */
function Derived({ entry }: { entry: SettingEntry }) {
  return (
    <div className="row">
      <div className="row-main">
        <div className="row-label">{entry.label}</div>
        <div className="row-help">
          <code>{entry.key}</code>
          {entry.derived_from && (
            <>
              {" — from "}
              <code>{entry.derived_from}</code>
            </>
          )}
          {entry.owned_by === "operations" && " — chosen when you sync"}
        </div>
      </div>
      <div className="row-end">
        <code>{entry.value === null || entry.value === "" ? "—" : String(entry.value)}</code>
      </div>
    </div>
  );
}

export default function SettingsPanel({ reloadKey }: { reloadKey?: number }) {
  const [data, setData] = useState<ConfigData | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setData(await getConfig());
      setDraft({});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, [reloadKey]);

  async function onSave() {
    setSaving(true);
    setError(null);
    setResult(null);
    try {
      const response = await saveConfig(draft);
      await load();
      const count = Object.keys(response.applied).length;
      setResult(
        response.warning
          ? `Applied ${count} change${count === 1 ? "" : "s"}. ${response.warning}`
          : `Applied ${count} change${count === 1 ? "" : "s"} — adapters rebuilt, no restart.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (!data) {
    return (
      <section className="panel">
        <div className="panel-body">
          <p className="muted" style={{ margin: 0 }}>
            {error ?? "Loading…"}
          </p>
        </div>
      </section>
    );
  }

  const onChange = (key: string, value: unknown) => setDraft((d) => ({ ...d, [key]: value }));
  const dirty = Object.keys(draft).length;

  const settings = data.settings;
  const applicable = settings.filter((s) => s.relevant !== false);
  // Worked out rather than asked: shown as facts, in one place, so the page
  // reads as "here is what it decided" instead of a wall of empty boxes.
  const derived = applicable.filter((s) => s.owned_by || s.derived);
  const asked = applicable.filter((s) => !s.owned_by && !s.derived);

  const platform = asked.filter((s) => s.section === "platform" && !s.advanced && s.kind === "mutable");
  const engagement = asked.filter((s) => s.section === "engagement" && !s.advanced);
  const credentials = settings.filter((s) => s.section === "credential");
  const advanced = asked.filter(
    (s) => s.advanced || s.kind === "static" || (s.section === "platform" && s.kind !== "mutable")
  );

  return (
    <>
      {(data.incoherent ?? []).map((finding) => (
        <div key={finding.id} className="notice warn">
          {/* Distinct from a stored value that would not apply: these applied
              perfectly and read the wrong thing. */}
          <h3>This builds, but will not work</h3>
          <p>
            {finding.problem} — {finding.consequence}.
          </p>
          <ul>
            {finding.remedies.map((remedy) => (
              <li key={remedy}>{remedy}</li>
            ))}
          </ul>
        </div>
      ))}

      {data.problem && (
        <div className="notice crit">
          <h3>Saved configuration was not applied</h3>
          <p>
            {data.problem} Correct it below and save again — the platform is running on its
            environment defaults, so this page is the way back.
          </p>
        </div>
      )}

      {engagement.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>This engagement</h2>
              <p>
                The few things about this client&rsquo;s setup that cannot be worked out from
                the repository. Stored on the project, so two engagements can hold different
                answers at once.
              </p>
            </div>
          </div>
          <div className="panel-body flush">
            {engagement.map((entry) => (
              <Row key={entry.key} entry={entry} draft={draft} onChange={onChange} />
            ))}
          </div>
        </section>
      )}

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Platform</h2>
            <p>
              Which integrations this deployment speaks to, which model writes, and who
              approves. Set once and rarely revisited.
            </p>
          </div>
        </div>
        <div className="panel-body flush">
          {platform.map((entry) => (
            <Row key={entry.key} entry={entry} draft={draft} onChange={onChange} />
          ))}
          <div className="row">
            <div className="row-main">
              <div className="row-label">Reach the coding agent</div>
              <div className="row-help">
                Verify the configured agent answers before a run depends on it.
              </div>
            </div>
            <div className="row-end">
              <AgentCheck />
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Credentials</h2>
            <p>
              Read from the environment and reported as present or absent, never read back —
              a value entered here would be a secret in a database and in an audit trail.
            </p>
          </div>
        </div>
        <div className="panel-body flush">
          {credentials.map((entry) => (
            <Row key={entry.key} entry={entry} draft={draft} onChange={onChange} />
          ))}
        </div>
      </section>

      {derived.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Worked out for you</h2>
              <p>
                Derived from the repository or chosen when you sync. Listed so nothing is
                hidden — override any of them below if your layout differs.
              </p>
            </div>
          </div>
          <div className="panel-body flush">
            {derived.map((entry) => (
              <Derived key={entry.key} entry={entry} />
            ))}
          </div>
          <details className="disclosure">
            <summary>Override a derived value</summary>
            <div className="panel-body flush">
              {derived
                .filter((s) => s.kind === "mutable" && !s.owned_by)
                .map((entry) => (
                  <Row key={entry.key} entry={entry} draft={draft} onChange={onChange} />
                ))}
            </div>
          </details>
        </section>
      )}

      {advanced.length > 0 && (
        <section className="panel">
          <details className="disclosure" style={{ borderTop: 0 }}>
            <summary>Advanced — tuning and fixed values</summary>
            <div className="panel-body flush">
              {advanced.map((entry) => (
                <Row key={entry.key} entry={entry} draft={draft} onChange={onChange} />
              ))}
            </div>
          </details>
        </section>
      )}

      {/* Sticky rather than at the bottom of a long page: a change made at the
          top used to need a scroll to find out whether it saved. */}
      {(dirty > 0 || result || error) && (
        <div
          className="panel"
          style={{ position: "sticky", bottom: "var(--s4)", boxShadow: "var(--shadow)" }}
        >
          <div className="row" style={{ borderBottom: 0 }}>
            <div className="row-main">
              <div className="row-label">
                {dirty
                  ? `${dirty} unsaved change${dirty === 1 ? "" : "s"}`
                  : error
                    ? "Not saved"
                    : "Saved"}
              </div>
              <div className="row-help" style={{ color: error ? "var(--crit)" : undefined }}>
                {error ?? result ?? "Applied by rebuilding the adapters — no restart."}
              </div>
            </div>
            <div className="row-end">
              {dirty > 0 && (
                <button className="ghost" onClick={() => setDraft({})} disabled={saving}>
                  Discard
                </button>
              )}
              <button onClick={() => void onSave()} disabled={saving || dirty === 0}>
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
