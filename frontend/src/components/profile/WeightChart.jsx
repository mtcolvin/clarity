import MetricChart from '../metrics/MetricChart'

// A plain line chart of WEIGHT over time, reusing the metric chart's visuals so it
// matches the rest of the app. DISPLAY-ONLY: it maps profile_history rows into the
// series shape MetricChart reads and passes NO flags/thresholds, so weight never
// enters the analysis engine — the Profile-data boundary holds for detection; this
// is purely a chart.
//
// Plots at ANY count: a single measurement is fine (it draws as one dot). With NO
// measurements it shows a grayed, chart-sized placeholder prompting an add, so the
// chart's spot stays visible and actionable (the Profile page's "Update weight"
// button sits right above it).
//
// profile_history rows are newest-first and carry no reference range; MetricChart
// wants oldest-first numeric rows, so we sort ascending and tag result_type
// 'numeric'. (Weight is stored as-entered — if the history mixes units, the axis
// labels with the latest reading's unit, same honesty as observations.)
export default function WeightChart({ history, header = null }) {
  const points = [...(history ?? [])]
    .filter((m) => m.value != null)
    .sort((a, b) => a.recorded_on.localeCompare(b.recorded_on))

  if (points.length === 0) {
    return (
      <div className="chart chart--empty" aria-label="No weight measurements yet">
        <span className="chart--empty__text muted">Add measurement</span>
      </div>
    )
  }

  const series = points.map((m) => ({
    observed_on: m.recorded_on,
    value: m.value,
    unit: m.unit,
    result_type: 'numeric',
  }))

  return <MetricChart series={series} flags={[]} header={header} />
}
