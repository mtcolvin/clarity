import { useState } from 'react'
import { addEvent, updateEvent } from '../../api'

// The fixed event types (must match the API's _EVENT_TYPES). Labels are friendly;
// values are what the backend stores/validates.
const EVENT_TYPES = [
  { value: 'visit', label: 'Visit' },
  { value: 'symptom', label: 'Symptom' },
  { value: 'life_event', label: 'Life event' },
  { value: 'procedure', label: 'Procedure' },
  { value: 'other', label: 'Other' },
]
const EMPTY = { event_date: '', event_type: 'visit', title: '', notes: '' }

// Add/edit form for a Timeline event — REUSED for both (pre-filled via key-remount
// in edit mode, submit routes to PUT), matching ConditionForm.
function fromEditing(editing) {
  if (!editing) return EMPTY
  return {
    event_date: editing.event_date ?? '',
    event_type: editing.event_type ?? 'visit',
    title: editing.title ?? '',
    notes: editing.notes ?? '',
  }
}

export default function EventForm({ editing, onSaved, onCancel }) {
  const [form, setForm] = useState(() => fromEditing(editing))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const isEdit = Boolean(editing)

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.title.trim()) {
      setError('Title is required.')
      return
    }
    if (!form.event_date) {
      setError('Date is required.')
      return
    }
    setBusy(true)
    setError(null)
    const body = {
      event_date: form.event_date,
      event_type: form.event_type,
      title: form.title.trim(),
      notes: form.notes.trim() || null,
    }
    try {
      if (isEdit) await updateEvent(editing.id, body)
      else await addEvent(body)
      onSaved?.()
    } catch (err) {
      setError(err.message || 'Could not save event.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form" onSubmit={handleSubmit}>
      {/* Only in EDIT mode, and only the title: the dialog's own header already says
          "Edit event", so repeating that would be a heading under a heading — but WHICH
          event is being edited is not otherwise on screen once the list is behind an
          overlay. */}
      {isEdit && <p className="form__editing">{editing.title}</p>}

      <label className="form__primary">
        Title
        <input value={form.title} onChange={(e) => set('title', e.target.value)} autoFocus />
      </label>

      <div className="form__grid">
        <label>
          Date
          <input type="date" value={form.event_date} onChange={(e) => set('event_date', e.target.value)} />
        </label>
        <label>
          Type
          <select value={form.event_type} onChange={(e) => set('event_type', e.target.value)}>
            {EVENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </label>
        <label>
          Notes <span className="optional">(optional)</span>
          <input value={form.notes} onChange={(e) => set('notes', e.target.value)} />
        </label>
      </div>

      {error && <p className="form__error">{error}</p>}
      <div className="form__actions">
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Add event'}
        </button>
        <button type="button" className="form__cancel" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  )
}
