export type Tone = "neutral" | "good" | "warning" | "critical" | "working";

/**
 * Label, value, and an optional note. Colour never carries the meaning on its
 * own — the note spells out what the number means.
 */
export default function StatTile({
  label,
  value,
  note,
  tone = "neutral",
  large = false,
}: {
  label: string;
  value: string | number;
  note?: string;
  tone?: Tone;
  large?: boolean;
}) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={large ? "tile-value lg" : "tile-value"}>{value}</span>
      {note && (
        <span className="status tile-note">
          {tone !== "neutral" && <span className={`status-dot ${tone}`} aria-hidden="true" />}
          {note}
        </span>
      )}
    </div>
  );
}
