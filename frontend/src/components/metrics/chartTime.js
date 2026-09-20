// Shared time-axis utilities — extracted from MetricChart.jsx (pure refactor, no
// behavior change) so any other time-axis visual (e.g. the qualitative timeline
// strip, #4) computes calendar-aligned ticks IDENTICALLY, with no parallel
// implementation to drift out of sync. Every export here is a pure function or a
// frozen constant/formatter; none of this depends on React or Recharts.

// Parse an ISO date-only string as LOCAL midnight. `new Date("2023-02-01")`
// parses as UTC, which can render the previous day under negative offsets; this
// keeps date math/labels in the user's own timezone (matching the entry form).
export function parseLocalDate(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

// Candidate gridline intervals, in months, aligned to the calendar.
export const STEP_MONTHS = [1, 2, 3, 6, 12, 24, 60, 120]
// Sub-month intervals, for a span that holds NO month boundary. 30 days is the
// widest such span (anything longer must cross a 1st), so 14 is the largest step
// worth trying.
export const STEP_DAYS = [1, 2, 7, 14]
export const MAX_TICKS = 8

// X padding: widen a time domain a small fraction beyond [tMin, tMax] so an
// endpoint doesn't sit jammed against the frame (and its dot/arrow/marker isn't
// clipped at the edge). Degenerate single-point span (tMin === tMax) falls back
// to a fixed ~30-day pad so the lone point centers with room on both sides.
// Shared by MetricChart AND the qualitative timeline strip (#4), so a
// single-reading metric's strip pads identically to the chart's own
// degenerate-span fallback.
const X_PAD_FRACTION = 0.04
export function padDomain(tMin, tMax) {
  const xSpan = tMax - tMin
  const xPad = xSpan > 0 ? xSpan * X_PAD_FRACTION : 1000 * 60 * 60 * 24 * 30
  return [tMin - xPad, tMax + xPad]
}

export const monthYearFmt = new Intl.DateTimeFormat(undefined, { month: 'short', year: 'numeric' })
export const yearFmt = new Intl.DateTimeFormat(undefined, { year: 'numeric' })

// Pick the smallest calendar step that yields <= MAX_TICKS gridlines over the
// span (densest readable option without crowding); fall back to the largest.
function chooseStepMonths(spanMonths) {
  return (
    STEP_MONTHS.find((step) => spanMonths / step + 1 <= MAX_TICKS) ??
    STEP_MONTHS[STEP_MONTHS.length - 1]
  )
}

// Equidistant ticks at calendar-aligned boundaries (e.g. step 6 -> Jan & Jul)
// within [tMin, tMax]. Boundaries are independent of the data dates, so the
// gridlines are regular while points keep their true positions. Returns whatever
// lands — possibly nothing; choosing what to do about a thin result is
// axisTicks' job, not this one's.
function monthTicks(tMin, tMax, stepMonths) {
  const start = new Date(tMin)
  let am = start.getFullYear() * 12 + start.getMonth()
  am -= am % stepMonths // floor to the previous aligned boundary
  const ticks = []
  for (let cursor = am; ; cursor += stepMonths) {
    const t = new Date(Math.floor(cursor / 12), cursor % 12, 1).getTime()
    if (t > tMax) break
    if (t >= tMin) ticks.push(t)
  }
  return ticks
}

// Day-aligned ticks, for a span containing no month boundary at all. The
// anchor is the MONDAY on or before tMin, so a weekly step lands on week starts
// — the day-scale answer to "gridlines sit where the period actually begins",
// which is the whole point of this module. Stepping with setDate keeps every
// tick at LOCAL midnight across a DST boundary (adding 7 * 86400000 would not).
function dayTicks(tMin, tMax, stepDays) {
  const cursor = new Date(tMin)
  cursor.setHours(0, 0, 0, 0)
  cursor.setDate(cursor.getDate() - ((cursor.getDay() + 6) % 7)) // back up to Monday
  const ticks = []
  while (cursor.getTime() <= tMax) {
    const t = cursor.getTime()
    if (t >= tMin) ticks.push(t)
    cursor.setDate(cursor.getDate() + stepDays)
  }
  return ticks
}

// THE axis-tick entry point: pick the scale, then the ticks, in one place so a
// caller can't pair a step with ticks computed for a different one. Returns
// `{ ticks, step }` where step is `{ unit: 'month' | 'day', size }`.
//
// Months first, and a month tick wins as soon as ONE lands. The bar was `>= 2`,
// which is what sent a 36-day span (Home's weight chart: one month boundary) to
// the day tier and drew WEEKLY gridlines on a chart whose gridlines are supposed
// to mark month starts. A single gridline at a real month start is the right
// answer for that span — sparse, but true; two week lines are neither.
//
// Worth being precise about what the original bug was, since the threshold has
// now moved twice: a series running 2026-06-21 → 2026-07-27 contains exactly one
// month boundary, the `>= 2` test rejected it, and the fallback drew gridlines
// at the first and last READING while still labelling them "Jun 2026" /
// "Jul 2026" — two lines claiming to be month starts that were nothing of the
// kind. The defect was the LABEL, not the count, and this is the direct fix.
//
// The DAY tier survives for the span that contains NO month boundary at all
// (a fortnight inside one month), where there is no month start to draw and an
// axis with no ticks tells you nothing about when you are looking at.
export function axisTicks(tMin, tMax) {
  const spanMonths = (tMax - tMin) / (1000 * 60 * 60 * 24 * 30.44)
  const monthSize = chooseStepMonths(spanMonths)
  const monthly = monthTicks(tMin, tMax, monthSize)
  if (monthly.length >= 1) return { ticks: monthly, step: { unit: 'month', size: monthSize } }

  for (const size of STEP_DAYS) {
    const ticks = dayTicks(tMin, tMax, size)
    if (ticks.length >= 2 && ticks.length <= MAX_TICKS) return { ticks, step: { unit: 'day', size } }
  }

  // Nothing lands: a single-reading series (tMin === tMax, deduped to one tick)
  // or a span under a day. Keep the endpoints so the axis still says which dates
  // it covers, and label them as the specific dates they are.
  return { ticks: [...new Set([tMin, tMax])], step: { unit: 'day', size: 1 } }
}

// Format a tick for the step that produced it. A MONTH/YEAR tick is a period
// label, which the date charter's one exception allows in natural language; a
// DAY tick is a specific date, so it renders `YYYY-MM-DD` like every other date
// in the app.
export function formatAxisTick(t, step) {
  if (step.unit === 'day') {
    const d = new Date(t)
    const p = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  }
  return (step.size >= 12 ? yearFmt : monthYearFmt).format(t)
}
