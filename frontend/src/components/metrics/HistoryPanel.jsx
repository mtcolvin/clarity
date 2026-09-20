// Notable readings across this metric's whole history — readings that anchor to a
// specific date: NUMERIC anomalies (out-of-range / unusual-for-your-baseline,
// grouped + condensed by the engine) PLUS CENSORED out-of-range readings.
//
// The numeric anomalies come grouped from analyze_history (a group with many
// same-kind anomalies leads with one deterministic summary line — "14 of 38
// readings above the reference range…" — that expands; 1–2-reading groups list
// individually). Censored out-of-range flags can't be grouped that way (censored
// values enter no numerical math), but they're already produced by
// flag_censored_out_of_range, so we render each as its own text line here — the
// same surface a numeric out-of-range gets, so the history scan doesn't silently
// miss them. (Presenting an already-computed flag needs no new math; the
// numeric-only constraint was a math constraint, not a presentation one.)
//
// Descriptive only: it restates the engine's summary/messages and never adds what
// they indicate. This is pure presentation.

import InfoHint from '../InfoHint'

// One individual reading line (used inside an expanded summary, and for the
// small inline groups).
function FlagRow({ flag }) {
  return (
    <li className={`flag flag--${flag.severity}`}>
      {/* Type (severity) + date on the head line; description below. */}
      <div className="flag__head">
        <span className="badge">{flag.severity}</span>
        {flag.observed_on && <span className="flag__kind">{flag.observed_on}</span>}
      </div>
      <span className="flag__msg">{flag.message}</span>
    </li>
  )
}

export default function HistoryPanel({ history, flags = [] }) {
  if (!history) return null
  const groups = history.groups ?? []

  // Censored out-of-range flags (from analyze_series, NOT analyze_history — that
  // stays numeric-only). Filter to censored so numeric out_of_range isn't
  // duplicated (those come from `groups`). Newest-first to match the recency lean.
  const censored = (flags ?? [])
    .filter((f) => f.kind === 'out_of_range' && f.detail?.censored)
    .sort((a, b) => (b.observed_on ?? '').localeCompare(a.observed_on ?? ''))

  // Heading scopes this to the WHOLE history (distinct from the current-state
  // "Current flags" section above), so a populated history alongside no current
  // flags reads as two true statements, not a contradiction.
  const heading = (
    <h3>
      Notable readings
      <InfoHint text="Past readings across this metric's whole history that stood out — not only the latest." />
    </h3>
  )

  if (!groups.length && !censored.length) {
    return (
      <section className="history">
        {heading}
        <p className="muted">No past readings stood out for this metric.</p>
      </section>
    )
  }

  return (
    <section className="history">
      {heading}
      <ul className="flags">
        {groups.map((g, i) => {
          // count > detail.length means the per-group cap-at-10 trimmed the list.
          const omitted = g.count - g.detail.length
          if (g.condensed) {
            return (
              <li key={i} className={`flag flag--${g.severity} history__group`}>
                <details>
                  <summary>
                    <span className="badge">{g.severity}</span>
                    <span className="flag__msg">{g.summary}</span>
                  </summary>
                  <ul className="flags history__detail">
                    {g.detail.map((f, j) => (
                      <FlagRow key={j} flag={f} />
                    ))}
                  </ul>
                  {omitted > 0 && (
                    <p className="muted small history__omitted">
                      Showing the {g.detail.length} most notable of {g.count}.
                    </p>
                  )}
                </details>
              </li>
            )
          }
          // 1–2 readings: not a wall, so show them individually (no summary).
          return g.detail.map((f, j) => <FlagRow key={`${i}-${j}`} flag={f} />)
        })}
        {/* Censored out-of-range readings — same row styling as a numeric
            out-of-range, so the visual language stays consistent. */}
        {censored.map((f, i) => <FlagRow key={`cens-${i}`} flag={f} />)}
      </ul>
    </section>
  )
}
