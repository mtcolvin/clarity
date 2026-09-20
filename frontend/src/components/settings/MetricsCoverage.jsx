import { useEffect, useState } from 'react'
import { getMetricsCoverage } from '../../api'
import Loading from '../shell/Loading'

// Read-only coverage roster (the second Settings tab): every tracked metric split
// into those that carry Kind-1 guideline thresholds and those that don't — a map
// of where detector rules exist. For metrics with thresholds it shows the source
// acronyms only; the full per-rule detail (cutoffs, plain-language rule, citation)
// lives on each metric's page, not here. No controls — purely a reference list.
//
// The endpoint returns metrics already alphabetical; the partition below preserves
// that, and we sort defensively so order is deterministic regardless of payload.
export default function MetricsCoverage() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getMetricsCoverage()
      .then((data) => !cancelled && (setRows(data), setError(null)))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [])

  if (!rows && !error) return <Loading what="coverage" />
  if (!rows) {
    return (
      <p className="form__error">
        Couldn’t load metric coverage: {error}. Is the API running with the latest routes?
      </p>
    )
  }

  const byName = (a, b) => a.metric.localeCompare(b.metric)
  const withThresholds = rows.filter((r) => r.has_thresholds).sort(byName)
  const without = rows.filter((r) => !r.has_thresholds).sort(byName)
  const rcvCount = rows.filter((r) => r.has_rcv).length

  return (
    <div className="coverage">
      <p className="muted small">
        Which tracked metrics carry detector config. Guideline review thresholds
        are grouped below (source names only — see a metric’s page for its full
        rules); an{' '}
        <span className="coverage__badge coverage__badge--rcv">RCV</span> badge
        marks the {rcvCount} metric{rcvCount === 1 ? '' : 's'} with a seeded
        Reference Change Value — flagging a jump beyond normal lab + biological
        noise between consecutive results.
      </p>

      <section className="coverage__section">
        <h4>With guideline thresholds ({withThresholds.length})</h4>
        {withThresholds.length === 0 ? (
          <p className="muted small">None configured yet.</p>
        ) : (
          <ul className="coverage__list">
            {withThresholds.map((r) => (
              <li key={r.metric} className="coverage__row">
                <span className="coverage__metric">{r.metric}</span>
                {r.sources.length > 0 && (
                  <span className="muted small"> — {r.sources.join(', ')}</span>
                )}
                {r.has_rcv && (
                  <span className="coverage__badge coverage__badge--rcv">RCV</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="coverage__section">
        <h4>Without thresholds ({without.length})</h4>
        {without.length === 0 ? (
          <p className="muted small">All tracked metrics have thresholds.</p>
        ) : (
          <ul className="coverage__list">
            {without.map((r) => (
              <li key={r.metric} className="coverage__row">
                <span className="coverage__metric">{r.metric}</span>
                {r.has_rcv && (
                  <span className="coverage__badge coverage__badge--rcv">RCV</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
