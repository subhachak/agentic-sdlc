"use client";

import Link from "next/link";

import { useEffect, useState } from "react";
import { getConfig, saveConfig } from "@/lib/api";
import type { ConfigData, SettingEntry } from "@/lib/types";

function Field({
  entry,
  draft,
  onChange,
}: {
  entry: SettingEntry;
  draft: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  const value = entry.key in draft ? draft[entry.key] : entry.value;

  return (
    <div className="field">
      <div>
        <div className="field-label">
          {entry.label}{" "}
          {entry.overridden && <span className="tag on">set here</span>}
          {entry.kind === "static" && <span className="tag">restart</span>}
          {entry.kind === "secret" && <span className="tag">environment</span>}
        </div>
        <div className="field-help">
          <code>{entry.key}</code>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
        {entry.kind === "secret" ? (
          <span className="status">
            <span
              className={`status-dot ${entry.configured ? "good" : "critical"}`}
              aria-hidden="true"
            />
            {entry.configured ? "Configured in the environment" : "Not set"}
          </span>
        ) : entry.kind === "static" ? (
          <code className="muted">{String(entry.value ?? "—")}</code>
        ) : entry.type === "bool" ? (
          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", fontSize: "0.9rem" }}>
            <input
              type="checkbox"
              checked={Boolean(value)}
              onChange={(e) => onChange(entry.key, e.target.checked)}
            />
            {value ? "On" : "Off"}
          </label>
        ) : entry.options.length > 0 ? (
          <select value={String(value ?? "")} onChange={(e) => onChange(entry.key, e.target.value)}>
            {entry.options.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            value={value === null || value === undefined ? "" : String(value)}
            placeholder={entry.placeholder}
            onChange={(e) => onChange(entry.key, e.target.value)}
          />
        )}
        {entry.help && <span className="field-help">{entry.help}</span>}
      </div>
    </div>
  );
}

export default function ConfigPage() {
  const [data, setData] = useState<ConfigData | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setData(await getConfig());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onSave() {
    setSaving(true);
    setError(null);
    setResult(null);
    try {
      const response = await saveConfig(draft);
      setDraft({});
      await load();
      const count = Object.keys(response.applied).length;
      setResult(
        response.warning
          ? `Applied ${count} change${count === 1 ? "" : "s"}. ${response.warning}`
          : `Applied ${count} change${count === 1 ? "" : "s"} — adapters rebuilt, no restart needed.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (!data) {
    return (
      <main className="wide">
        <h1>Configuration</h1>
        <p className="muted">{error ?? "Loading..."}</p>
      </main>
    );
  }

  const dirty = Object.keys(draft).length;

  /**
   * Three sections, on one page, because they answer different questions and
   * are changed by different people at different times. Presenting them as
   * one list makes a client's repository name look like a platform decision,
   * and buries the handful of fields a new engagement actually needs among
   * twenty that should be left alone.
   */
  const SECTIONS = [
    {
      id: "engagement" as const,
      title: "This engagement",
      blurb:
        "What the platform is pointed at — repositories, branches, environments, and how " +
        "coarse a module is in this codebase. These are the fields a new client or project " +
        "needs, and the ones to change when moving between them.",
    },
    {
      id: "platform" as const,
      title: "Platform",
      blurb:
        "How the platform itself runs: which integrations it speaks to, which model, and " +
        "the retry and gate policy. Set once per deployment and rarely revisited.",
    },
    {
      id: "credential" as const,
      title: "Credentials",
      blurb:
        "Read from the environment. Reported as present or absent and never read back — " +
        "a value entered here would be a secret in a database and in an audit trail.",
    },
  ];

  return (
    <main className="wide">
      <h1>Configuration</h1>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>
        Saved changes are applied by rebuilding the adapters — no restart. Every change is
        recorded below with what it was before. For indexing, exporting and the rest of
        setup, see <Link href="/operations">Operations</Link>.
      </p>

      {SECTIONS.map((section) => {
        const entries = data.settings.filter((s) => s.section === section.id);
        if (entries.length === 0) return null;
        const groups = Array.from(new Set(entries.map((s) => s.group)));

        return (
          <section key={section.id} aria-labelledby={`section-${section.id}`}>
            <h2 id={`section-${section.id}`} className="section-heading">
              {section.title}
            </h2>
            <p className="section-blurb">{section.blurb}</p>
            {groups.map((group) => (
              <div className="card" key={group}>
                {groups.length > 1 && (
                  <h3 style={{ marginTop: 0, fontSize: "0.85rem", color: "var(--muted)",
                               textTransform: "uppercase", letterSpacing: "0.04em" }}>
                    {group}
                  </h3>
                )}
                {entries
                  .filter((s) => s.group === group)
                  .map((entry) => (
                    <Field
                      key={entry.key}
                      entry={entry}
                      draft={draft}
                      onChange={(key, value) => setDraft((d) => ({ ...d, [key]: value }))}
                    />
                  ))}
              </div>
            ))}
          </section>
        );
      })}

      {data.history.length > 0 && (
        <div className="card">
          <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Recent changes</h2>
          <table>
            <thead>
              <tr>
                <th>Setting</th>
                <th>From</th>
                <th>To</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {data.history.slice(0, 8).map((change, i) => (
                <tr key={`${change.key}-${change.at}-${i}`}>
                  <td>{change.label}</td>
                  <td className="muted">
                    <code>{change.previous === null ? "environment default" : String(change.previous)}</code>
                  </td>
                  <td>
                    <code>{change.value === null ? "environment default" : String(change.value)}</code>
                  </td>
                  <td className="muted">{new Date(change.at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
        <button onClick={onSave} disabled={saving || dirty === 0}>
          {saving ? "Applying..." : dirty === 0 ? "No changes" : `Apply ${dirty} change${dirty === 1 ? "" : "s"}`}
        </button>
        {dirty > 0 && (
          <button className="secondary" onClick={() => setDraft({})} disabled={saving}>
            Discard
          </button>
        )}
      </div>

      {result && <p style={{ color: "var(--success)" }}>{result}</p>}
      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}
    </main>
  );
}
