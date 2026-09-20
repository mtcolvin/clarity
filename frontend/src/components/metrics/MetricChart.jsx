import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
  ReferenceArea,
  Tooltip,
  ResponsiveContainer,
  useYAxisScale,
  usePlotArea,
} from 'recharts'
import { useEffect, useState } from 'react'
import { maxDecimals, MAX_VALUE_DECIMALS } from '../../format'
import { useChartColors } from '../../theme'
import { parseLocalDate, padDomain, axisTicks, formatAxisTick } from './chartTime'
import { scaleSymlog } from 'd3-scale'
import { getChartScale, setChartScale } from '../../prefs'
import { chartableRows, hasBand } from './chartRows'
import ChartLegend from './ChartLegend'
import { InfoCircleIcon } from '../icons'

// Point-level flag kinds that are noteworthy but NOT out-of-range (e.g. unusual
// for you, a real delta, a threshold crossing) — a value can be flagged for
// these while sitting inside its reference range, so they get a distinct
// (amber) highlight rather than the out-of-range red. `trend` describes the
// whole series and highlights no single point.
const OTHER_POINT_KINDS = new Set(['personal_baseline', 'delta', 'threshold'])

// Point marks are SEMANTIC — red = outside the reference range, amber = noteworthy but
// inside it — and the hover dot reuses them, since a hovered out-of-range reading that
// turned accent-coloured would drop the one piece of information its mark carries.
//
// They now come from `useChartColors()` rather than being literals here: the MEANING is
// fixed, but the VALUE has to change with the ground, or the dark theme draws a dark red
// dot on a dark panel. Same rule as index.css's semantic tokens.

// Sliver of air below zero-valued dots; bounded so the -200/-2 proportional-pad
// class stays impossible (the floor is capped at this fraction of domain-top,
// never a fraction of the data range). Tune here.
const Y_FLOOR_MARGIN_FRAC = 0.05

// Per-metric value precision — ONE decimal count applied to EVERY value shown for a
// metric (Y-axis ticks, tooltip value, normal-range bounds, censored bound) so they
// all read with the same number of decimals within that metric (urine specific
// gravity everywhere as 1.005 / 1.010 / 1.030, never a mix of 1.03 and 1.005).
// valueDecimals (computed in the component) is the max of two needs:
//   - tickGapDecimals: enough decimals to keep the tightest pair of Y ticks distinct.
//     An integer-spaced-but-fractional axis would otherwise collapse — this is the
//     near-1.0 bug where the old toPrecision(3) turned 1.005 into "1", so a band
//     bottom at 1.005 looked like it started at 1.0.
//   - maxDecimals(data): the actual precision of the values + range bounds, so a
//     tooltip never truncates a reading.
// Clamped to <=MAX_VALUE_DECIMALS so float noise or an odd reading can't explode the
// label width. Fixed decimals (toFixed) also avoid sig-fig collapse and scientific
// notation, and trim the float noise the domain pad introduces.
// decimalsOf / maxDecimals / MAX_VALUE_DECIMALS are shared with the readings table
// via ../../format so both agree on a metric's decimal count (imported above).
function tickGapDecimals(ticks) {
  let minGap = Infinity
  for (let i = 1; i < ticks.length; i++) {
    const g = ticks[i] - ticks[i - 1]
    if (g > 1e-12) minGap = Math.min(minGap, g)
  }
  return Number.isFinite(minGap) ? Math.max(0, Math.ceil(-Math.log10(minGap))) : 0
}

// Round-number Y gridlines: multiples of {1,2,5} x 10^k that put a readable
// number of lines (target ~5-7, never more than 7) inside [lo, hi]. Whole numbers
// when the range allows; round decimals (0.1/0.2/0.5) when it doesn't — e.g. A1c
// lands on 5.0/5.5/6.0 rather than 5.4/5.7/6.0. Returns the ticks within [lo, hi].
// Log-axis gridlines: the 1/2/5 × 10^k values inside [lo, hi]. Used only in
// log-scale mode (an opt-in for outlier-heavy metrics); the linear path keeps
// niceTicks. Falls back to the raw bounds if the range spans less than a step.
function logTicks(lo, hi) {
  if (!(lo > 0 && hi > lo)) return []
  const ticks = []
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
    for (const m of [1, 2, 5]) {
      const v = m * Math.pow(10, e)
      if (v >= lo && v <= hi) ticks.push(+v.toFixed(10))
    }
  }
  return ticks.length ? ticks : [lo, hi]
}

function niceTicks(lo, hi, target = 6) {
  if (!(hi > lo)) return [lo]
  const mag = Math.pow(10, Math.floor(Math.log10((hi - lo) / target)))
  // Densest step (1<2<5<10 x mag) that keeps the count <= 7.
  let step = 10 * mag
  for (const m of [1, 2, 5, 10]) {
    const s = m * mag
    if (Math.floor(hi / s) - Math.ceil(lo / s) + 1 <= 7) {
      step = s
      break
    }
  }
  const ticks = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) {
    ticks.push(+v.toFixed(10)) // trim float drift (e.g. 0.1+0.2)
  }
  return ticks
}

// Censored arrow glyph: a capped arrow at the bound value. The horizontal cap
// sits exactly at the bound (so "<5" anchors at y=5); the arrow points AWAY from
// the cap toward where the true value lies — down for '<'/'<=' (at or below),
// up for '>'/'>=' (at or above). Muted grey: the value is uncertain, not an
// alarm. Distinguished from the personal-baseline hollow ring by shape.
function renderCensoredArrow({ cx, cy, payload, key }, bad, muted) {
  if (payload?.censored == null || cx == null || cy == null) return <g key={key} />
  const op = payload.operator
  const down = op === '<' || op === '<='
  const cap = `M ${cx - 5} ${cy} L ${cx + 5} ${cy}`
  const stem = down ? `M ${cx} ${cy} L ${cx} ${cy + 9}` : `M ${cx} ${cy} L ${cx} ${cy - 9}`
  const head = down
    ? `M ${cx - 4} ${cy + 5} L ${cx} ${cy + 9} L ${cx + 4} ${cy + 5}`
    : `M ${cx - 4} ${cy - 5} L ${cx} ${cy - 9} L ${cx + 4} ${cy - 5}`
  // Red when the engine DEFINITIVELY placed this censored reading outside its
  // normal range (item 6); otherwise the muted grey (uncertain, not flagged).
  const stroke = payload.flaggedOOR ? bad : muted
  return (
    <g
      key={key}
      stroke={stroke}
      strokeWidth={1.5}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={cap} />
      <path d={stem} />
      <path d={head} />
    </g>
  )
}

// `fmt` is the metric's shared value formatter (fixed decimals) so the range bounds
// match the value/tick decimals — see MAX_VALUE_DECIMALS above.
function rangeText(p, unit, fmt) {
  const lo = p?.ref_low, hi = p?.ref_high
  const hasLo = lo != null, hasHi = hi != null
  if (hasLo && hasHi) return `${fmt(lo)} – ${fmt(hi)} ${unit}`.trim()
  if (hasHi) return `≤ ${fmt(hi)} ${unit}`.trim()
  if (hasLo) return `≥ ${fmt(lo)} ${unit}`.trim()
  return ''
}

// Faithful relocation of the current formatter's per-entry logic; `fmt` is the
// metric's shared value formatter so every tooltip value has the same decimals.
// Returns { label, text } or null to suppress the row.
function formatEntry(entry, unit, fmt) {
  const val = entry?.value
  const p = entry?.payload
  if (entry?.dataKey === 'censored') {
    if (val == null) return null
    const op = p?.operator ?? ''
    const dir = op === '<' || op === '<=' ? 'at or below' : 'at or above'
    return { label: null, text: `${op}${fmt(val)} ${unit} — ${dir} the limit`.trim() }
  }
  if (entry?.dataKey === 'value') {
    if (val == null) return null
    return { label: 'value', text: `${fmt(val)} ${unit}`.trim() }
  }
  return null // ignore any other series (e.g. flaggedOOR marker)
}

// Custom tooltip content. Reproduces the old default-tooltip rows (value /
// censored) and adds a separate "Normal range" row read live from the hovered
// point's ref_low/ref_high (the retired <Area dataKey="range"> no longer feeds
// the tooltip a [low, high] tuple). Box chrome mimics the old default look.
function RangeTooltip({ active, payload, unit, fmt }) {
  if (!active || !payload?.length) return null
  const observedOn = payload[0]?.payload?.observed_on ?? ''
  const rows = payload
    .map((e) => formatEntry(e, unit, fmt))
    .filter(Boolean)
  const range = rangeText(payload[0]?.payload, unit, fmt)
  return (
    <div style={{
      background: 'var(--c-surface)',
      border: '1px solid var(--c-line)',
      color: 'var(--c-ink)',
      borderRadius: '3px',
      padding: '10px',
      whiteSpace: 'nowrap',
      fontSize: '0.875rem',
      lineHeight: 1.4,
    }}>
      {observedOn && <div style={{ marginBottom: 4, fontWeight: 'bold' }}>{observedOn}</div>}
      {rows.map((r, i) => (
        <div key={i}>{r.label ? `${r.label} : ${r.text}` : r.text}</div>
      ))}
      {range && <div>normal range : {range}</div>}
    </div>
  )
}

// Rail geometry — SHARED between the width reservation (margin.right) and the
// rail's own text placement, so the reserved gutter and where the text lands can
// never disagree.
const RAIL_GAP = 7 // px between the plot edge and the label start
const RAIL_CHAR_PX = 6.5 // fallback px/char at 11px if canvas measurement is unavailable
const RAIL_PAD = 8 // small safety pad on the far side of the widest label
const MARGIN_RIGHT_BASE = 24 // gutter when there are no threshold labels to host
// Capped/off-domain threshold labels carry a leading chevron-up glyph (drawn
// inline, not a Tabler import — this codebase has no icon lib). CAPPED_LABEL_INDENT
// (chevron width + gap) is SHARED between the rail's text shift and the marginRight
// allowance, so the reserved gutter always matches how far the label actually moves
// — same discipline as RAIL_GAP. CAPPED_TICK_LEN is the dashed guide-tick's height.
const CAPPED_CHEVRON_W = 9 // chevron glyph box width (px)
const CAPPED_CHEVRON_H = 4 // chevron apex rise (px); shrink both to scale the glyph
// Minimum spacing between Y tick LABELS, as a fraction of the domain. The plot is ~266px
// tall (320 less the margins and the X axis) and a label is 11px, so 5% ≈ 14px — enough
// to clear its neighbour without thinning a legitimately dense axis.
const MIN_TICK_GAP_FRAC = 0.05
// Log-mode headroom above the highest value, multiplicative because this axis pads by
// RATIO, not by amount. There is no matching pad BELOW: the scale is a SYMLOG, so its
// bottom is a real 0 (see the log branch) and 0 is where the axis should stop.
const LOG_PAD_UP = 1.3
// Air beneath 0 on the symlog axis, as a fraction of the axis's own (symlog) height —
// the counterpart of the linear path's sub-zero cosmetic floor, and computed in symlog
// space so it is the same visual gap whatever the metric's magnitude. A band that floors
// at 0 sits ON the 0 line rather than on the frame; no tick is generated below it, for
// the same reason linear's ticks start at 0 while its domain dips under.
const LOG_FLOOR_AIR = 0.04
const CAPPED_ICON_GAP = 4 // gap between the chevron and the label text (px)
const CAPPED_LABEL_INDENT = CAPPED_CHEVRON_W + CAPPED_ICON_GAP // 13px
const CAPPED_TICK_LEN = 9 // dashed guide-tick stub height (px)
// Stacked-row height for MULTIPLE capped labels. All off-top thresholds clamp to
// the same top edge, so 2+ of them (Calcium Corrected's 10/12/14) would overprint
// at one y. They're staggered DOWNWARD by this per-row step (~one 11px line +
// breathing room) so each reads on its own line in the right gutter.
const CAPPED_ROW_H = 15
// Match the rail <text>: 11px, inheriting the app's base family (index.css) — the
// rail text sets no font-family of its own, so measurement must use the same stack.
const RAIL_FONT = "11px system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"

// Measure a rail label's ACTUAL rendered width (px) via a cached canvas 2D
// context, instead of chars×constant. Proportional fonts make a long, mostly-
// lowercase source like "Endocrine Society 30" far narrower than its char count
// implies, so the flat estimate over-reserved the gutter for it; measuring the
// real glyphs sizes every metric's rail tightly. Falls back to the char estimate
// if canvas isn't available (non-DOM/test env).
let _railMeasureCtx = null
function measureLabelPx(text) {
  if (typeof document === 'undefined') return text.length * RAIL_CHAR_PX
  if (!_railMeasureCtx) {
    _railMeasureCtx = document.createElement('canvas').getContext('2d')
    _railMeasureCtx.font = RAIL_FONT
  }
  return _railMeasureCtx.measureText(text).width
}

// Width the rail needs = widest MEASURED label + the gap it starts after + a
// safety pad. Math.ceil keeps a round-up bias, and RAIL_PAD absorbs any small
// gap between the measurement font and the actual inherited family so the widest
// label never clips.
// Takes the rail's rendered LABEL STRINGS rather than thresholds, because the rail now
// also hosts the below-axis band-floor marker, which has no source and no cutoff.
function railWidth(labels) {
  const maxLabelPx = labels.reduce((m, t) => Math.max(m, measureLabelPx(t)), 0)
  return Math.ceil(maxLabelPx) + RAIL_GAP + RAIL_PAD
}

// Right-gutter label rail for guideline thresholds. Renders as a child of the
// chart so it can read the SAME y-scale the plot lines use (useYAxisScale) and
// the plot rect (usePlotArea) from the chart store — so a label re-tracks the
// domain/clamp/margin automatically, no parallel computation. Each threshold's
// text sits just right of the plot at its line's y-pixel, moving the in-plot
// label text OUT of the plot (the ReferenceLine itself stays). In-domain labels
// are grey (#495057), matching the removed inline threshold label; a CAPPED
// (off-domain) threshold instead renders an edge indicator — chevron + muted
// #868e96 label + dashed guide-tick (see the `above` branch). The personal-baseline
// label is deliberately NOT here (Option A — it stays inline, violet, in the plot).
function ThresholdRail({ thresholds, ink, line }) {
  const yScale = useYAxisScale()
  const plot = usePlotArea()
  if (!yScale || !plot || thresholds.length === 0) return null
  const x = plot.x + plot.width + RAIL_GAP // same RAIL_GAP the width calc reserves

  // Resolve each threshold to its y-pixel, then split by whether it's a CAPPED
  // (off-top) threshold. A capped threshold extrapolates to a y ABOVE plot.y, so it
  // would float/clip over the header; it's clamped to the top edge and marked as an
  // edge indicator instead (chevron + muted label + dashed guide-tick). In-domain
  // labels keep NO collision handling (the seeded metrics' in-domain cutoffs are
  // ~100px apart; TSH's tightest pair is the closest). The capped SET, however, all
  // clamps to the same top edge — so 2+ of them are STACKED (see below) rather than
  // overprinting. DEAD for every uncapped chart: pre-cap, domainTop is always >=
  // softMax, so no threshold is above the plot top.
  const rows = thresholds
    .map((t) => ({ t, y: yScale(t.cutoff), key: `rail-${t.source}-${t.cutoff}` }))
    .filter((r) => r.y != null)
  const inDomain = rows.filter((r) => r.y >= plot.y)
  // Stack order: highest cutoff first, so value order is preserved top-to-bottom
  // (higher cutoff sits physically higher) and the line NEAREST the domain (smallest
  // cutoff) lands closest to the plot content it nearly enters.
  const capped = rows.filter((r) => r.y < plot.y).sort((a, b) => b.t.cutoff - a.t.cutoff)

  return (
    <g className="threshold-rail">
      {/* One dashed guide-tick at the plot's top-right corner for the whole capped
          group — "these anchor here, at the top edge, not at a y-value". */}
      {capped.length > 0 && (
        <line
          x1={plot.x + plot.width}
          y1={plot.y}
          x2={plot.x + plot.width}
          y2={plot.y + CAPPED_TICK_LEN}
          stroke={line}
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      )}
      {inDomain.map(({ t, y, key }) => (
        <text
          key={key}
          x={x}
          y={y}
          fill={ink}
          fontSize={11}
          textAnchor="start"
          dominantBaseline="middle"
        >
          {`${t.source} ${t.cutoff}`}
        </text>
      ))}
      {capped.map(({ t, key }, i) => {
        // Stagger each capped label DOWN from the top edge by one row, so a group
        // (Calcium Corrected's 10/12/14) reads on separate lines instead of one
        // overprinted stack. chevron at baseY (top-aligned, hanging), text shifted
        // right by the shared CAPPED_LABEL_INDENT.
        const baseY = plot.y + i * CAPPED_ROW_H
        const chevCy = baseY + 5.5 // vertical center of the ~11px hanging label line
        return (
          <g key={key}>
            {/* chevron-up glyph, drawn inline (no icon lib) in the AppHeader style,
                centered on the label line so shrinking W/H keeps it aligned */}
            <path
              d={`M ${x} ${chevCy + CAPPED_CHEVRON_H / 2} l ${CAPPED_CHEVRON_W / 2} ${-CAPPED_CHEVRON_H} l ${CAPPED_CHEVRON_W / 2} ${CAPPED_CHEVRON_H}`}
              stroke={line}
              strokeWidth={1.25}
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            />
            <text
              x={x + CAPPED_LABEL_INDENT}
              y={baseY}
              fill={ink}
              fontSize={11}
              textAnchor="start"
              dominantBaseline="hanging"
            >
              {`${t.source} ${t.cutoff}`}
            </text>
          </g>
        )
      })}
    </g>
  )
}

// `legend` renders the legend directly under the chart (the default, and what every
// other caller wants). The Metrics page passes false and renders <ChartLegend> itself
// below the readings table — see ChartLegend.
export default function MetricChart({ series, flags, thresholds = [], personalBaselineMean = null, header = null, onDomainChange = null, legend = true }) {
  // Resolved from the CSS tokens once per theme change — see theme.js for why the chart
  // can't read `var(--x)` the way the rest of the app does.
  const C = useChartColors()
  const ACCENT = C.accent
  const BASELINE = C.baseline
  const BASELINE_SOFT = C.baselineSoft
  const OUT_OF_RANGE = C.outOfRange
  const NOTEWORTHY = C.noteworthy
  const BAND = C.band
  const GRID = C.grid
  // Chartable readings: NUMERIC (a real point) and CENSORED ("<5"/">100", drawn
  // as an arrow at its bound). Qualitative ("Positive") and range-as-text ("0-2")
  // have no Y position to plot — they stay "not charted" in the table (deferred;
  // see Roadmap). A censored reading needs its bound value AND an operator.
  // (A derived/computed metric arrives as plain numeric points — dates missing an
  // input are already omitted upstream — so it needs no special handling here.)
  const charted = chartableRows(series)
  // The chart renders only when there's at least one NUMERIC reading; a
  // censored-only metric is intentionally a no-chart case. Censored rows still
  // plot (as arrows) once the chart is up — they just can't bring it up alone.
  const hasNumeric = series.some((r) => (r.result_type ?? 'numeric') === 'numeric' && r.value != null)

  // Opt-in log Y-scale for outlier-heavy metrics — an extreme value (e.g. an AST
  // of 850 from an acute event) otherwise stretches the linear axis so the normal
  // reference band collapses to a sliver. The toggle only appears when it would
  // actually help (see logWorthwhile) and only when every plotted value is positive
  // (see canLog).
  //
  // REMEMBERED across visits (prefs.js, browser-local like the theme), because
  // switching to log is a way of LOOKING at a record you come back to, and having to
  // re-choose it every time made it feel like a novelty rather than a view. What is
  // stored is the PREFERENCE; whether it APPLIES is decided per chart below, so a
  // remembered "log" can never reach a chart that never offered the choice (the weight
  // chart, a metric with a narrow ratio).
  const [scalePref, setScalePref] = useState(getChartScale)

  function chooseScale(next) {
    setScalePref(next)
    setChartScale(next)
  }

  // Position points by their real date: add a numeric epoch-ms `t` so the X-axis
  // can use a time scale (a string dataKey would be categorical/evenly spaced).
  // Numeric and censored ride the same data array but on SEPARATE dataKeys:
  // `value` (numeric, drives the trend line + dots) vs `censored` (the bound,
  // drives the arrow layer). A row is exactly one of the two; the other key is
  // null, so neither series draws on the other's points.
  // ref_low/ref_high are read live by RangeTooltip; the range tuple + <Area> were retired in fb8ef65.
  //
  // chartData + the X-domain/tick block below are computed HERE — ahead of the
  // hasNumeric early return — for two reasons: (a) chartData is reused
  // throughout the rest of the render regardless, and (b) the domain needs to be
  // available before the useEffect call just below it (Rules of Hooks: a hook
  // can never sit after a conditional return). Guarded for an empty chartData
  // (a pure-qualitative-only metric, the common case, has none) so nothing
  // throws pre-return.
  const chartData = charted.map((r) => {
    const isCensored = (r.result_type ?? 'numeric') === 'censored'
    return {
      ...r,
      t: parseLocalDate(r.observed_on).getTime(),
      value: isCensored ? null : r.value,
      censored: isCensored ? r.value : null,
    }
  })

  const tMin = chartData.length ? chartData[0].t : null
  const tMax = chartData.length ? chartData[chartData.length - 1].t : null
  const xDomain = tMin != null ? padDomain(tMin, tMax) : null
  const domainStart = xDomain ? xDomain[0] : null
  const domainEnd = xDomain ? xDomain[1] : null
  const axis = tMin != null ? axisTicks(tMin, tMax) : null
  const xTicks = axis ? axis.ticks : []
  const step = axis ? axis.step : null
  const formatTick = (t) => formatAxisTick(t, step)

  // Report the computed X-domain up to the caller (MetricsPage), so the
  // qualitative timeline strip (#4) can align pixel-for-pixel with THIS chart
  // when both are showing for the same metric (the "mixed" case). Gated on
  // hasNumeric — not just "chartData is non-empty" — so a censored-only metric
  // (which has chartData but renders the empty state below, no visible chart)
  // never reports a domain nothing is actually drawn against.
  //
  // Deliberately depends on PRIMITIVES only (domainStart/domainEnd/step's unit
  // and size),
  // never onDomainChange/xDomain/xTicks: those are new references every render,
  // so including them would re-fire the effect every render and (since the
  // callback calls setState in the parent) loop. Reusing the SAME values on
  // re-render correctly does NOT re-fire this effect, which is what we want.
  useEffect(() => {
    if (hasNumeric && xDomain) {
      onDomainChange?.({ domain: xDomain, ticks: xTicks, step })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasNumeric, domainStart, domainEnd, step?.unit, step?.size])

  if (!hasNumeric) {
    return (
      <div className="chart">
        {header && <div className="chart__header">{header}</div>}
        <p className="muted">No numeric readings to chart for this metric.</p>
      </div>
    )
  }

  const numericPoints = chartData.filter((d) => d.value != null)
  const censoredPoints = chartData.filter((d) => d.censored != null)

  // Unit for the axis label/tooltip — the latest charted reading's unit (one
  // unit per metric is enforced on write, so this is consistent).
  const unit = chartData.at(-1)?.unit ?? ''

  // Map flags to the points they name, by observed_on. The backend now stamps
  // each point-level flag with its reading's date (out_of_range is judged per
  // reading against its own range), so a point is highlighted iff its own value
  // tripped a flag — out-of-range agrees with that point's stepped-band segment.
  // Flags without observed_on (trend) match no point. (Censored readings never
  // enter the engine's math, so they carry none of these flags.)
  const outOfRangeDates = new Set(
    flags.filter((f) => f.kind === 'out_of_range' && f.observed_on).map((f) => f.observed_on),
  )
  const noteworthyDates = new Set(
    flags.filter((f) => OTHER_POINT_KINDS.has(f.kind) && f.observed_on).map((f) => f.observed_on),
  )
  // Personal-baseline mode: out-of-lab-range readings consistent with the user's
  // own history are recontextualized (not an out-of-range concern). They get a
  // neutral hollow ring — distinct from the red out-of-range dot and the amber
  // noteworthy caret — so the information is shown, not deleted. A genuine break
  // from the pattern is a `personal_baseline` flag (amber caret), not this.
  const personalRangeDates = new Set(
    flags.filter((f) => f.kind === 'personal_range' && f.observed_on).map((f) => f.observed_on),
  )
  // Item 6: a censored reading the engine put DEFINITIVELY outside its normal
  // range carries an out_of_range flag on its date — stamp the point so its arrow
  // renders red. Ambiguous/in-range censored readings aren't in the set (stay grey).
  for (const d of censoredPoints) {
    d.flaggedOOR = outOfRangeDates.has(d.observed_on)
  }

  // Clinical reference-line Y values: threshold cutoffs (always) and the personal-
  // baseline mean (only when pb mode is on -> non-null). These are SOFT domain
  // inputs — included so their gridlines are never off-screen (a threshold outside
  // the domain is dropped by ifOverflow:'discard'), but they do NOT inflate the pad:
  // a far-away threshold would otherwise stretch the domain and squash the data+band.
  // RENDERING-only, like the censored bounds; no value here enters any computation.
  const thresholdYs = thresholds.map((t) => t.cutoff)
  const pbMean = personalBaselineMean
  const clinicalYs = [...thresholdYs, ...(pbMean != null ? [pbMean] : [])]

  // Y headroom — DATA-WEIGHTED. HARD inputs (the numeric values, censored arrow
  // anchors, and every displayed reference-range edge) drive both the extent and the
  // pad (~15%), so the data and band always sit comfortably on-screen regardless of
  // how far a threshold lies. The spreads no-op when a category is empty; the
  // degenerate single-point case falls back to |hardHi|*0.15 || 1.
  const numericValues = numericPoints.map((r) => r.value)
  const censoredBounds = censoredPoints.map((r) => r.censored)
  const refLows = chartData.map((r) => r.ref_low).filter((v) => v != null)
  const refHighs = chartData.map((r) => r.ref_high).filter((v) => v != null)
  const hardYs = [...numericValues, ...censoredBounds, ...refLows, ...refHighs]
  const hardLo = Math.min(...hardYs)
  const hardHi = Math.max(...hardYs)
  // Does the metric's own data genuinely reach below zero (a real negative reading or
  // band bound, e.g. Standard Base Excess ~ -2..+2, often negative)? This is DISTINCT
  // from a below-zero DOMAIN that's merely padding/centering artifact around
  // non-negative data (bilirubin/LDL bottoming at 0). The sub-zero cosmetic floor and
  // the "pin lowest tick at 0" rule both exist for the artifact case ONLY — when the
  // data truly lives below zero, the axis MUST extend there, so both are skipped.
  const dataGoesNegative = hardLo < 0
  const pad = hardHi > hardLo ? (hardHi - hardLo) * 0.15 : Math.abs(hardHi) * 0.15 || 1
  // (B) Minimum one-sided open extent. A one-sided band's open side reaches the
  // domain edge, so FLOOR that edge to at least MIN_OPEN_FRACTION past the bound — so
  // the in-range region shows and the fade has room rather than collapsing to a
  // sliver. ONE-SIDED ONLY: a both-bounds reading (both bounds present) contributes
  // to neither list, so its band keeps its exact [ref_low, ref_high] height. Folded
  // AFTER pad (not into the pad basis, same discipline as the SOFT split) and via
  // Math.min/max, so it only ever EXTENDS the edge — a data reading beyond the
  // minimum still wins and extends the band further (floor, never a clamp).
  const MIN_OPEN_FRACTION = 0.25 // tune on eyeball
  const highOnlyHighs = chartData
    .filter((r) => r.ref_high != null && r.ref_low == null)
    .map((r) => r.ref_high)
  const lowOnlyLows = chartData
    .filter((r) => r.ref_low != null && r.ref_high == null)
    .map((r) => r.ref_low)
  // high-only opens DOWNWARD -> floor the bottom; low-only opens UPWARD -> raise the top.
  const minOpenBottom = highOnlyHighs.length
    ? Math.min(...highOnlyHighs.map((b) => b * (1 - MIN_OPEN_FRACTION)))
    : Infinity
  const minOpenTop = lowOnlyLows.length
    ? Math.max(...lowOnlyLows.map((b) => b * (1 + MIN_OPEN_FRACTION)))
    : -Infinity
  // Base edges: the more extreme of the padded HARD extent and the (B) minimum-extent
  // floor. SOFT inputs (thresholds, pb mean) then extend an edge only if they lie
  // beyond it.
  const baseBottom = Math.min(hardLo - pad, minOpenBottom)
  const baseTop = Math.max(hardHi + pad, minOpenTop)
  const softMax = clinicalYs.length ? Math.max(...clinicalYs) : -Infinity
  const softMin = clinicalYs.length ? Math.min(...clinicalYs) : Infinity
  const topIsSoft = softMax > baseTop
  const bottomIsSoft = softMin < baseBottom
  // Cap a runaway soft TOP. When a threshold sits FAR above the data (R1 = how many
  // hard-data-spans of empty gap the softMax opens above hardHi), stretching the
  // domain up to it squashes the data+band into a sliver (Triglycerides' 500 over a
  // reading of 36; Glucose's 200; TSH's 10). Past CAP_RATIO we DON'T stretch: the top
  // falls back to the data-driven baseTop and the off-domain threshold becomes an
  // edge indicator (see ThresholdRail's clamped ↑ label). This also re-enables
  // centering below (the soft top is no longer meaningful), which reframes the data —
  // e.g. Cholesterol's centering pulls the top back up so its 240 lands in-domain
  // again, absorbing the cap. Guard the 0-denominator degenerate single-value hard
  // range: Infinity > CAP_RATIO still caps, correct when a threshold tops a lone reading.
  const CAP_RATIO = 0.85
  const R1 = hardHi > hardLo ? (softMax - hardHi) / (hardHi - hardLo) : Infinity
  const topCapped = topIsSoft && R1 > CAP_RATIO
  // When a SOFT value defines an edge, give it a SMALL breathing margin (a few % of
  // span) so the threshold line + label isn't jammed against the frame — but NOT the
  // full HARD pad, which would re-introduce the squash fix (c) removed. The margin
  // also keeps the threshold comfortably inside the domain, so ifOverflow:'discard'
  // never drops it (this replaces the old bare-epsilon nudge). No margin when the
  // HARD pad already sets the edge (don't double-pad).
  const SOFT_MARGIN_FRACTION = 0.04
  const provTop = topIsSoft ? softMax : baseTop
  const provBottom = bottomIsSoft ? softMin : baseBottom
  const softMargin = (provTop - provBottom) * SOFT_MARGIN_FRACTION
  let domainTop = topIsSoft && !topCapped ? softMax + softMargin : baseTop
  let domainBottom = bottomIsSoft ? softMin - softMargin : baseBottom
  // Post-domain centering. When NEITHER edge is SOFT-set (no far threshold / pbMean
  // forces asymmetry), a lone or low-spread reading can sit far off-center — e.g.
  // HDL's point ~88% up, because the bottom is anchored at the floor while the top
  // only hugs the data + pad. Rebalance by EXTENDING ONLY the tighter side so the
  // numeric-data extent is vertically centered. Targets the READINGS (numericValues),
  // not the HARD extent, so the band floor (e.g. HDL's 40) doesn't pull the target.
  // Extend-only: the larger room is preserved, the anchored bound/threshold never
  // moves, nothing clips. The gate is BOTH the fire condition and the safety check —
  // a far threshold that STAYS soft (e.g. LDL's 190, R1 below CAP_RATIO -> topIsSoft
  // but not topCapped) fails it and keeps the (c) + breathing-margin framing. But a
  // CAPPED top no longer defines a meaningful edge (the threshold is off-domain now),
  // so topCapped RE-ADMITS centering — reframing the squashed-then-capped data
  // (Cholesterol's centering pulls the top back to ~242, landing its 240 in-domain
  // again). Layers on top of (c), (B), and the margin.
  const CENTER_DEADZONE = 1.5 // only rebalance past this room-asymmetry ratio; tune on eyeball
  if ((!topIsSoft || topCapped) && !bottomIsSoft && numericValues.length) {
    const numericMin = Math.min(...numericValues)
    const numericMax = Math.max(...numericValues)
    const roomAbove = domainTop - numericMax
    const roomBelow = numericMin - domainBottom
    const ratio = Math.max(roomAbove, roomBelow) / Math.max(Math.min(roomAbove, roomBelow), 1e-9)
    if (ratio > CENTER_DEADZONE) {
      // Extend the tighter side to match the larger room, centering the data.
      if (roomAbove < roomBelow) domainTop = numericMax + roomBelow
      else domainBottom = numericMin - roomAbove
    }
  }
  // Sub-zero cosmetic floor — the FINAL operation on domainBottom, after every prior
  // reassignment (soft-min, centering). The axis is DATA-DRIVEN: a positive natural
  // floor is KEPT, never dragged down to 0. This is what stops a narrow reference band
  // sitting far above zero — sodium ~134–145, calcium ~8.4–10.2, hematocrit ~40.8–53
  // — from collapsing into a sliver at the top (the previous unconditional
  // Math.min(0, …) pinned EVERY axis to 0, squashing those bands). Metrics whose data
  // genuinely reaches at/below zero (ref_low 0 or near-zero values — bilirubin,
  // basophils, LDL's 0 floor) still have a negative natural floor, so they keep
  // anchoring near 0. Only THEN do we cap how far below 0 the domain dips — at
  // Y_FLOOR_MARGIN_FRAC of domain-TOP — giving a zero-valued dot a sliver of air
  // beneath it while making the -200/-2 class impossible (the dip is a fraction of
  // TOP, not 15% of the hard data RANGE).
  if (domainBottom < 0 && !dataGoesNegative) {
    domainBottom = Math.max(-(domainTop * Y_FLOOR_MARGIN_FRAC), domainBottom)
  }
  let yDomain = [domainBottom, domainTop]
  let yScaleType = 'linear'

  // Log-scale override. What matters for log is that the plotted POINTS (numeric
  // values + censored bounds) are positive — a log axis can't place 0/negatives.
  // A reference-BAND bound of 0 (a range like 0–50, common for ALT/enzymes) does NOT
  // disqualify log: the values are fine, and the band simply clamps its floor to the
  // log domain bottom when rendering (see the bandSegments clamp below). "Worthwhile"
  // only when the data spans a wide ratio (~4x+), so normal charts never sprout the
  // toggle. When active, discard the linear domain machinery above for a simple
  // multiplicatively-padded [min, max]; the band, thresholds, rail, dots and censored
  // arrows all map through the axis scale, so they follow with no extra work.
  const positiveHardYs = hardYs.filter((v) => v > 0)
  const plottedPoints = [...numericValues, ...censoredBounds]
  const canLog = plottedPoints.length > 0 && plottedPoints.every((v) => v > 0)
  const logWorthwhile = canLog && positiveHardYs.length > 0
                        && hardHi / Math.min(...positiveHardYs) >= 4
  // The preference APPLIES only where the toggle would be offered anyway. Deriving it
  // (rather than holding an on/off in state) is what makes a remembered "log" safe to
  // carry between metrics: a chart that doesn't qualify simply reads linear, with no
  // reset to remember to perform.
  const logScale = scalePref === 'log' && logWorthwhile
  // SYMLOG, not log. A plain log axis has no position for 0 — it is at negative infinity
  // — and a band that floors at 0 is ordinary here (ALT, bilirubin, LDL). Every way of
  // working around that was worse than the problem it solved: a hard edge at the clamped
  // floor asserts a bound nobody chose; a fade means an OPEN bound in this chart's own
  // vocabulary, and 0 is a defined one; an off-axis marker is a caret standing in for a
  // number we know exactly; and plotting 0 at ~1e-17 puts it seventeen decades below the
  // data (20 decades of axis instead of 2.35, ALT's readings squeezed into 8% of the
  // plot height).
  //
  // A symlog is LINEAR across a small region around 0 and logarithmic beyond it, so 0 is
  // a REAL POSITION and the band just draws to it. Nothing is faked and nothing needs a
  // legend. The price is one clause in the notice: spacing is ratio ABOVE the linear
  // region, not throughout.
  //
  // That region's width is the CONSTANT, set to the smallest positive bound on the chart
  // — the lowest value that means anything for this metric — so the compressed stretch
  // is exactly the part with nothing in it (ALT: 0–10) and the readings keep the room
  // (measured: 72% of the plot height, against 68% for the plain log axis that couldn't
  // draw the 0 at all).
  let ySymlog = null
  if (logScale) {
    const lo = Math.min(...positiveHardYs)   // smallest positive value/band bound
    const hi = Math.max(hardHi, ...clinicalYs.filter((v) => v > 0))
    const top = hi * LOG_PAD_UP
    // Invert the symlog transform to find the value whose distance BELOW 0 is
    // LOG_FLOOR_AIR of the axis: symlog(x) = log(1 + x/C), so x = C·((1 + top/C)^f − 1).
    // A symlog is defined for negatives (it is symmetric about 0), so this is a real
    // position on the scale rather than a clamp.
    const air = lo * (Math.pow(1 + top / lo, LOG_FLOOR_AIR) - 1)
    yDomain = [-air, top]
    ySymlog = scaleSymlog().constant(lo)
    yScaleType = 'symlog'
  }

  // Stepped reference band as per-segment areas. Group consecutive readings by
  // range SHAPE+bounds into contiguous runs; each ranged run becomes one
  // <ReferenceArea> below. A run spans the full width at the chart ends (x omitted
  // -> plot edge) and steps at the MIDPOINT between two readings whose ranges
  // differ; adjacent runs share that midpoint so their rects abut. A one-sided run
  // omits its open Y bound (-> plot edge) and fills with a fade gradient; a
  // both-bounds run is a solid [low, high]. A no-range run emits nothing, leaving
  // a gap. The single-reading case falls out: one run, both x ends omitted -> a
  // full-width band (or nothing, if it has no range).
  const EPS = 1e-9
  // Same range shape, null-aware (null bound matches null bound): a both-bounds-only
  // comparison would NaN on a one-sided range.
  const sameRangeShape = (a, b) => {
    const eq = (x, y) =>
      (x == null && y == null) || (x != null && y != null && Math.abs(x - y) <= EPS)
    return eq(a.ref_low, b.ref_low) && eq(a.ref_high, b.ref_high)
  }
  const bandSegments = []
  for (let i = 0; i < chartData.length; ) {
    let j = i // extend a run of consecutive same-range readings [i..j]
    while (j + 1 < chartData.length && sameRangeShape(chartData[j + 1], chartData[i])) j++
    const r = chartData[i]
    if (hasBand(r)) {
      const x1 = i === 0 ? undefined : (chartData[i - 1].t + chartData[i].t) / 2
      const x2 =
        j === chartData.length - 1 ? undefined : (chartData[j].t + chartData[j + 1].t) / 2
      let y1, y2, fill
      if (r.ref_low != null && r.ref_high != null) {
        y1 = r.ref_low // both bounds -> solid band
        y2 = r.ref_high
        fill = BAND
      } else if (r.ref_low != null) {
        // floor only -> solid at the floor, fading up to the open top. The open
        // bound is the data-space domain TOP (yDomain[1]), NOT an omitted bound:
        // omitting resolves to the pixel range extreme, which on the inverted
        // y-axis is the plot BOTTOM (data min) -> the rect would span the wrong way.
        y1 = r.ref_low
        y2 = yDomain[1]
        fill = 'url(#refRangeFadeUp)'
      } else {
        // ceiling only -> solid at the ceiling, fading down to the open bottom. Open
        // bound is the data-space domain BOTTOM (yDomain[0]) for the same reason.
        // Guarded at max(0, yDomain[0]): with the sub-zero cosmetic floor this keeps
        // the fade from bleeding below 0 (belt-and-suspenders — the sliver was already
        // in the transparent tail of refRangeFadeDown, but this makes it provable).
        y1 = dataGoesNegative ? yDomain[0] : Math.max(0, yDomain[0])
        y2 = r.ref_high
        fill = 'url(#refRangeFadeDown)'
      }
      // Log mode can't render a 0/negative band bound (e.g. a 0–50 range): clamp
      // both edges up to the log domain floor so the band still shows down to the
      // plot bottom. No-op in linear mode (bounds are already within its domain).
      bandSegments.push({ key: `band-${i}`, x1, x2, y1, y2, fill })
    }
    i = j + 1
  }

  // Y-axis ticks: the MEANINGFUL reference values (threshold cutoffs + band bounds,
  // within domain) ALWAYS get an axis tick so the scale reads the values that matter
  // (e.g. Cholesterol's 200 ceiling and 240 threshold), merged with round-number
  // ticks that fill the rest. A round tick that nearly coincides with a meaningful
  // value is dropped (the meaningful value owns that slot); the final pass dedupes
  // any remaining near-equal pair (e.g. a bound that equals a threshold). The
  // CartesianGrid line at a meaningful tick is hidden behind the threshold/bound line
  // drawn over it (grid zIndex << those).
  const collTol = (yDomain[1] - yDomain[0]) * 1e-4
  const inDomain = (v) => v >= yDomain[0] - collTol && v <= yDomain[1] + collTol
  const meaningfulYs = [...clinicalYs, ...refLows, ...refHighs].filter(inDomain)
  // Pin the lowest round tick at 0 (not the sub-zero cosmetic floor) so the axis
  // reads "0" at the bottom while the domain dips just below it for dot air — UNLESS
  // the data genuinely goes negative (SBE), where ticks must follow the real domain.
  const roundYs = niceTicks(dataGoesNegative ? yDomain[0] : Math.max(0, yDomain[0]), yDomain[1]).filter(
    (t) => !meaningfulYs.some((m) => Math.abs(t - m) < collTol),
  )
  // ZERO IS LABELLED WHENEVER THE AXIS REACHES IT. Whether a linear axis is zero-based
  // is the first thing a reader needs from it — it decides whether a doubling LOOKS like
  // a doubling — so 0 outranks every other tick and is added explicitly rather than left
  // to whichever list happens to produce it.
  //
  // It also has to SURVIVE, which is the part that was failing. ALT's band bounds (0 and
  // 10, on an 800-unit domain) are two ticks a few pixels apart; both were emitted, and
  // Recharts — which hides tick labels that would collide, keeping the later one — chose
  // to drop the 0. So the crowding is resolved HERE, in priority order, instead of being
  // left to a library rule that knows nothing about which value matters: 0 first, then
  // the meaningful reference values (band bounds, guideline cutoffs), then the round
  // fillers, each admitted only if it clears MIN_TICK_GAP_FRAC of the domain from every
  // tick already kept. ALT now reads 0 / 50 / 200 / … — the 10 loses, which costs
  // nothing: its band edge still draws, and its label was invisible either way.
  const tickGap = (yDomain[1] - yDomain[0]) * MIN_TICK_GAP_FRAC
  const zeroYs = inDomain(0) ? [0] : []
  const linearYTicks = [...zeroYs, ...meaningfulYs, ...roundYs]
    .reduce((kept, v) => (kept.some((k) => Math.abs(k - v) < tickGap) ? kept : [...kept, v]), [])
    .sort((a, b) => a - b)
  // Log mode uses decade (1/2/5×10^k) ticks instead of the linear round/meaningful mix.
  // Symlog ticks: 0 (a real position now), then the 1/2/5 decades from the linear
  // region's edge upward. Starting the decades AT the constant is what keeps them out of
  // the compressed stretch, where they would crowd into a few pixels.
  const yTicks =
    yScaleType === 'symlog'
      ? [0, ...logTicks(ySymlog.constant(), yDomain[1])]
      : linearYTicks
  // One precision for EVERY value on this metric's chart (ticks + tooltip value +
  // range bounds + censored bound) — max of what the ticks need to stay distinct and
  // the data's own precision, clamped. See the helpers above.
  const valueDecimals = Math.min(
    MAX_VALUE_DECIMALS,
    Math.max(
      tickGapDecimals(yTicks),
      maxDecimals([...numericValues, ...censoredBounds, ...refLows, ...refHighs]),
    ),
  )
  const fmtVal = (v) => v.toFixed(valueDecimals)

  const renderDot = ({ cx, cy, payload, key }) => {
    // Censored rows carry value=null, so they never get a numeric dot (their
    // arrow is drawn by the separate censored layer). Guard defensively.
    if (payload.value == null) return <g key={key} />
    const date = payload.observed_on
    // out-of-range (red) takes precedence: a solid red dot, no caret, even if the
    // point is also noteworthy. Sized just above the ordinary dot — enough to read as
    // "this one", not enough to become the loudest thing on the page.
    if (outOfRangeDates.has(date)) {
      return <circle key={key} cx={cx} cy={cy} r={4} fill={OUT_OF_RANGE} stroke={C.surface} strokeWidth={1.5} />
    }
    // Personal-baseline mode: a neutral hollow ring (grey outline, no fill) for an
    // out-of-lab-range reading that's within the user's established range — shown,
    // not deleted, and clearly not an alarm.
    if (personalRangeDates.has(date)) {
      return (
        <circle key={key} cx={cx} cy={cy} r={5} fill={C.surface} stroke={GRID} strokeWidth={2} />
      )
    }
    // Every other point keeps the uniform dot. A noteworthy-but-in-range point
    // (personal_baseline / delta / threshold) gets a small amber caret floating a
    // few px above it — clear of the dot and the line, so the dots stay uniform.
    const dot = <circle cx={cx} cy={cy} r={3} fill={ACCENT} stroke="none" strokeWidth={0} />
    if (noteworthyDates.has(date)) {
      // A SOLID triangle, not a stroked chevron: at this size a filled mark holds its
      // shape where an outline reads as a smudge. It points DOWN at the reading it
      // marks — its tip sits 4px above the dot's top edge, flat side up.
      const tipY = cy - 3 - 4
      const flatY = tipY - 5
      return (
        <g key={key}>
          {dot}
          <path
            d={`M ${cx - 4} ${flatY} L ${cx + 4} ${flatY} L ${cx} ${tipY} Z`}
            fill={NOTEWORTHY}
            stroke="none"
          />
        </g>
      )
    }
    return <g key={key}>{dot}</g>
  }

  // The hover dot: the same mark, one step larger, keeping the point's own colour.
  const renderActiveDot = ({ cx, cy, payload }) => {
    if (payload?.value == null || cx == null || cy == null) return null
    const date = payload.observed_on
    const fill = outOfRangeDates.has(date) ? OUT_OF_RANGE : ACCENT
    if (personalRangeDates.has(date)) {
      return <circle cx={cx} cy={cy} r={6} fill={C.surface} stroke={GRID} strokeWidth={2} />
    }
    return <circle cx={cx} cy={cy} r={5} fill={fill} stroke={C.surface} strokeWidth={1.5} />
  }

  // Right margin sizes to the rail's widest label (round-up bias, solo-only); with
  // no thresholds the rail is absent, so collapse to the base gutter and let the
  // plot reclaim the width. Uses the SAME RAIL_GAP the rail places its text after.
  // A capped threshold (cutoff above the domain top) renders with a leading chevron
  // in the rail, so its label lands CAPPED_LABEL_INDENT further right than railWidth
  // (text-only) reserves. Add that allowance so the widest capped label can't clip.
  // Matches ThresholdRail's `above` test (cutoff above the plot top) against yDomain[1].
  const anyCapped = thresholds.some((t) => t.cutoff > yDomain[1])
  const railLabels = thresholds.map((t) => `${t.source} ${t.cutoff}`)
  const marginRight =
    railLabels.length === 0
      ? MARGIN_RIGHT_BASE
      : railWidth(railLabels) + (anyCapped ? CAPPED_LABEL_INDENT : 0)

  // Show the Linear/Log switch only where it earns its place: a wide-ratio metric
  // (an outlier well above the rest) that's all-positive. `logWorthwhile` already
  // implies `canLog`, and `logScale` now implies `logWorthwhile`, so the old
  // "…|| logScale" clause (which existed so log could always be turned back off) can
  // no longer be the deciding term.
  const showLogToggle = logWorthwhile

  return (
    <div className="chart">
      {header && <div className="chart__header">{header}</div>}
      {/* No "Scale" label: the two options name themselves, and the group carries
          those words as its accessible name. */}
      {showLogToggle && (
        <div className="chart__scale-row">
          {/* The warning sits WITH the control that causes it, and only while it is in
              force. A log axis makes equal distances mean equal RATIOS, so a rise that
              looks modest can be a doubling — the one thing a reader carries over from
              every other chart in the app is that vertical distance means amount, and
              here it doesn't. Amber, because that is this app's "worth a look" colour,
              and short, because it is a caption on a control, not a finding. */}
          {logScale && (
            <p className="chart__logwarn">
              <InfoCircleIcon size={14} />
              {/* One clause, and it has to name the caveat the symlog buys 0 with:
                  spacing is ratio only ABOVE the linear region. Saying plain "spacing is
                  ratio" would be false near the bottom of the axis. */}
              <span><strong>Log scale.</strong> Spacing is ratio above the flat
                stretch near 0, not amount.</span>
            </p>
          )}
          <div className="chart__scale-toggle" role="group" aria-label="Y-axis scale">
            <button type="button" className={!logScale ? 'active' : ''}
                    aria-pressed={!logScale}
                    onClick={() => chooseScale('linear')}>Linear</button>
            <button type="button" className={logScale ? 'active' : ''}
                    aria-pressed={logScale}
                    onClick={() => chooseScale('log')}>Log</button>
          </div>
        </div>
      )}
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={chartData} margin={{ top: 16, right: marginRight, bottom: 8, left: 4 }}>
          {/* Reusable vertical fade gradients for one-sided bands: solid at the lab
              limit, transparent toward the open side. objectBoundingBox (the SVG
              default) maps each fade across its own segment's rect, so these two
              defs serve every one-sided segment of every metric. */}
          <defs>
            <linearGradient id="refRangeFadeUp" x1="0" y1="0" x2="0" y2="1">
              {/* floor only: solid from the floor (bottom) up through most of the
                  rect; fades to transparent only in roughly the top ~20% (open end). */}
              <stop offset="0%" stopColor={BAND} stopOpacity={0} />
              <stop offset="20%" stopColor={BAND} stopOpacity={1} />
              <stop offset="100%" stopColor={BAND} stopOpacity={1} />
            </linearGradient>
            <linearGradient id="refRangeFadeDown" x1="0" y1="0" x2="0" y2="1">
              {/* ceiling only: solid from the ceiling (top) down through most of the
                  rect; fades to transparent only in roughly the bottom ~20% (open end). */}
              <stop offset="0%" stopColor={BAND} stopOpacity={1} />
              <stop offset="80%" stopColor={BAND} stopOpacity={1} />
              <stop offset="100%" stopColor={BAND} stopOpacity={0} />
            </linearGradient>
          </defs>
          {/* syncWithTicks: draw grid lines ONLY at the axis ticks. Without it,
              Recharts' getCoordinatesOfGrid appends the plot's top/bottom edge
              coordinates as extra lines (getCoordinatesOfGrid pushes minValue/
              maxValue when syncWithTicks is false) — and the top-edge line lands
              ~1px above the topmost tick, so the two dashed lines overlap into one
              heavy-looking dashed line at the top border. Syncing to ticks removes
              those boundary lines and the doubling. */}
          <CartesianGrid strokeDasharray="3 3" syncWithTicks />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={xDomain}
            ticks={xTicks}
            interval={0}
            tickFormatter={formatTick}
            tick={{ fontSize: 11 }}
          />
          <YAxis
            // Size the axis to its actual tick labels (Recharts 3 auto width) rather
            // than the fixed ~60px default — otherwise a metric with short labels and
            // no thresholds (e.g. the dimensionless BUN:Cr ratio, whose right gutter
            // collapses to MARGIN_RIGHT_BASE) left a lopsidedly wide left margin.
            width="auto"
            // A d3 symlog INSTANCE when log is on (Recharts takes a scale function as
            // readily as a name), so 0 has a real position on it.
            scale={ySymlog ?? 'linear'}
            // In log mode the domain is computed to enclose the data, so hold it
            // exactly (allowDataOverflow) rather than let Recharts re-nice it.
            allowDataOverflow={yScaleType === 'symlog'}
            domain={yDomain}
            ticks={yTicks}
            // Render EVERY tick handed over. Recharts defaults to hiding labels it
            // judges to collide, keeping the later one — which is how ALT's 0 (a real
            // band bound, and the one value that says whether the axis is zero-based)
            // was being dropped in favour of a 10 nobody could read either. The spacing
            // is arbitrated above, in priority order, so the library's veto is now the
            // only thing that can lose a tick we deliberately kept.
            interval={0}
            tickFormatter={fmtVal}
            tick={{ fontSize: 11 }}
            label={
              unit
                ? { value: unit, angle: -90, position: 'insideLeft', dx: 8, style: { fontSize: 12 } }
                : undefined
            }
          />
          <Tooltip content={<RangeTooltip unit={unit} fmt={fmtVal} />} />
          {/* Stepped reference band: one <ReferenceArea> per contiguous same-range
              run (see bandSegments). Full-bleed at the chart ends, stepping at the
              midpoint where the range changes, with a faded open side for one-sided
              ranges. Declared before the gridlines and data line so it paints behind
              them; no-range runs emit nothing, leaving a gap. */}
          {bandSegments.map((seg) => (
            <ReferenceArea
              key={seg.key}
              x1={seg.x1}
              x2={seg.x2}
              y1={seg.y1}
              y2={seg.y2}
              fill={seg.fill}
              fillOpacity={0.2}
              stroke="none"
              ifOverflow="visible"
            />
          ))}
          {/* Censored arrows: an additional marker layer (no connecting line) at
              each censored reading's bound. Numeric rows have censored=null, so
              nothing is drawn there. */}
          {censoredPoints.length > 0 && (
            <Line
              dataKey="censored"
              stroke="none"
              dot={(props) => renderCensoredArrow(props, OUT_OF_RANGE, GRID)}
              activeDot={false}
              connectNulls={false}
              legendType="none"
              isAnimationActive={false}
            />
          )}
          {/* Clinical gridlines (paint over the band, under the data line).
              Threshold cutoffs: darker grey, SOLID by default. A line whose
              render_style is 'dashed' (a contested/soft cutoff, e.g. TSH 4.5) is
              drawn dashed so it reads as less firm than a flat cutoff; the reason
              is spelled out by its status_note in the legend. Labels are NO LONGER
              inline — they render in the right-gutter <ThresholdRail> below, out
              of the plot (SOURCE + number only, never a condition name). */}
          {thresholds.map((t) => (
            <ReferenceLine
              key={`thr-${t.cutoff}`}
              y={t.cutoff}
              stroke={C.accent}
              strokeWidth={1}
              strokeDasharray={t.render_style === 'dashed' ? '5 4' : undefined}
            />
          ))}
          {/* Right-gutter labels for the threshold lines above (Option A: the
              personal-baseline label stays inline, below). */}
          <ThresholdRail thresholds={thresholds} ink={ACCENT} line={GRID} />
          {/* Personal-baseline mean (pb mode only): a distinct muted-violet dashed
              line. Neutral label — the engine's computed mean, not "normal". */}
          {pbMean != null && (
            <ReferenceLine
              y={pbMean}
              stroke={BASELINE_SOFT}
              strokeWidth={1.5}
              strokeDasharray="5 4"
              label={{
                value: 'Personal baseline',
                position: 'insideBottomRight',
                fill: BASELINE,
                fontSize: 11,
              }}
            />
          )}
          <Line
            type="linear"
            dataKey="value"
            stroke={ACCENT}
            strokeWidth={2}
            dot={renderDot}
            // Recharts' default hover dot paints in the LINE's colour, which turned an
            // out-of-range reading graphite exactly when you pointed at it to read it.
            activeDot={renderActiveDot}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* The legend renders here by default; the Metrics page opts out and places
          <ChartLegend> below its readings table instead. Same inputs either way. */}
      {legend && (
        <ChartLegend
          series={series}
          flags={flags}
          thresholds={thresholds}
          personalBaselineMean={personalBaselineMean}
        />
      )}
    </div>
  )
}
