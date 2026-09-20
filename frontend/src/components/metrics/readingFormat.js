// How a stored reading READS — shared by the readings table and the metric rail, so a
// value shown in two places can never be formatted two ways. Lives in its own module
// (not in ObservationTable) because a component file may only export components.
// The decimal count itself comes from ../../format (seriesDecimals/fixedFormatter);
// these functions take the resulting `fmt` so every caller uses the same precision.

// The value WITHOUT its unit — the metric rail sets the number and the unit at
// different sizes, so it needs them apart. displayValue is this plus the unit, so
// there is still only one place that decides how a result of each type reads.
export function valueOnly(r, fmt) {
  const type = r.result_type ?? 'numeric'
  if (type === 'qualitative') return r.value_text ?? ''
  if (type === 'censored') return `${r.operator ?? ''}${fmt(r.value)}`
  if (r.value == null) return '—' // defensive: a numeric row with no value has nothing to show
  return fmt(r.value)
}

export function displayValue(r, fmt) {
  const text = valueOnly(r, fmt)
  const type = r.result_type ?? 'numeric'
  if (type === 'qualitative' || text === '—') return text
  return `${text}${r.unit ? ' ' + r.unit : ''}`
}

// Exported so the metric rail can state the latest reading and its interval in the
// EXACT words the table uses — one formatter, no second implementation to drift.
// The expected-normal, per type: qualitative shows its normal_text; numeric and
// censored show their ref_low/ref_high range, honoring any bound operators —
// a one-sided censored normal reads as "≤10" / "≥5", a strict bound in a
// two-sided range shows inline (">5–10"), inclusive two-sided stays "5–10".
// Bounds use the same `fmt` so they match the value column's precision.
export function displayNormal(r, fmt) {
  if ((r.result_type ?? 'numeric') === 'qualitative') return r.normal_text || '—'
  const { ref_low: lo, ref_high: hi, ref_low_operator: loOp, ref_high_operator: hiOp } = r
  if (lo == null && hi == null) return '—'
  if (lo != null && hi != null) {
    return `${loOp === '>' ? '>' : ''}${fmt(lo)} – ${hiOp === '<' ? '<' : ''}${fmt(hi)}`
  }
  if (hi != null) return `${hiOp === '<' ? '<' : '≤'}${fmt(hi)}`
  return `${loOp === '>' ? '>' : '≥'}${fmt(lo)}`
}
