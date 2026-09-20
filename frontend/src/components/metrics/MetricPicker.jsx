// `derivedMetrics` is a name -> caption map of COMPUTED metrics. They render in a
// separate "Computed metrics" <optgroup> below the measured ones (rather than
// interleaved alphabetically), so the picker distinguishes what was measured from
// what's derived. With none, the select is a flat measured list as before.
//
// `aliasByMetric` is a canonical-name -> display-alias map. The option LABEL shows the
// alias (the friendly name) when one is set, but the option VALUE stays the CANONICAL
// name — that's the metric's identity and what every API call keys on, so the display
// layer can never change which metric is addressed.
// `collectionMetrics` is the set of metric names that have ≥1 reading in a timed
// collection (24h urine, etc.). They render in their OWN "Timed collections" optgroup —
// so a collection's analytes cluster visually without needing a name prefix, the same way
// derived metrics get a "Computed metrics" group.
// `groupByMetric` is a canonical-name -> USER GROUP label map (e.g. an arterial blood-gas
// panel). Each distinct group renders as its own <optgroup>. Precedence when a metric
// could fall in several buckets: derived (Computed) > explicit user group > collection >
// ungrouped — the explicit user choice wins over the automatic collection grouping.
// `variant="pill"` renders the same <select> as a compact "Change metric" pill: the
// native control is still there (grouping, keyboard, the browser's own list) but sits
// transparent over a styled label. It's used where the metric NAME is already the
// heading beside it, so a select repeating that name would just say it twice.
export default function MetricPicker({
  metrics, selected, onChange, derivedMetrics = {}, aliasByMetric = {},
  collectionMetrics = [], groupByMetric = {}, variant = 'default',
}) {
  const collSet = new Set(collectionMetrics)
  const isDerived = (m) => m in derivedMetrics
  const userGroup = (m) => (!isDerived(m) ? groupByMetric[m] || null : null)

  const ungrouped = metrics.filter(
    (m) => !isDerived(m) && !userGroup(m) && !collSet.has(m),
  )
  const collected = metrics.filter(
    (m) => !isDerived(m) && !userGroup(m) && collSet.has(m),
  )
  const computed = metrics.filter(isDerived)

  // Distinct user-group labels, alphabetical; each becomes an <optgroup>.
  const groupNames = [
    ...new Set(metrics.map(userGroup).filter(Boolean)),
  ].sort((a, b) => a.localeCompare(b))

  const option = (m) => (
    <option key={m} value={m}>
      {aliasByMetric[m] || m}
    </option>
  )
  const select = (
    <select aria-label="Metric" value={selected} onChange={(e) => onChange(e.target.value)}>
      {ungrouped.map(option)}
      {groupNames.map((g) => (
        <optgroup key={g} label={g}>
          {metrics.filter((m) => userGroup(m) === g).map(option)}
        </optgroup>
      ))}
      {collected.length > 0 && (
        <optgroup label="Timed collections (24h)">{collected.map(option)}</optgroup>
      )}
      {computed.length > 0 && (
        <optgroup label="Computed metrics">{computed.map(option)}</optgroup>
      )}
    </select>
  )

  if (variant === 'pill') {
    return (
      <label className="picker picker--pill">
        {/* The visible label is decorative — the select above carries the accessible
            name and the current value, so this must not be read out as well. */}
        <span className="picker__pill" aria-hidden="true">
          Change metric <span className="picker__caret">▾</span>
        </span>
        {select}
      </label>
    )
  }

  return <label className="picker">{select}</label>
}
