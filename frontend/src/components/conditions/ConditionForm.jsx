import { useState } from 'react'
import { addCondition, updateCondition } from '../../api'
import Icd10Lookup from './Icd10Lookup'

const STATUSES = ['active', 'resolved', 'monitoring']
const EMPTY = { name: '', icd10: '', onset_on: '', status: 'active', resolved_on: '', notes: '' }

// Add/edit form for a condition — REUSED for both, like ObservationForm: in edit
// mode it's pre-filled (the page remounts it via key) and submit routes to PUT.
// Layout reflects that the NAME is the primary identifier (prominent, full width)
// and the ICD-10 code is secondary (its own row so the lookup has room, explicitly
// optional, with a helper that fills both fields). resolved_on appears only when
// status is 'resolved' and is OPTIONAL — a "Date unknown" toggle records resolved-
// but-date-unknown (stored null; we don't invent a date). Status moving away from
// resolved clears the date, so an active/monitoring condition never holds a stale one.
function fromEditing(editing) {
  if (!editing) return EMPTY
  return {
    name: editing.name ?? '',
    icd10: editing.icd10 ?? '',
    onset_on: editing.onset_on ?? '',
    status: editing.status ?? 'active',
    resolved_on: editing.resolved_on ?? '',
    notes: editing.notes ?? '',
  }
}

export default function ConditionForm({ editing, onSaved, onCancel }) {
  const [form, setForm] = useState(() => fromEditing(editing))
  const [unknownDate, setUnknownDate] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const isEdit = Boolean(editing)

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
  }

  // Changing status clears resolved_on unless we're (still) resolved — no stale
  // resolution date can linger on an active/monitoring condition.
  function setStatus(value) {
    setForm((f) => ({ ...f, status: value, resolved_on: value === 'resolved' ? f.resolved_on : '' }))
    if (value !== 'resolved') setUnknownDate(false)
  }

  // "Date unknown" clears + disables the date input; both blank and unknown store null.
  function toggleUnknown(checked) {
    setUnknownDate(checked)
    if (checked) set('resolved_on', '')
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.name.trim()) {
      setError('Name is required.')
      return
    }
    setBusy(true)
    setError(null)
    const resolved = form.status === 'resolved'
    const body = {
      name: form.name.trim(),
      icd10: form.icd10.trim() || null,
      onset_on: form.onset_on || null,
      status: form.status,
      // Optional even when resolved: blank / unknown both persist as null.
      resolved_on: resolved && !unknownDate ? form.resolved_on || null : null,
      notes: form.notes.trim() || null,
    }
    try {
      if (isEdit) await updateCondition(editing.id, body)
      else await addCondition(body)
      if (!isEdit) {
        setForm(EMPTY)
        setUnknownDate(false)
      }
      onSaved?.()
    } catch (err) {
      setError(err.message || 'Could not save condition.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form" onSubmit={handleSubmit}>
      {isEdit && <p className="form__editing">Editing: {editing.name}</p>}

      {/* Name is the primary identifier — full width, prominent. */}
      <label className="form__primary">
        Condition name
        <input value={form.name} onChange={(e) => set('name', e.target.value)} autoFocus={isEdit} />
      </label>

      {/* ICD-10 on its own full-width row so the code input, the lookup toggle, and
          the search results all have room (not squeezed into a narrow grid cell). */}
      <div className="form__icd10">
        <label className="form__secondary">
          ICD-10 code <span className="optional">(optional)</span>
          <input className="form__icd10-input" value={form.icd10}
                 onChange={(e) => set('icd10', e.target.value)} placeholder="e.g. E80.4" />
        </label>
        <Icd10Lookup onPick={(e) => setForm((f) => ({ ...f, name: e.name, icd10: e.code }))} />
      </div>

      <div className="form__grid">
        <label>
          Onset <span className="optional">(optional)</span>
          <input type="date" value={form.onset_on} onChange={(e) => set('onset_on', e.target.value)} />
        </label>
        <label>
          Status
          <select value={form.status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        {/* resolved_on appears only when resolved; optional, with an unknown toggle. */}
        {form.status === 'resolved' && (
          <div className="form__field">
            <span className="form__field-label">
              Resolved on <span className="optional">(optional)</span>
            </span>
            <input type="date" value={form.resolved_on} disabled={unknownDate}
                   onChange={(e) => set('resolved_on', e.target.value)} />
            <label className="form__check">
              <input type="checkbox" checked={unknownDate}
                     onChange={(e) => toggleUnknown(e.target.checked)} />
              Date unknown
            </label>
          </div>
        )}
        <label>
          Notes <span className="optional">(optional)</span>
          <input value={form.notes} onChange={(e) => set('notes', e.target.value)} />
        </label>
      </div>

      {error && <p className="form__error">{error}</p>}
      <div className="form__actions">
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Add condition'}
        </button>
        {/* Always shown, not edit-only: the form is now opened from the section head, so
            Cancel is the way OUT of an add as much as it is out of an edit. */}
        <button type="button" className="form__cancel" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  )
}
