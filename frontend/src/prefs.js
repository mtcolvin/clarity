// Browser-local view preferences — settings that describe how YOU are looking at the
// record, not anything about the record itself. Sibling to theme.js, which owns the one
// preference big enough to need its own module (it has to apply before first paint).
//
// PRIVACY NOTE, because localStorage is a second store outside health.db and worth being
// deliberate about: what goes here is a SCALAR, not a fact about the record. The chart
// scale is remembered as one global "linear or log" — deliberately NOT per metric, which
// would mean writing a map of metric NAMES into browser storage, and a list of the labs
// someone tracks is record-adjacent in a way "log" is not. (`ht-last-metric` already
// stores one metric name for the Metrics page's default; that is one name for a concrete
// need, and this is the reason not to grow it into a set.)
//
// Every read and write is wrapped: localStorage throws in private mode and when storage
// is disabled, and a view preference is never worth crashing a page over.

const SCALE_KEY = 'ht-chart-scale'
const SCALES = ['linear', 'log']

// The remembered Y-axis scale. It is a PREFERENCE, not a decision: a chart applies it
// only where it already offers the choice (a wide-ratio, all-positive metric), so a
// remembered "log" can never put a chart that never had the toggle onto a log axis.
export function getChartScale() {
  try {
    const v = localStorage.getItem(SCALE_KEY)
    return SCALES.includes(v) ? v : 'linear'
  } catch {
    return 'linear'
  }
}

export function setChartScale(scale) {
  try {
    localStorage.setItem(SCALE_KEY, SCALES.includes(scale) ? scale : 'linear')
  } catch { /* not fatal: the choice still holds for this view */ }
}
