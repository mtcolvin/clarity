// The faithful, complete render of one export bundle's cited facts (readings / findings /
// thresholds / context). Shared by the single-metric preview, the multi-metric grouped
// preview, and the collapsed "what was sent" alongside a result — one source of truth, so
// the previewed facts and the sent facts can't drift.
export default function BundleFacts({ bundle }) {
  return (
    <>
      <h4 className="export__section">
        Readings ({bundle.readings.length} of {bundle.n_readings})
      </h4>
      <table className="readings">
        <thead>
          <tr><th>Date</th><th>Value</th><th>Range</th><th>In range</th></tr>
        </thead>
        <tbody>
          {bundle.readings.map((r) => (
            <tr key={r.observed_on}>
              <td>{r.observed_on}</td>
              {/* per-type display: qualitative shows its text, censored its bound, numeric its value */}
              <td>{r.display ?? (r.value ?? '—')}</td>
              <td>
                {r.result_type === 'qualitative'
                  ? (r.normal_text ?? '—')
                  : <>{r.ref_low ?? '—'} – {r.ref_high ?? '—'}</>}
              </td>
              <td>{r.in_range === null || r.in_range === undefined ? '—' : r.in_range ? 'Yes' : 'No'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4 className="export__section">Engine findings ({bundle.engine_findings.length})</h4>
      {bundle.engine_findings.length === 0 ? (
        <p className="muted small">None.</p>
      ) : (
        bundle.engine_findings.map((f, i) => {
          const { kind, severity, message, ...rest } = f
          return (
            <div className="export__finding" key={i}>
              <strong>{kind}</strong> ({severity}) — {message}
              {Object.keys(rest).length > 0 && (
                <p className="export__finding-detail">
                  {Object.entries(rest).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                </p>
              )}
            </div>
          )
        })
      )}

      <h4 className="export__section">Cited thresholds ({bundle.cited_thresholds.length})</h4>
      {bundle.cited_thresholds.length === 0 ? (
        <p className="muted small">None.</p>
      ) : (
        bundle.cited_thresholds.map((t, i) => (
          <div className="export__finding" key={i}>
            <strong>{t.source} {t.cutoff}</strong> — {t.definition}
            {t.gap_to_cutoff !== null && (
              <p className="export__finding-detail">gap to cutoff: {t.gap_to_cutoff}</p>
            )}
          </div>
        ))
      )}

      <h4 className="export__section">Other context</h4>
      <div className="export__finding">
        Personal baseline (median): {bundle.personal_baseline_mean ?? '—'}<br />
        Personal baseline mode: {bundle.personal_baseline_mode ? 'on' : 'off'}<br />
        Methodology note: {bundle.methodology_note ?? '—'}<br />
        Latest change: {bundle.latest_change
          ? `${bundle.latest_change.previous_display} → ${bundle.latest_change.current_display} (${bundle.latest_change.status})`
          : '—'}
      </div>
    </>
  )
}
