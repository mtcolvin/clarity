import { useState } from 'react'
import Modal from '../Modal'
import { setMetricGroup } from '../../api'

// Set (or clear) the selected metric's GROUP label — a purely presentational picker
// cluster (an <optgroup>), e.g. an arterial blood-gas panel. Display-only: it touches no
// identity/match key and no reading, so it's freely reversible (clear the field to
// ungroup). `existingGroups` seeds a datalist so an existing panel is reused by typing/
// picking its exact label rather than re-inventing a near-duplicate. Pre-filled with the
// current group; remounted per metric via `key` in the parent. Not shown for derived
// metrics (they already cluster under "Computed metrics"; the backend also refuses 409).
export default function GroupModal({
  open, metric, currentGroup = '', existingGroups = [], onClose, onSet,
}) {
  const [group, setGroup] = useState(currentGroup || '')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const trimmed = group.trim()

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const res = await setMetricGroup(metric, trimmed || null)
      onSet(res) // { metric, group }
    } catch (err) {
      // sendJSON puts the backend's detail on err.message (404 / 409).
      setError(err.message || 'Could not set the group.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Group">
      <form className="form" onSubmit={handleSubmit}>
        <p className="form__editing">Group for “{metric}”</p>
        <div className="form__grid">
          <label>
            Group
            <input
              value={group}
              list="metric-group-list"
              onChange={(e) => setGroup(e.target.value)}
              placeholder="e.g. Arterial Blood Gas — leave blank to ungroup"
            />
          </label>
          <datalist id="metric-group-list">
            {existingGroups.map((g) => (
              <option key={g} value={g} />
            ))}
          </datalist>
        </div>
        <p className="form__hint">
          A display-only cluster — the metric appears under this heading in the picker.
          Type an existing group’s exact name to add this metric to it, or leave blank to
          ungroup. It changes nothing about the readings.
        </p>
        {error && <p className="form__error">{error}</p>}
        <div className="form__actions">
          <button type="submit" disabled={submitting}>
            {submitting ? 'Saving…' : trimmed ? 'Save' : 'Clear'}
          </button>
          <button type="button" className="form__cancel" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Modal>
  )
}
