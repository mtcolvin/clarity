import { useState } from 'react'
import Modal from '../Modal'
import { setDisplayName } from '../../api'

// Set (or clear) the selected metric's DISPLAY name (shorthand label). The match key is
// the metric's id; the verbose lab label and this shorthand BOTH resolve to it. Unlike a
// rename this ADDS a label rather than replacing the verbose one, so the metric keeps the
// lab wording a future import resolves by. Clearing falls back to showing the verbose
// label. The backend refuses (409) a label another metric already resolves by. Pre-filled
// with the current alias; remounted per metric via `key` in the parent.
export default function DisplayNameModal({
  open, metric, currentAlias = '', isDerived = false, onClose, onSet,
}) {
  const [name, setName] = useState(currentAlias || '')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const trimmed = name.trim()

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      // Empty clears the alias (null) -> UI falls back to the canonical name.
      await setDisplayName(metric, trimmed || null)
      onSet(trimmed || null)
    } catch (err) {
      // sendJSON puts the backend's detail on err.message (e.g. the 409 collision).
      setError(err.message || 'Could not set the display name.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Display name">
      <form className="form" onSubmit={handleSubmit}>
        <p className="form__editing">
          Display name for “{metric}”{' '}
          <span className="muted">({isDerived ? 'the full name — kept too' : 'the lab’s name — kept too'})</span>
        </p>
        <div className="form__grid">
          <label>
            Shown as
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={isDerived ? 'e.g. NLR — leave blank for the default'
                                     : 'e.g. BUN — leave blank to use the lab name'}
            />
          </label>
        </div>
        <p className="form__hint">
          {isDerived
            ? 'Only changes what’s shown. This is a computed metric — clearing the field falls back to its default name.'
            : 'Only changes what’s shown. The lab name is kept too, so imports still resolve to this same metric.'}
        </p>
        {error && <p className="form__error">{error}</p>}
        <div className="form__actions">
          <button type="submit" disabled={submitting}>
            {submitting ? 'Saving…' : trimmed ? 'Save' : 'Clear'}
          </button>
          <button type="button" className="form__cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}
