import InfoHint from '../InfoHint'

// Highest-severity first so the things worth attention sit at the top.
const SEVERITY_ORDER = { high: 0, watch: 1, info: 2 }

// Per-reading anomaly kinds are OWNED by the HistoryPanel (the whole-history
// "notable readings" view summarizes every out_of_range / personal_baseline).
// This regular section keeps only the whole-series / latest-crossing kinds
// (trend, threshold, delta) so a flag isn't listed in both panels. Nothing is
// dropped: every out_of_range / personal_baseline a metric has is represented in
// the history view (analyze_history computes the same set over the full series).
const HISTORY_OWNED_KINDS = new Set(['out_of_range', 'personal_baseline'])

// Scoped heading so this section reads as CURRENT-state (the latest reading,
// recent change, and overall trend) — distinct from the whole-history view in
// HistoryPanel. Without the scope, an empty "no flags" here reads as a blanket
// "nothing stands out" that contradicts past readings the history panel lists.
export default function FlagList({ flags }) {
  const own = flags.filter((f) => !HISTORY_OWNED_KINDS.has(f.kind))
  const sorted = [...own].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9),
  )

  return (
    <section className="current-flags">
      <h3>
        Current flags
        <InfoHint text="Findings about the current state: the latest reading, the most recent change, and the overall trend." />
      </h3>
      {sorted.length === 0 ? (
        <p className="muted">
          No current flags — nothing notable in the latest reading or current trend.
        </p>
      ) : (
        <ul className="flags">
          {sorted.map((f, i) => (
            <li key={i} className={`flag flag--${f.severity}`}>
              {/* Type (severity) + date on the head line; the description drops
                  below. Every flag now carries a date (trend flags are stamped
                  with the latest reading's date). */}
              <div className="flag__head">
                <span className="badge">{f.severity}</span>
                {f.observed_on && <span className="flag__kind">{f.observed_on}</span>}
              </div>
              <span className="flag__msg">{f.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
