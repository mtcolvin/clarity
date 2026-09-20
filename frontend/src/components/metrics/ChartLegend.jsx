import { ExternalLinkIcon } from '../icons'
import { chartableRows, hasBand } from './chartRows'

// The chart's legend: brief STRUCTURAL one-liners (what each visual element means),
// then the richer THRESHOLD blocks (the guideline cutoffs marked on the chart).
// Threshold blocks name the SOURCE organization's own classification vocabulary —
// describing the framework, never interpreting the user's reading.
//
// Lifted out of MetricChart so the Metrics page can place it where it belongs in the
// reading order: BELOW the readings table, since it's reference material you consult,
// not something you scan on the way to the numbers. It takes the same raw inputs the
// chart does and re-derives its own conditions through the shared chartRows helpers,
// rather than being handed the chart's internals.
//
// Renders nothing when no line applies.
export default function ChartLegend({
  series, flags = [], thresholds = [], personalBaselineMean = null,
}) {
  const charted = chartableRows(series)
  const anyBand = charted.some(hasBand)
  const anyUnranged = charted.some((r) => !hasBand(r))
  const anyCensored = charted.some((r) => (r.result_type ?? 'numeric') === 'censored')
  const anyPersonalRange = flags.some((f) => f.kind === 'personal_range' && f.observed_on)

  if (!anyBand && !anyCensored && !anyPersonalRange
      && personalBaselineMean == null && thresholds.length === 0) return null

  return (
    <div className="chart-legend">
      {anyBand && (
        <p className="chart-legend__line muted small">
          Shaded band = the reference range for each reading, spanning the chart
          width and stepping at the midpoint where the range changed
          {anyUnranged ? '; readings without a range are left unshaded' : ''}
          . A one-sided range (only an upper or lower limit) is shown solid at the
          limit and fades to transparent on its open side.
        </p>
      )}
      {anyCensored && (
        <p className="chart-legend__line muted small">
          ↓/↑ arrows mark below/above-limit (censored) readings at their limit
          value — the true value lies beyond the arrow. A{' '}
          <span style={{ color: '#d6336c' }}>red</span> arrow is definitively
          outside the lab range; grey means the limit can&rsquo;t place it in or out.
        </p>
      )}
      {anyPersonalRange && (
        <p className="chart-legend__line muted small">
          ○ Hollow points are outside the lab range but within your established
          range (personal-baseline mode). The lab range is still shown as the band
          above; a change from your pattern would flag with an amber caret.
        </p>
      )}
      {personalBaselineMean != null && (
        <p className="chart-legend__line muted small">
          Personal baseline (violet dashed line) = the median of your numeric
          readings (robust to outliers); shown only when personal-baseline mode
          is on for this metric.
        </p>
      )}

      {thresholds.length > 0 && (
        <>
          {(anyBand || anyCensored || anyPersonalRange || personalBaselineMean != null) && (
            <hr className="chart-legend__divider" />
          )}
          <ul className="chart-legend__thresholds">
            {thresholds.map((t) => (
              <li key={`${t.source}-${t.cutoff}`} className="chart-legend__threshold">
                {/* One flowing muted-small line — same voice as "Shaded band = …":
                    a bold "KDIGO 60" lead-in (ties to the on-chart gridline label),
                    the definition, then the inline source citation. */}
                <p className="chart-legend__line muted small">
                  <strong>{t.source} {t.cutoff}</strong>
                  {t.status_note && (
                    <em className="chart-legend__status"> · {t.status_note}</em>
                  )}
                  {t.definition ? ` — ${t.definition}` : ''}
                  {t.source_full_name ? ` Source: ${t.source_full_name}` : ''}
                  {t.url && (
                    <>
                      {' · '}
                      <a
                        className="chart-legend__link"
                        href={t.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        View {t.source} {t.source_guideline ?? 'guideline'}<ExternalLinkIcon />
                      </a>
                    </>
                  )}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
