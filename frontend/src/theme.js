import { useEffect, useMemo, useState } from 'react'

// Theme: light, dark, or follow the OS. Everything about the LOOK lives in index.css's
// token blocks; this module owns only the CHOICE — where it's stored, when it's applied,
// and how the chart (which can't read CSS variables) finds out.
//
// Stored in localStorage, NOT in the settings table. Two reasons, and the second is the
// real one: a theme is a per-DEVICE display preference rather than a property of the
// record, and reading it from the API would mean a round-trip before the first paint —
// i.e. a flash of the light theme on every load. `applyStoredTheme()` runs from main.jsx
// before React mounts, off a synchronous localStorage read, so the first paint is already
// correct. (The export-enable toggle stays server-side for the opposite reason: it gates
// data leaving the machine, so it is a property of the install, not of the browser.)

const KEY = 'ht-theme'
export const THEMES = ['system', 'light', 'dark']
const CHANGED = 'ht-theme-changed'

export function getTheme() {
  try {
    const v = localStorage.getItem(KEY)
    return THEMES.includes(v) ? v : 'system'
  } catch {
    return 'system'   // private mode / storage disabled — follow the OS and don't crash
  }
}

// The theme actually in force: 'system' resolved against the OS preference.
export function resolveTheme(choice = getTheme()) {
  if (choice !== 'system') return choice
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

// One writer for the attribute the CSS keys off. Called before mount and on every change.
export function applyStoredTheme() {
  document.documentElement.dataset.theme = resolveTheme()
}

export function setTheme(choice) {
  try {
    localStorage.setItem(KEY, choice)
  } catch { /* not fatal: the theme still applies for this session */ }
  applyStoredTheme()
  window.dispatchEvent(new CustomEvent(CHANGED))
}

// Subscribe to the theme in force. Re-renders on an explicit change AND on the OS
// flipping while the choice is 'system' — without that second listener, a machine that
// switches at sunset would leave the app in yesterday's theme until reload.
export function useTheme() {
  const [theme, setThemeState] = useState(() => resolveTheme())
  useEffect(() => {
    const update = () => setThemeState(resolveTheme())
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    window.addEventListener(CHANGED, update)
    mq?.addEventListener('change', update)
    return () => {
      window.removeEventListener(CHANGED, update)
      mq?.removeEventListener('change', update)
    }
  }, [])
  return theme
}

// ---------------------------------------------------------------------- chart colours
//
// Recharts takes colours as PROPS that become SVG presentation attributes, and an SVG
// attribute can't parse `var(--x)` — so the chart genuinely cannot read the tokens the
// way the rest of the app does. It resolves them instead: one getComputedStyle read per
// theme change, not per render.
//
// Only the ACCENT family is read. The semantic marks (out-of-range red, the noteworthy
// amber caret) are resolved here too, because on a dark ground the light-theme values are
// unreadable — same meaning, different value, exactly as in index.css.
const TOKENS = {
  accent: '--c-accent',
  baseline: '--c-baseline',
  baselineSoft: '--c-baseline-soft',
  outOfRange: '--sem-bad-strong',
  noteworthy: '--sem-watch',
  grid: '--c-line',
  band: '--sem-ok',
}

// `theme` is carried through onto the result rather than only gating the read: a caller
// occasionally needs to know WHICH theme these values came from, and it makes the memo's
// dependency an honest one instead of a lint suppression.
function readTokens(theme) {
  const cs = getComputedStyle(document.documentElement)
  const out = { theme }
  for (const [name, token] of Object.entries(TOKENS)) {
    out[name] = cs.getPropertyValue(token).trim()
  }
  return out
}

export function useChartColors() {
  const theme = useTheme()
  // Derived during render, not synchronised in an effect: reading a computed style is a
  // pure read of something React doesn't own, and `theme` already changes when it does.
  return useMemo(() => readTokens(theme), [theme])
}
