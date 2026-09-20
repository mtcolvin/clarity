import { useState } from 'react'
import Modal from '../Modal'
import { renameMetric } from '../../api'

// Rename the currently-selected metric. A local relabel only — the backend moves
// every reading and the metric's personal-baseline settings across atomically,
// and refuses to merge onto an existing metric (surfaced here as the 409 detail).
// Pre-filled with the current name; remounted per metric via `key` in the parent.
export default function RenameMetricModal({ open, metric, existingMetrics = [], onClose, onRenamed }) {
  const [name, setName] = useState(metric)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const trimmed = name.trim()
  const unchanged = trimmed === metric
  // Client-side hint mirroring the backend's refusal, so the user sees it before
  // submitting; the server stays the source of truth (it re-checks and 409s).
  const collides = !unchanged && existingMetrics.includes(trimmed)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!trimmed) {
      setError('A new name is required.')
      return
    }
    if (unchanged) {
      setError('That’s the same name.')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await renameMetric(metric, trimmed)
      onRenamed(trimmed)
    } catch (err) {
      // sendJSON puts the backend's detail on err.message (e.g. the 409 merge refusal).
      setError(err.message || 'Could not rename the metric.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Rename metric">
      <form className="form" onSubmit={handleSubmit}>
        <p className="form__editing">Renaming “{metric}”</p>
        <div className="form__grid">
          <label>
            New name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. HbA1c"
            />
          </label>
        </div>
        {collides && (
          <p className="form__error">
            A metric named “{trimmed}” already exists — renaming onto it would merge
            two series, which isn’t allowed. Pick a different name.
          </p>
        )}
        {error && <p className="form__error">{error}</p>}
        <div className="form__actions">
          <button type="submit" disabled={submitting || unchanged || collides}>
            {submitting ? 'Renaming…' : 'Rename'}
          </button>
          <button type="button" className="form__cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}
