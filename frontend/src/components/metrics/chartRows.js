// Which readings the chart can plot. Shared by MetricChart (what it draws) and
// ChartLegend (which legend lines apply), so the two can't drift apart — the legend
// sits in a different part of the page now and would otherwise re-derive this by hand.
//
// NUMERIC readings are real points; CENSORED ("<5" / ">100") are drawn as an arrow at
// their bound. Qualitative ("Positive") and range-as-text have no Y position and are
// not charted at all — they stay visible in the readings table.
export function chartableRows(series) {
  return series.filter((r) => {
    const rt = r.result_type ?? 'numeric'
    if (rt === 'numeric') return r.value != null
    if (rt === 'censored') return r.value != null && r.operator
    return false
  })
}

// A reading is shaded by the reference band whenever it has AT LEAST ONE bound —
// one-sided lab ranges ('≤10', '≥5') are valid and render with a faded open side.
export function hasBand(r) {
  return r.ref_low != null || r.ref_high != null
}
