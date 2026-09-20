import { useState } from 'react'

// Cross-metric overview: a consolidated "what should I look at" view across ALL
// metrics. Shows each metric's CURRENT state — the flags on its latest reading
// plus its overall trend — ranked server-side (severity > deviation magnitude >
// recency), reordered for display by recency, and shown top-5 with an expander
// for the rest. (A former second section, "Notable across your history", was
// removed as stale; the /overview route still returns `history`, now ignored.)
//
// Descriptive only: every line is a Flag.message the engine produced — this
// component reorders and lists, it never reinterprets. Each row links to that
// metric's detail view (onSelectMetric).
//
// `data` is the /overview payload, fetched by HomePage — see the note there.
const TOP_N = 5

// One clickable row: the whole row is the button, so the metric name and the flag
// text are a single jump-to-metric target. The name leads (it's what you're looking
// for), with the severity badge and date trailing on the same line and the engine's
// message beneath. `date` is the flagged reading's observed_on (ISO 'YYYY-MM-DD',
// per the date charter); whole-series flags (e.g. trend) have none, so it's omitted.
function OverviewRow({ metric, date, severity, text, onSelect }) {
  return (
    <li className="ovrow">
      <button
        type="button"
        className="ovrow__pick"
        onClick={() => onSelect(metric)}
        title={`Go to ${metric}`}
      >
        <span className="ovrow__head">
          <span className="ovrow__metric">{metric}</span>
          <span className={`badge badge--${severity}`}>{severity}</span>
          {date && <span className="ovrow__date">{date}</span>}
        </span>
        <span className="ovrow__msg">{text}</span>
      </button>
    </li>
  )
}

export default function Overview({ data, onSelectMetric }) {
  const [open, setOpen] = useState(false)

  // Never block the page on the overview: before load or on an empty DB, render
  // nothing (HomePage handles the error case by leaving `data` null).
  if (!data || data.total_metrics === 0) return null

  const { current } = data

  // Shown ordered by RECENCY — most recent flagged reading first. observed_on is an
  // ISO 'YYYY-MM-DD' string, so a plain string compare is chronological; whole-series
  // flags (no date) sink to the end. Array.sort is stable, so the server's severity
  // ranking is preserved as the tiebreaker among same-date flags. Display-only — the
  // engine's ranking is unchanged.
  const byRecency = [...current].sort(
    (a, b) => (b.observed_on ?? '').localeCompare(a.observed_on ?? ''),
  )
  const shown = open ? byRecency : byRecency.slice(0, TOP_N)
  const more = byRecency.length - TOP_N

  return (
    <section className="rsec">
      <h2 className="rsec__head">Current flags</h2>
      {current.length === 0 ? (
        <p className="muted">Nothing stands out in any metric&rsquo;s latest reading or trend.</p>
      ) : (
        <>
          <ul className="ovlist">
            {shown.map((f, i) => (
              <OverviewRow
                key={i}
                metric={f.metric}
                date={f.observed_on}
                severity={f.severity}
                text={f.message}
                onSelect={onSelectMetric}
              />
            ))}
          </ul>
          {more > 0 && (
            <button type="button" className="ovlist__more" onClick={() => setOpen((o) => !o)}>
              {open ? 'Show less' : `Show ${more} more`}
            </button>
          )}
        </>
      )}
    </section>
  )
}
