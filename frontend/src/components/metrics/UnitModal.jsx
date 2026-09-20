import { useState } from 'react'
import Modal from '../Modal'
import { setMetricUnit } from '../../api'

// RELABEL the selected metric's unit across all its numeric/censored readings. A pure
// LABEL change — values are NOT converted (they're stored as entered and left untouched).
// Use it to fix casing ('mg/dl' -> 'mg/dL') or unify equivalent units ('EU/dL' -> 'mg/dL',
// which for urobilinogen are 1:1); a genuine conversion (mg/dL -> mg/L) means editing the
// values too. Qualitative readings stay unitless. Pre-filled with the current unit;
// remounted per metric via `key` in the parent. Not shown for derived metrics (their unit
// is fixed by the computation — the backend also refuses with 409).
export default function UnitModal({ open, metric, currentUnit = '', onClose, onSet }) {
  const [unit, setUnit] = useState(currentUnit || '')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const res = await setMetricUnit(metric, unit.trim())
      onSet(res)
    } catch (err) {
      // sendJSON puts the backend's detail on err.message (404 / 409).
      setError(err.message || 'Could not change the unit.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Edit unit">
      <form className="form" onSubmit={handleSubmit}>
        <p className="form__editing">Unit for “{metric}”</p>
        <div className="form__grid">
          <label>
            Unit
            <input
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              placeholder="e.g. mg/dL — leave blank for dimensionless"
            />
          </label>
        </div>
        <p className="form__hint">
          <strong>Relabels the unit on every numeric reading — it does NOT convert the
          values.</strong> Use it to fix casing (mg/dl → mg/dL) or unify equivalent units
          (EU/dL → mg/dL). For a real conversion (e.g. mg/dL → mg/L) you’d change the values
          too. Qualitative readings stay unitless.
        </p>
        {error && <p className="form__error">{error}</p>}
        <div className="form__actions">
          <button type="submit" disabled={submitting}>
            {submitting ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className="form__cancel" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Modal>
  )
}
