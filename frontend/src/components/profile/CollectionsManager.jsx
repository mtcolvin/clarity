import { useEffect, useState } from 'react'
import { getCollections, getCollectionReadings, deleteCollection } from '../../api'
import CollectionModal from '../metrics/CollectionModal'
import { ChevronIcon } from '../icons'
import { displayValue, displayNormal } from '../metrics/readingFormat'
import { fixedFormatter, seriesDecimals } from '../../format'
import Loading from '../shell/Loading'

// Manage timed collections (24h urine, etc.) — the list/edit/delete view, mounted as a tab
// on the Profile page. Entry (create-first) also happens from the reading form; this is the
// home for reviewing and fixing a collection's shared context.
//
// Delete is gated: the backend refuses (409) while a collection still has readings. That
// used to render as the word "locked" beside Edit, which named a state without saying what
// was locked or why — so the DELETE BUTTON ITSELF is now disabled and carries the reason as
// its tooltip (and its aria-label, so it isn't mouse-only). A disabled control in the place
// the live one would be is self-explanatory in a way a separate word never is.
//
// Each row EXPANDS to list its analytes, because "5 readings" tells you a collection is
// full without telling you what is in it — and the readings live on their own metric pages,
// so the only way to see the set was to remember it. Fetched lazily per collection and
// cached, so opening a row costs one request and reopening costs none.
export default function CollectionsManager() {
  const [collections, setCollections] = useState(null) // null = loading
  const [error, setError] = useState(null)
  const [modal, setModal] = useState(null)      // { editing } (edit) | { editing: null } (new) | null
  const [confirmId, setConfirmId] = useState(null)
  const [openId, setOpenId] = useState(null)    // the expanded collection
  const [readings, setReadings] = useState({})  // id -> rows | 'loading' | 'error'

  function load() {
    return getCollections().then(setCollections).catch((e) => setError(e.message))
  }
  useEffect(() => { load() }, [])

  function toggle(id) {
    if (openId === id) return setOpenId(null)
    setOpenId(id)
    if (readings[id] !== undefined && readings[id] !== 'error') return
    setReadings((r) => ({ ...r, [id]: 'loading' }))
    getCollectionReadings(id)
      .then((rows) => setReadings((r) => ({ ...r, [id]: rows })))
      .catch(() => setReadings((r) => ({ ...r, [id]: 'error' })))
  }

  async function handleDelete(id) {
    try {
      await deleteCollection(id)
    } catch (e) {
      setError(e.message)
      return
    }
    setConfirmId(null)
    load()
  }

  if (error && collections === null) {
    return <p className="error">Couldn’t reach the API: {error}</p>
  }
  if (collections === null) return <Loading what="collections" />

  return (
    <div className="collections">
      <p className="muted small">
        Timed collections (e.g. 24-hour urine) group several analytes under one volume,
        duration, and date. Create one here or from the reading form, then add its analytes.
        Open a row to see which analytes it holds. A collection with readings can’t be
        deleted until those are removed first.
      </p>
      <button type="button" className="btn-primary" onClick={() => setModal({ editing: null })}>
        + New collection
      </button>
      {error && <p className="form__error">{error}</p>}
      {collections.length === 0 ? (
        <p className="muted">No timed collections yet.</p>
      ) : (
        <table className="readings collections__table">
          <thead>
            <tr>
              <th aria-label="expand" /><th>Completed</th><th>Kind</th><th>Duration</th>
              <th>Volume</th><th>Readings</th><th>Notes</th><th aria-label="actions" />
            </tr>
          </thead>
          <tbody>
            {collections.map((c) => {
              const open = openId === c.id
              const rows = readings[c.id]
              return [
                <tr key={c.id} className={open ? 'is-open' : undefined}>
                  <td>
                    <button
                      type="button"
                      className={`collections__toggle${open ? ' collections__toggle--open' : ''}`}
                      aria-expanded={open}
                      aria-label={`${open ? 'Hide' : 'Show'} the analytes in the ${c.completed_on} collection`}
                      onClick={() => toggle(c.id)}
                    >
                      <ChevronIcon size={14} />
                    </button>
                  </td>
                  <td>{c.completed_on}</td>
                  <td className="muted">{c.kind}</td>
                  <td className="muted">{c.duration_hours != null ? `${c.duration_hours} h` : '—'}</td>
                  <td className="muted">{c.volume_ml != null ? `${c.volume_ml} mL` : '—'}</td>
                  <td className="muted">{c.n_readings}</td>
                  <td className="muted">{c.notes || '—'}</td>
                  <td className="readings__actions">
                    <button type="button" className="metrics__rename"
                            onClick={() => setModal({ editing: c })}>
                      Edit
                    </button>
                    {confirmId === c.id ? (
                      <>
                        <button type="button" className="danger"
                                onClick={() => handleDelete(c.id)}>Confirm</button>
                        <button type="button" onClick={() => setConfirmId(null)}>Cancel</button>
                      </>
                    ) : (
                      // Disabled rather than hidden or replaced by a word: the control
                      // stays where you look for it and explains its own state.
                      <button
                        type="button"
                        disabled={c.n_readings > 0}
                        title={c.n_readings > 0
                          ? `Can’t delete: this collection still has ${c.n_readings} reading${c.n_readings === 1 ? '' : 's'}. Remove or reassign them first.`
                          : undefined}
                        onClick={() => setConfirmId(c.id)}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>,
                open && (
                  <tr key={`${c.id}-analytes`} className="collections__panel-row">
                    <td colSpan={8}>
                      <div className="collections__panel">
                        {rows === 'loading' && <Loading what="analytes" inline />}
                        {rows === 'error' && (
                          <p className="form__error">Couldn’t load this collection’s analytes.</p>
                        )}
                        {Array.isArray(rows) && rows.length === 0 && (
                          <p className="muted small">
                            No analytes yet — add readings from the entry form and choose this
                            collection.
                          </p>
                        )}
                        {Array.isArray(rows) && rows.length > 0 && (
                          <ul className="collections__analytes">
                            {/* Decimals are computed PER ANALYTE, not across the set: these
                                are different tests in different units, so one shared
                                precision (the rule inside a single metric's series) would
                                print a pH to the decimals a sodium needs. */}
                            {rows.map((r) => (
                              <li key={r.id}>
                                <span className="collections__analyte">{r.alias || r.metric}</span>
                                <span className="collections__analyte-value">
                                  {displayValue(r, fixedFormatter(seriesDecimals([r])))}
                                </span>
                                <span className="collections__analyte-normal muted">
                                  {displayNormal(r, fixedFormatter(seriesDecimals([r])))}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </td>
                  </tr>
                ),
              ]
            })}
          </tbody>
        </table>
      )}
      {modal && (
        <CollectionModal
          key={modal.editing?.id ?? 'new'}
          open
          editing={modal.editing}
          onClose={() => setModal(null)}
          onCreated={() => { setModal(null); load() }}
          onSaved={() => { setModal(null); load() }}
        />
      )}
    </div>
  )
}
