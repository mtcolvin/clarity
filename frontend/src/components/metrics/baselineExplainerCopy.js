import { MIN_COMPUTABLE_READINGS } from './BaselineMode'

// The personal-baseline explainer copy, shared verbatim (as a function of the
// live threshold values, not a static string) by both surfaces — the
// Metrics-page auto-once popup (BaselineExplainer.jsx) and the permanent
// Settings-page block (SettingsPanel.jsx). Split into its own plain module
// (rather than living in BaselineExplainer.jsx) because a function export
// alongside a component default trips eslint-plugin-react-refresh's
// allowConstantExport check, which permits constant literals but not
// functions in a component file.
//
// Cites two LIVE numbers rather than hardcoding them: the suggestion banner's
// fraction/readings floor is a persisted, user-tunable setting (settings.py:
// personal_baseline_suggest_min_fraction/_min_readings) — a static string
// would silently go stale the moment someone edits those on the Settings
// page. MIN_COMPUTABLE_READINGS (the quiet link's lower, separate floor) has
// no such backend setting, so it's imported as the one shared constant
// instead of retyped as a second, driftable literal.
export function baselineExplainerCopy({ suggestFraction, suggestMinReadings }) {
  const pct = Math.round(suggestFraction * 100)
  return (
    "Personal-baseline mode compares a metric's readings to your own history " +
    'instead of the standard lab range — useful when a value is chronically ' +
    'outside range but normal for you. Flags still fire on a real change from ' +
    'your pattern; the lab range stays visible. Available per metric once it ' +
    `has at least ${MIN_COMPUTABLE_READINGS} readings — and suggested ` +
    `automatically once a metric is outside the lab range on more than ${pct}% ` +
    `of at least ${suggestMinReadings} such readings.`
  )
}
