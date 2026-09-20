// Hand-drawn inline SVGs shared across the personal-baseline discoverability
// surfaces (BaselineMode's on-state/quiet-link, the Settings explainer block,
// and the Metrics-page auto-once popup). No icon library — stroke-based, round
// caps/joins, matching the app's existing inline-SVG convention (e.g.
// AppHeader's hamburger icon). They inherit `currentColor`, so the accent comes
// from CSS (.baseline__icon) rather than a hardcoded hex — see the tokens in
// index.css.
//
// Lifted out of BaselineMode.jsx (rather than left local there) once a second
// consumer — the Settings panel, a different feature directory — needed the
// same icon: a shared top-level module avoids a cross-feature import into
// components/metrics and gives Step 5's popup a third consumer for free.

function baseProps(size) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: '2',
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': 'true',
  }
}

// Multi-line callouts nudge the icon down (`offset`) to align with the first
// text line's cap-height; a single-line context (the quiet link) leaves it
// centered instead.
function iconClassName(offset) {
  return `baseline__icon${offset ? ' baseline__icon--offset' : ''}`
}

// Health glyph — a SOLID heart with a plus-shaped CUTOUT in the top-right lobe
// (the universal "health"/medical symbol; replaces the earlier person-with-heart).
// FILLED, not stroked, so it overrides baseProps' fill/stroke: the plus is negative
// space via fill-rule="evenodd" (the inner plus subpath punches a hole), showing the
// baseline container through it. Inherits currentColor like the rest. Marks the
// personal-baseline surface.
export function HealthIcon({ size = 17, offset = false }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      stroke="none"
      aria-hidden="true"
      className={iconClassName(offset)}
    >
      <path
        fillRule="evenodd"
        d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z M16.1 5 h1.5 v1.35 h1.35 v1.5 h-1.35 v1.35 h-1.5 v-1.35 h-1.35 v-1.5 h1.35 z"
      />
    </svg>
  )
}

export function InfoCircleIcon({ size = 17, offset = false }) {
  return (
    <svg {...baseProps(size)} className={iconClassName(offset)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <path d="M12 8h.01" />
    </svg>
  )
}

// External-link arrow — the export handoff (CLAUDE.md "The export handoff"),
// distinct from the personal-baseline health glyph: this surface sends a
// metric's picture OFF the machine, so it gets its own "leaving" mark rather
// than reusing an icon whose meaning is "your own history."
export function ExportIcon({ size = 17, offset = false }) {
  return (
    <svg {...baseProps(size)} className={iconClassName(offset)}>
      <path d="M7 17 17 7" />
      <path d="M8 7h9v9" />
    </svg>
  )
}

// External-link glyph — a box with an arrow leaving the top-right corner — for
// OUTBOUND citation links (e.g. "View WHO guideline on haemoglobin…"). Uses
// currentColor (not the fixed-violet baseProps) so it inherits the link's color
// and hover, and sits inline after the link text.
export function ExternalLinkIcon({ size = 13 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ verticalAlign: '-1px', marginLeft: '3px' }}
    >
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h6" />
    </svg>
  )
}

// Lightbulb — "model thinking": reasoning beyond the cited facts. Used by the
// export handoff's result tier as its "model reasoning" glyph (it carried over
// from the removed InterpretationPanel, which used the same mark for the same
// meaning). Deliberately not sharp/angular (no triangle, no
// exclamation) — this marks thinking, never a warning.
export function LightbulbIcon({ size = 16, offset = false }) {
  return (
    <svg {...baseProps(size)} className={iconClassName(offset)}>
      <path d="M9 18h6" />
      <path d="M10 22h4" />
      <path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2.3h6c0-1.1.4-1.8 1-2.3A7 7 0 0 0 12 2Z" />
    </svg>
  )
}

// Toggle glyphs for the timeline's view switch. Both use currentColor (not the fixed
// violet) so they invert with the button — dark on the inactive white pill, white on
// the active violet one. `strokeProps` mirrors baseProps but inherits color.
function strokeProps(size) {
  return {
    width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: '2', strokeLinecap: 'round',
    strokeLinejoin: 'round', 'aria-hidden': 'true',
  }
}

// Timeline view — a bulleted list of rows (a dot + a line, three deep), echoing the
// timeline's dot-and-entry rhythm. Reads clearly as "list/feed" at 18px.
export function TimelineViewIcon({ size = 18 }) {
  return (
    <svg {...strokeProps(size)}>
      <circle cx="5" cy="6" r="1.6" fill="currentColor" stroke="none" />
      <line x1="9" y1="6" x2="19" y2="6" />
      <circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none" />
      <line x1="9" y1="12" x2="19" y2="12" />
      <circle cx="5" cy="18" r="1.6" fill="currentColor" stroke="none" />
      <line x1="9" y1="18" x2="19" y2="18" />
    </svg>
  )
}

// --- Imaging viewer tools -------------------------------------------------------------
// Deliberately minimal, stroke-based, currentColor — so they read cleanly at ~15px inside
// a pill button and invert on the active (violet) state. They replace emoji, which
// rendered as detailed multi-colour glyphs that couldn't invert and sat inconsistently
// on the baseline.

export function PlayIcon({ size = 15 }) {
  return (
    <svg {...strokeProps(size)}>
      <path d="M8 5.5l10 6.5-10 6.5z" fill="currentColor" stroke="currentColor"
            strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

export function PauseIcon({ size = 15 }) {
  return (
    <svg {...strokeProps(size)}>
      <path d="M9 5.5v13M15 5.5v13" strokeWidth="2.5" />
    </svg>
  )
}

// Distance — a dimension line with end ticks (the drafting convention for "this length").
export function DistanceIcon({ size = 15 }) {
  return (
    <svg {...strokeProps(size)}>
      <path d="M4 12h16" />
      <path d="M4 8v8" />
      <path d="M20 8v8" />
    </svg>
  )
}

// Angle — two rays from a vertex with the arc that marks the angle between them.
export function AngleIcon({ size = 15 }) {
  return (
    <svg {...strokeProps(size)}>
      <path d="M5 19h15" />
      <path d="M5 19L17 6" />
      <path d="M12 19a7 7 0 0 0-1.7-4.6" strokeWidth="1.3" />
    </svg>
  )
}

// Region — a marquee rectangle (dashed = a selection, not a drawn shape).
export function RegionIcon({ size = 15 }) {
  return (
    <svg {...strokeProps(size)}>
      <rect x="4.5" y="6.5" width="15" height="11" rx="1.5" strokeDasharray="3.2 2.6" />
    </svg>
  )
}

// Chevron — points down; the timeline month header rotates it -90deg (to point right)
// when its month is collapsed. currentColor so it inherits the header's grey.
export function ChevronIcon({ size = 16 }) {
  return (
    <svg {...strokeProps(size)}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  )
}

// Magnifier — the CLOSED state of the shared search field (SearchField.jsx).
export function SearchIcon({ size = 16 }) {
  return (
    <svg {...strokeProps(size)}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-4.3-4.3" />
    </svg>
  )
}

// Expand / contract — the imaging viewer's fullscreen toggle. Four corner brackets, drawn
// pointing OUT to fill and IN to leave, which is the convention every media player uses;
// they are two icons rather than one rotated, because the arrows genuinely reverse.
export function ExpandIcon({ size = 16 }) {
  return (
    <svg {...strokeProps(size)}>
      <path d="M9 3H3v6M15 3h6v6M15 21h6v-6M9 21H3v-6" />
    </svg>
  )
}

export function ContractIcon({ size = 16 }) {
  return (
    <svg {...strokeProps(size)}>
      <path d="M3 9h6V3M21 9h-6V3M21 15h-6v6M3 15h6v6" />
    </svg>
  )
}

// Hamburger — "open the thing that lists what you can pick". Lifted out of AppHeader when
// the imaging page needed the same glyph for its studies drawer: two copies of one icon is
// how two copies of one affordance start.
export function MenuIcon({ size = 24 }) {
  return (
    <svg {...strokeProps(size)}>
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  )
}

// Cross — the OPEN state of that same control, which turns into its own close button
// rather than growing a second one beside it. Drawn rather than typed: the × character
// it replaces was a glyph whose weight and size came from the body font, so it never
// matched the magnifier it sat next to. Inset to 6..18 (not the full 4..20) so its
// diagonals read at the same visual weight as the magnifier's circle.
export function CloseIcon({ size = 16 }) {
  return (
    <svg {...strokeProps(size)}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  )
}

// Gear — the "manage / settings for this thing" glyph on the Metrics header's
// ActionMenu trigger. Hand-drawn to the module's convention rather than lifted from
// an icon set: a hub, a ring, and eight teeth drawn as short spokes that OVERLAP the
// ring (starting inside it at r=5.6 and ending at r=8.2). The overlap is what makes it
// read as a gear rather than a sun — a sun's rays are detached from its disc.
export function GearIcon({ size = 16 }) {
  return (
    <svg {...strokeProps(size)}>
      <circle cx="12" cy="12" r="6.2" />
      <circle cx="12" cy="12" r="2.4" />
      {/* Four axis teeth… */}
      <path d="M18.2 12h1.7M5.8 12H4.1M12 5.8V4.1M12 18.2v1.7" />
      {/* …and four diagonal ones, at 45°. */}
      <path d="M16.4 7.6l1.2-1.2M7.6 7.6L6.4 6.4M16.4 16.4l1.2 1.2M7.6 16.4l-1.2 1.2" />
    </svg>
  )
}

// Calendar view — a framed month with a header bar, two hanging tabs, and a grid of
// day dots, echoing the calendar overview. Reads clearly as "calendar" at 18px.
// Overrides the shared strokeWidth: this icon carries more geometry than its
// siblings (a frame, a header rule, two hangers and five dots), so at the common
// 2px it read as a heavier block than the list icon beside it in the same toggle.
export function CalendarViewIcon({ size = 18 }) {
  return (
    <svg {...strokeProps(size)} strokeWidth="1.6">
      <rect x="4" y="5" width="16" height="16" rx="2.5" />
      <line x1="4" y1="9.5" x2="20" y2="9.5" />
      <line x1="8.5" y1="3" x2="8.5" y2="6" />
      <line x1="15.5" y1="3" x2="15.5" y2="6" />
      <circle cx="8.5" cy="14" r="1" fill="currentColor" stroke="none" />
      <circle cx="12" cy="14" r="1" fill="currentColor" stroke="none" />
      <circle cx="15.5" cy="14" r="1" fill="currentColor" stroke="none" />
      <circle cx="8.5" cy="17.5" r="1" fill="currentColor" stroke="none" />
      <circle cx="12" cy="17.5" r="1" fill="currentColor" stroke="none" />
    </svg>
  )
}
