// Shared value formatting so EVERY surface (chart ticks/tooltip, readings table,
// Expected/Normal column) shows all of a given metric's values with the SAME number
// of decimal places — e.g. Hemoglobin as 14.0 / 13.8 / 14.2, never a mix of "14"
// and "14.2". ONE decimal count PER METRIC, driven by the data's own precision and
// clamped so an odd reading can't explode label width. The chart takes the max of
// this and what its Y-axis ticks need to stay distinct (tickGapDecimals, chart-only);
// for real lab data the data precision dominates, so chart and table agree.

export const MAX_VALUE_DECIMALS = 4

// Decimal places in a number's own string form (2 for 1.05, 0 for 14).
// NOISE-TOLERANT: a derived value flows through as a raw float (rounding is display-
// side, so no drift enters a chained derivation), and binary-float subtraction yields
// e.g. 2.6999999999999997 for what is really 2.7. toPrecision(12) collapses that noise
// tail (JS floats carry ~15–17 significant digits) so the count reflects the value's
// TRUE precision — 2.7 -> 1 — while a genuinely precise reading like 1.005 (3) is
// unchanged. A repeating decimal from division (BUN:Cr 15.2941…) still counts high and
// clamps to MAX_VALUE_DECIMALS; that metric pins its own precision at the source.
export function decimalsOf(n) {
  if (n == null || !Number.isFinite(Number(n))) return 0
  const s = String(Number(Number(n).toPrecision(12)))
  const dot = s.indexOf('.')
  return dot === -1 ? 0 : s.length - dot - 1
}

export function maxDecimals(nums) {
  return nums.reduce((m, n) => Math.max(m, decimalsOf(n)), 0)
}

// Every displayable number in a metric's series: each row's value (numeric OR
// censored) plus its ref-range bounds — exactly the set the chart folds into its
// own precision, so the two can't disagree. Qualitative rows (value null) contribute
// nothing.
export function seriesNumbers(series) {
  const out = []
  for (const r of series ?? []) {
    if (r.value != null && Number.isFinite(Number(r.value))) out.push(Number(r.value))
    if (r.ref_low != null && Number.isFinite(Number(r.ref_low))) out.push(Number(r.ref_low))
    if (r.ref_high != null && Number.isFinite(Number(r.ref_high))) out.push(Number(r.ref_high))
  }
  return out
}

// One decimal count for a whole metric's values, from the data's precision, clamped.
export function seriesDecimals(series) {
  return Math.min(MAX_VALUE_DECIMALS, maxDecimals(seriesNumbers(series)))
}

// A formatter that renders any number at a fixed decimal count; non-numbers pass
// through as-is (so an operator/label around the number is preserved by the caller).
export function fixedFormatter(decimals) {
  return (v) => {
    const n = Number(v)
    return Number.isFinite(n) ? n.toFixed(decimals) : String(v ?? '')
  }
}
