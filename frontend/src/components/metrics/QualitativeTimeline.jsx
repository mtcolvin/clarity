import { parseLocalDate, padDomain, axisTicks, formatAxisTick } from './chartTime'

// Free-text qualitative values (e.g. a culture result) truncate here, full text
// in the badge's `title` attribute.
const TRUNCATE_LEN = 30

// Nominal SVG coordinate space; scales to 100% width via viewBox (no resize
// listener needed). Kept small — this is a compact strip, not a full chart.
const VIEW_W = 800
const VIEW_H = 76
const MARGIN_X = 16
const AXIS_Y = 50
// Approx y where a .qual-badge's bottom edge sits (top:4px + ~20px rendered
// height) — the connector's start point.
const BADGE_BOTTOM_Y = 24
// Two elbow connectors whose horizontal BRIDGE segments overlap in x — which
// happens whenever their badge/dot pair straddle each other, exactly the close-
// together case the elbow exists to disambiguate — would coincide and read as
// ONE line if both bridges sat at the same y (found in testing). Each bridge is
// assigned the lowest row (0, 1, 2, ...) that doesn't x-overlap any
// already-placed bridge, staggering the row vertically by ELBOW_ROW_GAP so
// overlapping bridges are visibly distinct lines. Sized for up to 3 rows
// (24+6=30, 36, 42, all comfortably clear of AXIS_Y=50) — this app's real
// qualitative data caps at 2-3 readings per metric, so 3+ SIMULTANEOUSLY
// overlapping bridges is not expected; revisit the row cap if that changes.
const ELBOW_ROW_GAP = 6

// A badge's approximate HALF-width, as a % of the strip's rendered width (not
// nominal-space px — badges are real HTML with a real CSS pixel width, so a
// nominal-space constant wouldn't guarantee actual non-overlap across
// different container widths; percentage keeps the math in the SAME unit the
// badges are already positioned in). Scaled by the DISPLAYED text's length
// rather than one flat worst-case constant — found necessary in testing: a
// blanket constant sized for the longest real value ("Non-Reactive", 12 chars)
// pushed even a short pair ("Positive"/"Negative", 8 chars) needlessly far
// apart, since the elbow connector (with its own bridge-row collision
// detection, above) already disambiguates regardless of distance — the ONLY
// remaining reason two badges need separation is to not overlap as BOXES,
// which scales with their own text, not the dataset's longest value.
// Calibrated from ACTUAL measured badge widths in testing (still felt too
// generous at the first pass — that version modeled a badge's real pixel width
// LOOSER than it actually renders): .qual-badge's fixed horizontal padding is
// 2 x 0.55rem =~ 17.6px, and its 0.78rem bold text averages ~6px/character.
// Converted to % of the narrowest container observed (~583px): half of
// (17.6 + 6*len)/2 -> ~1.5% base + ~0.5%/char. A 12-char worst case
// ("Non-Reactive") still lands at ~7.5% half-width, comfortably enough to
// avoid overlapping another long badge; shorter real values scale down from
// there, closer to what they actually need.
const BADGE_HALF_WIDTH_BASE_PCT = 1.5
const BADGE_HALF_WIDTH_PER_CHAR_PCT = 0.5
function badgeHalfWidthPct(text) {
  return BADGE_HALF_WIDTH_BASE_PCT + BADGE_HALF_WIDTH_PER_CHAR_PCT * text.length
}
// Small visual breathing room beyond exact edge-to-edge touching, added on top
// of the two badges' (or one badge + the container edge's) computed half-widths
// — the x-axis counterpart to ELBOW_GAP_TOLERANCE below (that one buffers the
// y-row collision check; this one buffers actual badge placement on x).
const BADGE_BUFFER_PCT = 2

// The smallest row (0, 1, 2, ...) NOT in `usedRows` — a pure, non-mutating scan
// (recursion instead of a mutable counter, to stay render-pure). Mirrors
// ThresholdRail's "lowest free row" collision-avoidance idea (MetricChart.jsx),
// applied here to elbow-connector bridge rows instead of rail labels.
function firstFreeRow(usedRows, row = 0) {
  return usedRows.includes(row) ? firstFreeRow(usedRows, row + 1) : row
}

// A compact time axis for qualitative / no-Y-value results (Positive/Negative/
// Yellow/... — #4). Renders below the numeric chart when one exists for this
// metric (the MIXED case — today only Urine Protein), or standalone when it
// doesn't (the COMMON case — 23 of 24 qualitative-carrying metrics have zero
// numeric readings, ever, so MetricChart shows only its empty-state text and
// this strip is the only visual). Reuses the SAME calendar-tick machinery
// (chartTime.js) MetricChart uses, so ticks read identically everywhere; a
// neutral marker + badge per reading, no color-coded valence (see CLAUDE.md
// surface-not-diagnose — there's no deterministic signal to hang "good/bad" on
// a qualitative value without per-metric clinical judgment this app doesn't do).
//
// Label placement: the DOT always sits at a reading's TRUE date position —
// never moved, never approximated. The BADGE is what floats: readings arrive
// chronological (oldest first), swept left-to-right, and a badge is pushed
// right of its true position only far enough to clear ITS OWN and its
// neighbor's text-width from overlapping (badgeHalfWidthPct, below) — never
// more than that. A dashed leader line always runs from the badge down to its
// own dot, vertical when untouched, diagonal when nudged — so which badge
// belongs to which point stays unambiguous no matter how close two readings'
// true dates are (found necessary in testing: an earlier vertical-row-stagger
// design kept badges at their true x, so two close-in-time badges still
// visually overlapped as BOXES even on different rows — moving the read
// position, not just its row, is what actually separates them).
//
// `sharedAxis` — when provided (the mixed case), it's MetricChart's OWN
// computed { domain, ticks, step }, reported up via its onDomainChange —
// so the strip's DATE MAPPING matches the chart above it exactly (same domain,
// same calendar ticks) WHENEVER that domain actually covers every qualitative
// reading here (checked below — it can be narrower than this metric's full
// qualitative history, e.g. one numeric reading pads only ~30 days; trusting
// it blindly would position an out-of-window reading's badge off-screen). Its
// own margins/plot width are independent of MetricChart's adaptive right-
// margin (the threshold rail) — that's a deliberate simplification, not an
// attempt at literal shared-pixel-rect alignment, which would need reading
// MetricChart's actual plot geometry.
// Absent (or insufficient), the strip computes its own domain from ITS OWN
// qualitative dates via the same padDomain/chooseStepMonths/calendarTicks
// chain MetricChart uses internally — so a lone standalone reading still gets
// the chart's same ~30-day degenerate-span pad, never a bare floating badge
// with no time reference, and no reading is ever silently dropped off-strip.
export default function QualitativeTimeline({ series, sharedAxis = null }) {
  const readings = series
    .filter((r) => r.result_type === 'qualitative')
    .map((r) => {
      const value_text = r.value_text ?? ''
      const truncated = value_text.length > TRUNCATE_LEN
      return {
        observed_on: r.observed_on,
        value_text,
        // The DISPLAYED text — what actually renders and takes up badge width
        // (and so drives the spacing math below), distinct from the full text
        // kept for the title tooltip.
        displayText: truncated ? `${value_text.slice(0, TRUNCATE_LEN)}…` : value_text,
        truncated,
        t: parseLocalDate(r.observed_on).getTime(),
      }
    })

  if (readings.length === 0) return null

  // sharedAxis is trusted ONLY when it covers EVERY qualitative reading here —
  // found necessary in testing: the chart's own numeric domain can be much
  // narrower than this metric's full qualitative history (e.g. a single
  // numeric reading pads only ~30 days, while a qualitative reading from years
  // earlier is also on this metric) — silently trusting a too-narrow shared
  // domain positions the out-of-window reading's badge at a wild off-screen
  // percentage, invisibly dropping real data. Never acceptable; fall back to
  // computing this strip's OWN domain (which always covers all of its own
  // readings, same as the standalone case) rather than lose anything.
  const sharedCoversAll = sharedAxis
    && readings.every((r) => r.t >= sharedAxis.domain[0] && r.t <= sharedAxis.domain[1])

  let domain, ticks, step
  if (sharedCoversAll) {
    domain = sharedAxis.domain
    ticks = sharedAxis.ticks
    step = sharedAxis.step
  } else {
    const tMin = readings[0].t
    const tMax = readings[readings.length - 1].t
    domain = padDomain(tMin, tMax)
    ;({ ticks, step } = axisTicks(tMin, tMax))
  }

  const x = (t) => MARGIN_X + ((t - domain[0]) / (domain[1] - domain[0])) * (VIEW_W - 2 * MARGIN_X)
  const pct = (t) => (100 * x(t)) / VIEW_W

  // Two-pass declutter (both immutable reduces — no mutable running variable,
  // to stay render-pure). The required gap between any two adjacent badges is
  // computed FROM THEIR OWN text (badgeHalfWidthPct of each, summed, plus a
  // small buffer) — not a flat worst-case constant — so a short pair sits much
  // closer than a long pair would need to.
  //
  // Pass 1 (left-to-right): a badge's position is its TRUE position unless
  // that's within the required gap of the previous (already-placed) badge, in
  // which case it's pushed right just far enough to clear it.
  //
  // Pass 2 (right-to-left): found necessary in testing — a cluster near the
  // END of the domain has nowhere to push RIGHT into, so pass 1 alone can
  // shove a badge past 100% (off-screen). Pass 2 pulls such a cluster back
  // inward: the rightmost badge is clamped inside the container (by its OWN
  // half-width), and each earlier one is kept at least the required gap to the
  // left of its (already-corrected) right neighbor — compressing the group
  // inward rather than letting it run off the edge. A badge pulled left of its
  // true position simply gets a leader line that leans the other way; still an
  // honest, traceable connection to its own dot.
  const forward = readings.reduce((acc, r) => {
    const truePct = pct(r.t)
    const prev = acc[acc.length - 1]
    const gap = prev
      ? badgeHalfWidthPct(prev.displayText) + badgeHalfWidthPct(r.displayText) + BADGE_BUFFER_PCT
      : 0
    const badgePct = prev ? Math.max(truePct, prev.badgePct + gap) : truePct
    return [...acc, { ...r, truePct, badgePct }]
  }, [])
  const placed = forward.reduceRight((acc, r) => {
    const next = acc[0]
    const maxAllowed = next
      ? next.badgePct - (badgeHalfWidthPct(r.displayText) + badgeHalfWidthPct(next.displayText) + BADGE_BUFFER_PCT)
      : 100 - badgeHalfWidthPct(r.displayText) - BADGE_BUFFER_PCT
    return [{ ...r, badgePct: Math.min(r.badgePct, maxAllowed) }, ...acc]
  }, [])

  // Elbow bridge-row assignment (immutable reduce, same style as the two
  // passes above): each connector's bridge spans [badgeX, dotX] (whichever
  // order). Found in testing that two connectors whose bridges x-overlap —
  // exactly the close-together case the elbow exists to disambiguate — read as
  // ONE line when both bridges sit at the same y. Each gets the lowest row
  // that doesn't x-overlap any bridge already placed at that row.
  //
  // The overlap check pads each span by ELBOW_GAP_TOLERANCE before comparing —
  // found necessary in testing (a REGRESSION from tightening the badge
  // spacing above): with badges now sitting much closer to their true
  // positions, two bridges can end up merely ADJACENT rather than literally
  // overlapping (e.g. spans [652,746.8] and [748,755.6] — technically
  // non-overlapping by ~1 nominal px), so a strict interval check placed both
  // at row 0 and they read as one line anyway. Padding the comparison treats
  // "close enough to be visually indistinguishable" as a collision too, not
  // just literal overlap.
  const ELBOW_GAP_TOLERANCE = 20
  const withElbows = placed.reduce((acc, r) => {
    const badgeX = (r.badgePct / 100) * VIEW_W
    const dotX = x(r.t)
    const lo = Math.min(badgeX, dotX)
    const hi = Math.max(badgeX, dotX)
    const overlappingRows = acc
      .filter((p) => !(p.hi + ELBOW_GAP_TOLERANCE < lo || hi + ELBOW_GAP_TOLERANCE < p.lo))
      .map((p) => p.elbowRow)
    const elbowRow = firstFreeRow(overlappingRows)
    return [...acc, { ...r, badgeX, dotX, lo, hi, elbowRow }]
  }, [])

  return (
    <div className="qual-timeline">
      <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} width="100%" height={VIEW_H} preserveAspectRatio="none">
        <line x1={MARGIN_X} y1={AXIS_Y} x2={VIEW_W - MARGIN_X} y2={AXIS_Y} stroke="#e9ecef" strokeWidth={1} />
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} y1={AXIS_Y} x2={x(t)} y2={AXIS_Y + 6} stroke="#ced4da" strokeWidth={1} />
            <text x={x(t)} y={AXIS_Y + 18} fontSize={11} fill="#868e96" textAnchor="middle">
              {formatAxisTick(t, step)}
            </text>
          </g>
        ))}
        {/* Jointed (elbow) leader line from each badge down to its OWN dot's
            true position: a short vertical stub from the badge, a horizontal
            bridge, then a vertical drop into the dot — degenerates to a plain
            vertical line when the badge wasn't nudged (badgeX === dotX, all
            three segments collinear). Found necessary in testing: one long
            straight diagonal, when a badge sits far from its dot to avoid
            overlapping a neighbor, reads as the badge floating disconnected
            rather than as an intentional callout — the elbow's horizontal
            segment makes "this connects to that" explicit regardless of how
            far apart they are. The bridge ROW (elbowRow, assigned above) keeps
            two overlapping bridges from coinciding into what reads as one
            line — each path still starts at a DIFFERENT x (its own badge) and
            ends at a DIFFERENT x (its own dot), so two close dots stay
            unambiguous. */}
        {withElbows.map((r) => {
          const elbowY = BADGE_BOTTOM_Y + ELBOW_ROW_GAP + r.elbowRow * ELBOW_ROW_GAP
          return (
            <path
              key={`conn-${r.observed_on}`}
              d={`M ${r.badgeX} ${BADGE_BOTTOM_Y} L ${r.badgeX} ${elbowY} L ${r.dotX} ${elbowY} L ${r.dotX} ${AXIS_Y}`}
              fill="none"
              stroke="#adb5bd"
              strokeWidth={1}
              strokeDasharray="2 2"
            />
          )
        })}
        {withElbows.map((r) => (
          <circle key={r.observed_on} cx={r.dotX} cy={AXIS_Y} r={3} fill="#868e96" />
        ))}
      </svg>
      <div className="qual-timeline__badges">
        {placed.map((r) => (
          <span
            key={r.observed_on}
            className="qual-badge qual-timeline__badge"
            style={{ left: `${r.badgePct}%` }}
            title={r.truncated ? r.value_text : undefined}
          >
            {r.displayText}
          </span>
        ))}
      </div>
    </div>
  )
}
