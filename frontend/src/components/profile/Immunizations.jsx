import { useEffect, useState } from 'react'
import { getImmunizations, deleteImmunization } from '../../api'
import ImmunizationForm from './ImmunizationForm'
import Modal from '../Modal'
import SearchField from '../shell/SearchField'
import Loading from '../shell/Loading'

// The vaccination record — a Profile tab, alongside conditions & medications and timed
// collections. It was a top-level nav entry showing a "Coming soon" stub; it now holds
// real records, in the same permanent-record register as the tabs beside it.
//
// Same shape as the conditions/medications sections: a ruled head whose one action opens
// the form, one form in two modes (add / edit) so the two can't validate differently, and
// a two-step delete per row. Nothing here is analysed — an immunization has a date and a
// name, never a value, so no detector, chart or flag touches it.
//
// The form opens as an OVERLAY rather than inline: an inline form pushes the list it is
// about down the page, so adding a record hides the records you were reading, and an edit
// form can end up nowhere near the row it belongs to. The dialog keeps the list still and
// makes the form's scope unambiguous.
export default function Immunizations() {
  const [rows, setRows] = useState(null)   // null = loading
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState(null)
  const [confirmingId, setConfirmingId] = useState(null)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')

  const formOpen = adding || editing != null

  // Filtered in the browser, across every text field a record carries: the whole list is
  // already loaded (it is a few dozen rows, not a corpus), so a search endpoint would be
  // a round-trip to re-send data the page is holding. Matching the LOT and the NOTES too
  // is the point — "which shot was lot 9549B" and "which came from the childhood card"
  // are exactly the questions a vaccination record gets asked.
  const q = query.trim().toLowerCase()
  const shown = !q ? (rows ?? []) : (rows ?? []).filter((r) =>
    [r.vaccine, r.administered_on, r.dose_label, r.amount, r.site, r.lot, r.notes]
      .some((f) => (f || '').toLowerCase().includes(q)),
  )

  function load() {
    return getImmunizations().then(setRows).catch((e) => setError(e.message))
  }
  useEffect(() => { load() }, [])

  function openAdd() { setEditing(null); setAdding(true) }
  function openEdit(r) { setAdding(false); setEditing(r) }
  function closeForm() { setAdding(false); setEditing(null) }

  async function handleDelete(r) {
    try {
      await deleteImmunization(r.id)
      // Close the form if it is showing the row being deleted — a form pre-filled from
      // a record that no longer exists would save a new one.
      setEditing((cur) => (cur && cur.id === r.id ? null : cur))
      setConfirmingId(null)
      await load()
    } catch (e) {
      setError(e.message)
    }
  }

  if (error && rows === null) {
    return <p className="error">Couldn’t reach the API: {error}</p>
  }

  return (
    <section className="records">
      <p className="muted small">
        Your vaccination history, kept on this machine like every other record here.
        Only the vaccine name is required — a shot you remember but can’t date is still
        worth recording, and is listed as “date unknown” rather than given a guessed date.
      </p>

      <section className="records__section">
        <div className="records__head">
          <h3>Immunizations</h3>
          <SearchField
            value={query}
            onChange={setQuery}
            label="Search immunizations"
            placeholder="Vaccine, lot, site, note…"
            count={q ? `${shown.length} match${shown.length === 1 ? '' : 'es'}` : null}
          />
          {!formOpen && (
            <button type="button" onClick={openAdd}>+ Add immunization</button>
          )}
        </div>

        <Modal
          open={formOpen}
          onClose={closeForm}
          title={editing ? 'Edit immunization' : 'Add immunization'}
        >
          <ImmunizationForm
            key={editing?.id ?? 'new'}
            editing={editing}
            onSaved={() => { closeForm(); load() }}
            onCancel={closeForm}
          />
        </Modal>

        {error && rows !== null && <p className="form__error">{error}</p>}

        {rows === null ? (
          <Loading what="immunizations" />
        ) : rows.length === 0 ? (
          <p className="muted">No immunizations recorded yet.</p>
        ) : shown.length === 0 ? (
          <p className="muted">Nothing matches “{query}”.</p>
        ) : (
          <table className="readings records__imm-table">
            <thead>
              <tr>
                <th>Date</th><th>Vaccine</th><th>Dose</th><th>Amount</th><th>Site</th>
                <th>Lot</th><th>Notes</th><th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id} className={editing?.id === r.id ? 'is-editing' : undefined}>
                  {/* An undated record says so rather than showing a bare dash: the
                      distinction between "no date recorded" and an empty cell matters
                      when the rest of the row is filled in. */}
                  <td className="records__imm-date">
                    {r.administered_on || <span className="muted">Date unknown</span>}
                  </td>
                  <td>{r.vaccine}</td>
                  <td className="muted">{r.dose_label || '—'}</td>
                  {/* An amount is a FIGURE with a unit, so it takes the mono face like
                      every other measured value the app prints. */}
                  <td className="muted records__imm-amount">{r.amount || '—'}</td>
                  <td className="muted">{r.site || '—'}</td>
                  <td className="muted records__imm-lot">{r.lot || '—'}</td>
                  <td className="muted">{r.notes || '—'}</td>
                  <td className="readings__actions">
                    {confirmingId === r.id ? (
                      <>
                        <button type="button" className="danger" onClick={() => handleDelete(r)}>
                          Confirm delete
                        </button>
                        <button type="button" onClick={() => setConfirmingId(null)}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button type="button" onClick={() => openEdit(r)}>Edit</button>
                        <button type="button" onClick={() => setConfirmingId(r.id)}>Delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </section>
  )
}
