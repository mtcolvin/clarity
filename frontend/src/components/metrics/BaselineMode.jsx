import { useState } from 'react'
import { HealthIcon } from '../icons'

// The hard floor for ENABLING personal-baseline mode at all — across the
// board, whether the metric arrived via the suggestion banner (a candidate)
// or the quiet link (not a candidate). Uses candidacy.numeric_count (ALL
// numeric readings, no ref-bound requirement), never candidacy.n
// (judgeable-only — a metric can have plenty of numeric readings but few
// judgeable ones, and the wrong denominator would wrongly hide a computable
// metric). Deliberately a fixed 5, independent of the suggestion banner's own
// (user-tunable, settings.py personal_baseline_suggest_min_readings) floor:
// under that setting's DEFAULT of 5 the two already agree, but if it's ever
// tuned lower, a candidate could otherwise appear (and be enabled) below this
// floor — the explicit `numeric_count >= MIN_COMPUTABLE_READINGS` check on
// BOTH render branches below is what keeps 5 an actual invariant rather than
// an incidental default. Exported so the global explainer
// (BaselineExplainer.jsx / baselineExplainerCopy.js) can cite the exact same
// number rather than repeating "5" as a second, driftable literal.
export const MIN_COMPUTABLE_READINGS = 5

// Per-metric personal-baseline control. TWO surfaces now, sharing one violet callout:
//   1. Mode ON -> the active-mode callout (a confirmation, not a decision) with a
//      collapsed note field, so the mode is visible and the note editable.
//   2. Candidate, mode off, not dismissed, AND numeric_count >=
//      MIN_COMPUTABLE_READINGS -> the SUGGESTION banner (the active pitch, asking for
//      a decision — it has to be seen, so it stays on the page, not in a menu).
//   3. Otherwise -> nothing. The plain "turn this on" trigger that used to render here
//      as a quiet link is now an item in the Manage-metric menu (MetricsPage): it was
//      only ever a trigger, and it appeared on most metrics at rest, competing with
//      the metric's own facts for the rail.
//
// The SETTINGS THEMSELVES ARE OWNED BY THE PAGE (MetricsPage fetches them and passes
// `data` + `onApply`), because the menu item and this component are two views of one
// piece of state — fetching it in both would let them disagree.
//
// SAFETY: the suggestion states a frequency fact and conditions the action on
// the USER's knowledge ("if this is expected for you"); it never asserts the
// deviation is benign. The note is the user's own words, shown as such — never
// the tool's inference.
export default function BaselineMode({ metric, data, onApply }) {
  const [noteDraft, setNoteDraft] = useState(data?.note ?? '')
  const [editingNote, setEditingNote] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function apply(patch) {
    setBusy(true)
    setError(null)
    try {
      const updated = await onApply(patch)
      setNoteDraft(updated.note ?? '')
      return updated
    } catch (e) {
      setError(e.message || 'Could not update personal-baseline mode.')
      throw e
    } finally {
      setBusy(false)
    }
  }

  function cancelEditingNote() {
    setNoteDraft(data.note ?? '')
    setEditingNote(false)
  }

  async function saveNote() {
    try {
      await apply({ note: noteDraft })
      setEditingNote(false)
    } catch {
      /* error already surfaced by apply(); stay in edit mode so it can be retried */
    }
  }

  if (!data) return null // settings not loaded (or failed) — don't block the metric view

  const { personal_baseline_mode: mode, suggestion_dismissed: dismissed, candidacy, note } = data

  // State 1 (mode on): the active-mode callout + collapsed note field.
  if (mode) {
    return (
      <section className="baseline baseline--active">
        <div className="baseline__row">
          <HealthIcon size={17} offset />
          <p className="baseline__msg">
            Tracking against your own baseline — expected deviations read as
            &ldquo;within your established range&rdquo;; real changes still flag.
            Lab range stays visible for context.
          </p>
        </div>
        <hr className="baseline__divider" />
        {editingNote ? (
          <div className="baseline__note">
            <input
              id={`note-${metric}`}
              type="text"
              aria-label="Your note"
              placeholder="e.g. Gilbert's — expected (your words)"
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              autoFocus
            />
            <button type="button" className="baseline__primary-btn" disabled={busy}
                    onClick={saveNote}>
              Save
            </button>
            <button type="button" className="baseline__link" disabled={busy}
                    onClick={cancelEditingNote}>
              Cancel
            </button>
          </div>
        ) : note ? (
          <p className="baseline__note-display">
            <span className="muted small baseline-tag">{note}</span>
            <button type="button" className="baseline__link" onClick={() => setEditingNote(true)}>
              Edit
            </button>
          </p>
        ) : (
          <button type="button" className="baseline__link" onClick={() => setEditingNote(true)}>
            + Add a note
          </button>
        )}
        <div className="baseline__actions">
          <button type="button" className="baseline__primary-btn" disabled={busy}
                  onClick={() => apply({ personal_baseline_mode: false })}>
            Track against the lab range again
          </button>
        </div>
        {error && <p className="form__error">{error}</p>}
      </section>
    )
  }

  // State 2: the suggestion banner — kept fuller, it's the active pitch. The
  // numeric_count check is a belt-and-suspenders floor: is_candidate already
  // implies numeric_count >= MIN_COMPUTABLE_READINGS under the suggestion
  // threshold's DEFAULT settings, but that threshold is user-tunable — this
  // keeps 5 readings an actual floor for ENABLING the mode, not just an
  // incidental default (see the MIN_COMPUTABLE_READINGS comment above).
  if (candidacy.is_candidate && !dismissed && candidacy.numeric_count >= MIN_COMPUTABLE_READINGS) {
    return (
      <section className="baseline baseline--suggest">
        <p className="baseline__msg">
          {metric} has been outside the lab range on most readings. If that&rsquo;s
          expected for you, track it against your own baseline — flags will
          highlight real changes from your pattern, with the lab range still
          shown for context.
        </p>
        <div className="baseline__actions">
          <button type="button" className="baseline__primary-btn" disabled={busy}
                  onClick={() => apply({ personal_baseline_mode: true })}>
            Track against your baseline
          </button>
          <button type="button" className="baseline__secondary" disabled={busy}
                  onClick={() => apply({ suggestion_dismissed: true })}>
            Not for me
          </button>
        </div>
        {error && <p className="form__error">{error}</p>}
      </section>
    )
  }

  // Mode off and not being pitched: nothing here. Turning it on lives in the
  // Manage-metric menu (see the note at the top of this file).
  return null
}
