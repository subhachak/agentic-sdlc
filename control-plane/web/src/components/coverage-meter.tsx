/**
 * How many acceptance criteria have reached a passing test.
 *
 * The fill carries severity and the track is a lighter step of the same hue,
 * so the state reads across the whole bar rather than only where it stops.
 */
export default function CoverageMeter({
  tested,
  total,
}: {
  tested: number;
  total: number;
}) {
  const pct = total === 0 ? 0 : Math.round((tested / total) * 100);
  const tone = total === 0 ? "" : pct >= 80 ? "" : pct >= 50 ? "warning" : "critical";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem" }}>
        <span>
          {total === 0
            ? "No acceptance criteria in the graph yet"
            : `${tested} of ${total} criteria verified by a passing test`}
        </span>
        <span className="muted" style={{ fontVariantNumeric: "tabular-nums" }}>
          {total === 0 ? "—" : `${pct}%`}
        </span>
      </div>
      <div
        className="meter"
        role="meter"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Acceptance criteria verified by a passing test"
      >
        <div className={`meter-fill ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
