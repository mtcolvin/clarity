import { useEffect, useState } from 'react'
import { getSettings, saveSettings, getExportEnabled, putExportEnabled, STATIC_DEMO } from '../../api'
import { InfoCircleIcon } from '../icons'
import { baselineExplainerCopy } from '../metrics/baselineExplainerCopy'
import Loading from '../shell/Loading'

// The group whose heading gets the permanent personal-baseline explainer
// paragraph right below it (see the settings__group render below). Matches
// the `group` string on the two personal_baseline_suggest_* SettingDefs in
// settings.py — not dismissable here (unlike the Metrics-page popup), since
// this is reference copy that belongs wherever the thresholds it explains
// are being tuned.
const BASELINE_EXPLAINER_GROUP = 'Personal-baseline suggestions'

// The group whose heading gets the export handoff's capability toggle (see
// below). Matches export_provider's `group` in settings.py — the toggle sits
// above that provider radio group so the whole "External export" section
// reads top to bottom: is it on, then which provider.
const EXPORT_GROUP = 'External export'

// export_hosted_enabled (CLAUDE.md "The export handoff") is a RAW setting —
// deliberately outside settings.py's typed registry (a capability flag, not a
// tunable knob; see api.py), so it's NOT part of the defs/draft/Save-batch
// flow above. It writes immediately on toggle, like BaselineMode's mode
// switch — matching the charter's requirement that revoking be exactly as
// easy as granting (no separate "Save" step either direction).
function ExportEnableToggle() {
  const [enabled, setEnabled] = useState(null) // null = still loading
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getExportEnabled()
      .then((d) => !cancelled && setEnabled(d.enabled))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [])

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      const d = await putExportEnabled(!enabled)
      setEnabled(d.enabled)
    } catch (e) {
      setError(e.message || 'Could not update the export capability.')
    } finally {
      setBusy(false)
    }
  }

  if (enabled === null) return null

  return (
    <div className="settings__row">
      <label className="settings__label" htmlFor="export-enabled-toggle">
        Enable external export
      </label>
      <label className="settings__toggle">
        <input
          id="export-enabled-toggle"
          type="checkbox"
          checked={STATIC_DEMO ? false : enabled}
          disabled={busy || STATIC_DEMO}
          onChange={toggle}
        />
        {STATIC_DEMO ? 'Off' : enabled ? 'On' : 'Off'}
      </label>
      <p className="settings__desc muted small">
        Turns on the per-metric export flow (Metrics page). Off by default —
        just as easy to turn back off as on. Even when on, nothing sends
        without reviewing a full preview and confirming each time.
        {STATIC_DEMO && (
          <> <strong>Unavailable in this static demo:</strong> sending needs a
          backend, so the capability is held off rather than offered and then
          refused.</>
        )}
      </p>
      {error && <p className="form__error">{error}</p>}
    </div>
  )
}

// Adjustable settings form (lives on its own page — see SettingsPage). Exposes
// the DISPLAY-VOLUME values (changes-digest recency window, anomaly detail cap,
// anomaly condense threshold) plus the narration-engine choice — none of which
// change WHAT is flagged. The backend registry drives every field (label,
// description, type, bounds, and — for a categorical setting — its option list),
// so this renders generically: a numeric setting renders a number input that
// constrains itself to any minimum/maximum; an 'enum' setting renders a radio
// group of its allowed options (the closed list the server validates against).
//
// On Save it persists the batch and calls onSaved() so the parent bumps its
// reloadKey — which re-fetches the changes digest and the anomaly/history panel,
// reflecting the new values immediately.
//
// `groups` (optional): restrict the panel to those registry groups — how the
// Settings page renders one panel instance per tab. Each instance is its own
// independent form (draft + Save) over its slice; saveSettings only ever sends
// changed keys, so per-tab saves can't clobber the other tabs' values. With a
// single group shown, the in-form group heading is suppressed (the tab label
// already names it) but the per-group extras (explainer, export toggle) keep
// rendering. Omitted -> every group, headings shown (the pre-tabs behavior).
export default function SettingsPanel({ groups, onSaved }) {
  const [allDefs, setAllDefs] = useState(null) // FULL registry from the backend
  const [draft, setDraft] = useState({}) // key -> current input value (string)
  const [status, setStatus] = useState(null) // 'saving' | 'saved' | null
  const [error, setError] = useState(null)

  const showHeadings = !groups || groups.length > 1

  useEffect(() => {
    getSettings()
      .then((rows) => {
        setAllDefs(rows)
        setDraft(Object.fromEntries(rows.map((d) => [d.key, String(d.value)])))
        setError(null)
      })
      .catch((e) => setError(e.message))
  }, [])

  if (!allDefs && !error) return <Loading what="settings" />
  // Couldn't load the settings registry (e.g. the API is an older process that
  // doesn't expose /settings yet). Surface it instead of vanishing silently.
  if (!allDefs) {
    return (
      <p className="form__error">
        Couldn’t load settings: {error}. Is the API running with the latest routes?
      </p>
    )
  }

  // The slice this instance renders and saves. State keeps the FULL registry
  // (so the mount effect stays free of component-scoped values); the groups
  // filter applies at render time. `changed`/Save only ever consider the
  // visible slice, so per-tab saves can't touch the other tabs' values.
  const defs = groups ? allDefs.filter((d) => groups.includes(d.group)) : allDefs

  // Which fields differ from what's stored (drives the Save button + payload).
  const changed = defs.filter((d) => draft[d.key] !== String(d.value))
  const dirty = changed.length > 0

  async function handleSave(e) {
    e.preventDefault()
    setStatus('saving')
    setError(null)
    try {
      // Send only changed keys. Numeric settings go as numbers; an enum value is
      // a string (one of its option values). The backend validates either way —
      // an out-of-allowlist enum value is rejected server-side.
      const values = Object.fromEntries(
        changed.map((d) => [d.key, d.type === 'enum' ? draft[d.key] : Number(draft[d.key])]),
      )
      const rows = await saveSettings(values) // echoes the FULL registry back
      setAllDefs(rows)
      setDraft(Object.fromEntries(rows.map((d) => [d.key, String(d.value)])))
      setStatus('saved')
      onSaved?.() // bump reloadKey so the affected views refetch
    } catch (e2) {
      setError(e2.message || 'Could not save settings.')
      setStatus(null)
    }
  }

  function handleReset() {
    setDraft(Object.fromEntries(defs.map((d) => [d.key, String(d.value)])))
    setStatus(null)
    setError(null)
  }

  return (
    <div className="settings">
      <form onSubmit={handleSave} className="settings__form">
        {defs.map((d, i) => (
          <div key={d.key} className="settings__row">
            {/* Group boundary: heading (when more than one group is visible)
                plus the per-group extras, before the first setting of each group. */}
            {d.group && d.group !== defs[i - 1]?.group && (
              <>
                {showHeadings && <h4 className="settings__group">{d.group}</h4>}
                {d.group === BASELINE_EXPLAINER_GROUP && (
                  <div className="baseline baseline--explainer">
                    <div className="baseline__row">
                      <InfoCircleIcon size={17} offset />
                      <p className="baseline__msg">
                        {baselineExplainerCopy({
                          suggestFraction: defs.find(
                            (x) => x.key === 'personal_baseline_suggest_min_fraction',
                          )?.value,
                          suggestMinReadings: defs.find(
                            (x) => x.key === 'personal_baseline_suggest_min_readings',
                          )?.value,
                        })}
                      </p>
                    </div>
                  </div>
                )}
                {d.group === EXPORT_GROUP && <ExportEnableToggle />}
              </>
            )}
            <label className="settings__label" htmlFor={`set-${d.key}`}>
              {d.label}
              {d.unit ? <span className="muted small"> ({d.unit})</span> : null}
            </label>
            {d.type === 'enum' ? (
              // Categorical setting: a radio group of the server's closed option
              // list, each with its own description (so the privacy posture of
              // each engine is visible at the point of choosing).
              <div className="settings__options" role="radiogroup" aria-label={d.label}>
                {d.options.map((opt) => {
                  // available===false → render the option visibly DISABLED (not
                  // hidden): keeps the "you can switch engines here" affordance
                  // while being honest it isn't usable now (e.g. Ollama not
                  // running). A missing flag (older API) is treated as available.
                  // In the static demo NOTHING can be saved, so every control is held
                  // disabled. Showing a provider radio as SELECTED under a capability
                  // that is switched off was the specific thing that read as a
                  // contradiction — the page appeared to have made a choice it had not.
                  const unavailable = opt.available === false || STATIC_DEMO
                  return (
                    <label
                      key={opt.value}
                      className={`settings__option${unavailable ? ' settings__option--disabled' : ''}`}
                    >
                      <input
                        type="radio"
                        name={`set-${d.key}`}
                        value={opt.value}
                        checked={draft[d.key] === opt.value}
                        disabled={unavailable}
                        onChange={(e) =>
                          setDraft((cur) => ({ ...cur, [d.key]: e.target.value }))
                        }
                      />
                      <span className="settings__option-label">
                        {opt.label}
                        {opt.value === d.default ? (
                          <span className="muted small"> (default)</span>
                        ) : null}
                        {unavailable ? (
                          <span className="muted small">
                            {STATIC_DEMO ? ' — not settable in this demo' : ' — not detected'}
                          </span>
                        ) : null}
                      </span>
                      <span className="settings__option-desc muted small">{opt.description}</span>
                    </label>
                  )
                })}
              </div>
            ) : (
              <input
                id={`set-${d.key}`}
                type="number"
                className="settings__input"
                disabled={STATIC_DEMO}
                value={draft[d.key] ?? ''}
                step={d.step ?? (d.type === 'int' ? 1 : 'any')}
                // Bounds render only when present — null today, the seam for future
                // bounded (safety-relevant) settings.
                min={d.minimum ?? undefined}
                max={d.maximum ?? undefined}
                onChange={(e) =>
                  setDraft((cur) => ({ ...cur, [d.key]: e.target.value }))
                }
              />
            )}
            <p className="settings__desc muted small">
              {d.description}
              {d.type !== 'enum' && (
                <>
                  {' '}
                  <span className="muted">Default: {d.default}.</span>
                </>
              )}
            </p>
          </div>
        ))}

        {error && <p className="form__error">{error}</p>}

        <div className="settings__actions">
          <button type="submit" disabled={!dirty || status === 'saving' || STATIC_DEMO}>
            {status === 'saving' ? 'Saving…' : 'Save settings'}
          </button>
          {dirty && (
            <button type="button" className="settings__reset" onClick={handleReset}>
              Reset
            </button>
          )}
          {status === 'saved' && !dirty && (
            <span className="muted small">Saved.</span>
          )}
        </div>
      </form>
    </div>
  )
}
