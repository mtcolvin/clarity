// Dashboard-level "since your last reading" digest, across ALL metrics. The
// engine (analysis.latest_change) computes each movement deterministically and
// the /changes route surfaces only metrics that BOTH moved AND have a recent
// latest reading (within recent_days) — stale months-old changes, unchanged
// metrics, and single-reading metrics are intentionally dropped. This component
// only displays the result. Descriptive only — "rose", "fell", "changed from X
// to Y", "now outside its reference range" — never what it means.
//
// `data` is the /changes payload, fetched by HomePage — see the note there.
export default function ChangesDigest({ data }) {
  if (!data) return null

  const { moved, recent_days: recentDays, total_metrics: totalMetrics } = data
  // Nothing in the DB yet — let the rest of the page handle the empty state.
  if (totalMetrics === 0) return null

  return (
    <section className="rsec">
      <h2 className="rsec__head">Since your last reading</h2>

      {moved.length > 0 ? (
        <ul className="changes__list">
          {moved.map((c) => (
            <li key={c.metric} className={`change${c.flag_transition ? ' change--flagged' : ''}`}>
              {c.text}
            </li>
          ))}
        </ul>
      ) : (
        // Explicit empty state: distinguishes "no recent movement" from a bug, so
        // an empty digest reads as informative rather than broken.
        <p className="muted small">
          No new results in the last {recentDays} days.
        </p>
      )}
    </section>
  )
}
