import { useState } from 'react'
import { addMedication, updateMedication } from '../../api'

const EMPTY = { name: '', dose: '', frequency: '', start_date: '', end_date: '', notes: '' }

// Add/edit form for a medication — REUSED for both, like ObservationForm: in edit
// mode it's pre-filled (the page remounts it via key) and submit routes to PUT.
// Leaving end date blank means the medication is active; editing end_date in or out
// flips the derived `active` badge (no separate status flag).
function fromEditing(editing) {
  if (!editing) return EMPTY
  return {
    name: editing.name ?? '',
    dose: editing.dose ?? '',
    frequency: editing.frequency ?? '',
    start_date: editing.start_date ?? '',
    end_date: editing.end_date ?? '',
    notes: editing.notes ?? '',
  }
}

export default function MedicationForm({ editing, onSaved, onCancel }) {
  const [form, setForm] = useState(() => fromEditing(editing))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const isEdit = Boolean(editing)

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.name.trim()) {
      setError('Name is required.')
      return
    }
    setBusy(true)
    setError(null)
    const body = {
      name: form.name.trim(),
      dose: form.dose.trim() || null,
      frequency: form.frequency.trim() || null,
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      notes: form.notes.trim() || null,
    }
    try {
      if (isEdit) await updateMedication(editing.id, body)
      else await addMedication(body)
      if (!isEdit) setForm(EMPTY)
      onSaved?.()
    } catch (err) {
      setError(err.message || 'Could not save medication.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form" onSubmit={handleSubmit}>
      {isEdit && <p className="form__editing">Editing: {editing.name}</p>}

      <label className="form__primary">
        Medication name
        <input value={form.name} onChange={(e) => set('name', e.target.value)} autoFocus={isEdit} />
      </label>

      <div className="form__grid">
        <label>
          Dose <span className="optional">(optional)</span>
          <input value={form.dose} onChange={(e) => set('dose', e.target.value)}
                 placeholder="e.g. 20 mg" />
        </label>
        <label>
          Frequency <span className="optional">(optional)</span>
          <input value={form.frequency} onChange={(e) => set('frequency', e.target.value)}
                 placeholder="e.g. once daily" />
        </label>
        <label>
          Start <span className="optional">(optional)</span>
          <input type="date" value={form.start_date} onChange={(e) => set('start_date', e.target.value)} />
        </label>
        <label>
          End <span className="optional">(blank = active)</span>
          <input type="date" value={form.end_date} onChange={(e) => set('end_date', e.target.value)} />
        </label>
        <label>
          Notes <span className="optional">(optional)</span>
          <input value={form.notes} onChange={(e) => set('notes', e.target.value)} />
        </label>
      </div>

      {error && <p className="form__error">{error}</p>}
      <div className="form__actions">
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Add medication'}
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
