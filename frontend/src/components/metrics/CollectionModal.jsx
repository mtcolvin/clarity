import { useState } from 'react'
import Modal from '../Modal'
import { createCollection, updateCollection } from '../../api'

// Create OR edit a timed collection (24h urine, etc.). Create is the "create-first" step
// (make the collection, then add its analytes referencing it); edit changes the shared
// context (volume/duration/dates/notes) without touching the analytes. Only `completed_on`
// (the END date the analytes share as their observed_on) is required. `started_on` is
// intentionally NOT collected — it's derivable (completion − duration), so the field was
// dropped; the column stays nullable for the rare irregular case. In edit mode the parent
// remounts this via `key` so the fields pre-fill from `editing`.
export default function CollectionModal({ open, onClose, editing = null, onCreated, onSaved }) {
  const isEdit = Boolean(editing)
  const [completedOn, setCompletedOn] = useState(editing?.completed_on ?? '')
  const [durationHours, setDurationHours] = useState(
    editing?.duration_hours != null ? String(editing.duration_hours) : '24')
  const [volumeMl, setVolumeMl] = useState(
    editing?.volume_ml != null ? String(editing.volume_ml) : '')
  const [notes, setNotes] = useState(editing?.notes ?? '')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!completedOn.trim()) {
      setError('The collection’s completion date is required.')
      return
    }
    setError(null)
    setSubmitting(true)
    const body = {
      completed_on: completedOn.trim(),
      duration_hours: durationHours.trim() === '' ? null : Number(durationHours),
      volume_ml: volumeMl.trim() === '' ? null : Number(volumeMl),
      notes: notes.trim() || null,
    }
    try {
      if (isEdit) {
        onSaved(await updateCollection(editing.id, body))
      } else {
        onCreated(await createCollection(body))
      }
    } catch (err) {
      setError(err.message || 'Could not save the collection.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Edit collection' : 'New timed collection'}>
      <form className="form" onSubmit={handleSubmit}>
        {!isEdit && (
          <p className="form__hint">
            A timed collection (e.g. 24-hour urine) groups several analytes that share one
            volume, duration, and date. Add the analytes afterward — they’ll use the
            completion date below.
          </p>
        )}
        <div className="form__grid">
          <label>
            Completion date
            <input type="date" value={completedOn}
                   onChange={(e) => setCompletedOn(e.target.value)} />
          </label>
          <label>
            Duration (hours)
            <input type="number" step="any" min="0" value={durationHours}
                   onChange={(e) => setDurationHours(e.target.value)} placeholder="24" />
          </label>
          <label>
            Total volume (mL) <span className="muted">(optional)</span>
            <input type="number" step="any" min="0" value={volumeMl}
                   onChange={(e) => setVolumeMl(e.target.value)} placeholder="e.g. 1850" />
          </label>
        </div>
        <label>
          Notes <span className="muted">(optional)</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {error && <p className="form__error">{error}</p>}
        <div className="form__actions">
          <button type="submit" disabled={submitting}>
            {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Create collection'}
          </button>
          <button type="button" className="form__cancel" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Modal>
  )
}
