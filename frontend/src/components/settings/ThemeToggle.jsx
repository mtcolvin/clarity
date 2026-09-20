import { getTheme, setTheme, useTheme, THEMES } from '../../theme'

const LABELS = { system: 'System', light: 'Light', dark: 'Dark' }

// The theme control, in Settings → Display. A segmented control, the same one the sex
// selector and the chart's Linear/Log switch use — three exclusive options, all visible,
// no dropdown to open.
//
// It writes to localStorage rather than the settings table, and is therefore NOT part of
// SettingsPanel's registry-driven form or its Save batch: a theme is a per-DEVICE display
// preference, and reading it from the API would mean a round-trip before the first paint —
// a flash of the light theme on every load. It applies immediately on click, like the
// export capability toggle (the app's other non-registry setting), so there is nothing to
// save and nothing to lose by navigating away.
//
// "System" is the default and is a real third option, not a synonym for light: a machine
// that switches at sunset should take the app with it, which `useTheme` subscribes to.
export default function ThemeToggle() {
  const active = useTheme()          // the theme in FORCE (system resolved)
  const choice = getTheme()          // what was CHOSEN (may be 'system')

  return (
    <div className="settings__row">
      <span className="settings__label" id="theme-label">Appearance</span>
      <div className="segmented" role="radiogroup" aria-labelledby="theme-label">
        {THEMES.map((t) => (
          <label key={t} className="segmented__option">
            <input
              type="radio"
              name="app-theme"
              value={t}
              checked={choice === t}
              onChange={() => setTheme(t)}
            />
            <span>{LABELS[t]}</span>
          </label>
        ))}
      </div>
      <p className="settings__desc muted small">
        Dark inverts the page and panel grounds and lifts the accent to a pale slate; the
        out-of-range red, reference-band green and noteworthy amber keep their meanings and
        take lighter values so they stay readable. Stored in this browser, not in your
        record. Default: System{choice === 'system' ? ` (currently ${active})` : ''}.
      </p>
    </div>
  )
}
