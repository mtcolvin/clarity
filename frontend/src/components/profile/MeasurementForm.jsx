import { useState } from 'react'
import { addProfileMeasurement, updateProfileMeasurement } from '../../api'

// Local (not UTC) today as YYYY-MM-DD, so the default date matches the user's clock.
function todayISO() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const UNIT_SUGGESTIONS = { weight: ['lb', 'kg'], height: ['in', 'cm'] }
const DEFAULT_UNIT = { weight: 'lb', height: 'in' }

// Inline form for one physical measurement, reused for ADD and EDIT — the same
// add-or-edit shape ObservationForm uses, for the same reason: two forms over one
// record inevitably validate differently. Pass `editing` (a measurement row) to
// correct it in place; omit it to append a new one.
//
// The table stays APPEND-ONLY for new measurements — each save is a new row and the
// latest is the current value — which is a different thing from immutable: a mistyped
// weight was previously only fixable by deleting the row, which threw away the date too.
// What an edit CANNOT change is `field`: weight and height are different quantities, so
// a row never moves between them (the backend doesn't accept it either). Reused for
// weight + height via `field`; the parent remounts it via `key` to reset after a save /
// when toggled open. Unit is required and stored AS ENTERED (no conversion).
export default function MeasurementForm({ field, editing = null, onSaved, onCancel }) {
  const isEdit = editing != null
  const [value, setValue] = useState(isEdit ? String(editing.value) : '')
  const [unit, setUnit] = useState(isEdit ? editing.unit : (DEFAULT_UNIT[field] ?? ''))
  const [recordedOn, setRecordedOn] = useState(isEdit ? editing.recorded_on : todayISO())
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (value.trim() === '' || Number.isNaN(Number(value))) return setError('Value must be a number.')
    if (!unit.trim()) return setError('Unit is required.')
    if (!recordedOn) return setError('Date is required.')
    setError(null)
    setSubmitting(true)
    try {
      const body = { value: Number(value), unit: unit.trim(), recorded_on: recordedOn }
      if (isEdit) await updateProfileMeasurement(editing.id, body)
      else await addProfileMeasurement({ field, ...body })
      onSaved()
    } catch (err) {
      setError(err.message || 'Could not save the measurement.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="form profile__form" onSubmit={handleSubmit}>
      <div className="form__grid">
        <label>
          Value
          <input type="number" step="any" value={value}
                 onChange={(e) => setValue(e.target.value)} autoFocus />
        </label>
        <label>
          Unit
          <input list={`unit-${field}`} value={unit}
                 onChange={(e) => setUnit(e.target.value)}
                 placeholder={field === 'height' ? 'e.g. in' : 'e.g. lb'} />
          <datalist id={`unit-${field}`}>
            {(UNIT_SUGGESTIONS[field] ?? []).map((u) => <option key={u} value={u} />)}
          </datalist>
        </label>
        <label>
          Date
          <input type="date" value={recordedOn}
                 onChange={(e) => setRecordedOn(e.target.value)} />
        </label>
      </div>
      {error && <p className="form__error">{error}</p>}
      <div className="form__actions">
        <button type="submit" disabled={submitting}>
          {submitting ? 'Saving…' : isEdit ? 'Save changes' : `Save ${field}`}
        </button>
        <button type="button" className="form__cancel" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}
