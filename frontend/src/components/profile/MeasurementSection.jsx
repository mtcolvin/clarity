import { useState } from 'react'
import MeasurementForm from './MeasurementForm'
import Modal from '../Modal'

// One physical-measurement section (Weight or Height): the prominent CURRENT
// value, an "Update" toggle that reveals the inline add form, an optional `chart`
// slot (Weight passes a trend chart here; Height passes none), and the full history
// with edit + a two-step delete per row. Dates render as raw ISO (YYYY-MM-DD charter).
// Empty state: "No {label} recorded yet."
//
// Chart and history sit SIDE BY SIDE (.profile__body), not stacked: they are two views
// of one series, and stacking them pushed the numbers below the fold on a section that
// is mostly a short list. The history pane is capped to the chart's height and scrolls
// inside itself, so the section's height is set by the chart rather than by how many
// times you have weighed yourself. A section with no chart (Height) gets the full width
// for its list instead — a lone 30rem-capped column beside empty space reads as a
// missing chart.
export default function MeasurementSection({ field, label, current, history, chart, onAdded, onDelete }) {
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState(null)   // the measurement row being corrected
  const [confirmingId, setConfirmingId] = useState(null)

  // Add and edit are ONE form in two modes; opening either closes the other, so the
  // page never shows two forms writing to the same series.
  function openAdd() { setEditing(null); setAdding(true) }
  function openEdit(m) { setAdding(false); setEditing(m) }
  function closeForm() { setAdding(false); setEditing(null) }

  const formOpen = adding || editing != null

  return (
    <section className="profile__measure">
      <div className="profile__measure-head">
        <h3>{label}</h3>
        {!formOpen && (
          <button type="button" onClick={openAdd}>Update {label.toLowerCase()}</button>
        )}
      </div>

      {/* The current value is THE fact of this section, so it renders in the shared
          "labelled fact" vocabulary (.stat__*) the metric rail and Home's counts use —
          rather than a bolded sentence that happened to start with "Current:". */}
      <p className="profile__current">
        {current ? (
          <>
            <span className="stat__k">Current</span>
            <span className="stat__hero">
              <span className="stat__big">{current.value}</span>
              <span className="stat__unit">{current.unit}</span>
              <span className="muted small">updated {current.recorded_on}</span>
            </span>
          </>
        ) : (
          <span className="muted">No {label.toLowerCase()} recorded yet.</span>
        )}
      </p>

      {/* An overlay, not an inline form: inline, it pushed the chart and the history down
          the page — so updating your weight hid the trend you were looking at. */}
      <Modal
        open={formOpen}
        onClose={closeForm}
        title={`${editing ? 'Edit' : 'Add'} ${label.toLowerCase()}`}
      >
        <MeasurementForm
          key={editing ? `edit-${editing.id}` : 'add'}
          field={field}
          editing={editing}
          onSaved={() => { closeForm(); onAdded() }}
          onCancel={closeForm}
        />
      </Modal>

      {history.length > 0 && (
        <div className={`profile__body${chart ? '' : ' profile__body--nochart'}`}>
          {chart && <div className="profile__chart">{chart}</div>}
          <div className="profile__history">
            <table className="readings">
              <thead>
                <tr><th>Date</th><th>Value</th><th aria-label="actions" /></tr>
              </thead>
              <tbody>
                {history.map((m) => (
                  <tr key={m.id} className={editing?.id === m.id ? 'is-editing' : undefined}>
                    <td>{m.recorded_on}</td>
                    <td>{m.value} {m.unit}</td>
                    <td className="readings__actions">
                      {confirmingId === m.id ? (
                        <>
                          <button type="button" className="danger"
                                  onClick={() => { setConfirmingId(null); onDelete(m) }}>
                            Confirm delete
                          </button>
                          <button type="button" onClick={() => setConfirmingId(null)}>Cancel</button>
                        </>
                      ) : (
                        <>
                          <button type="button" onClick={() => openEdit(m)}>Edit</button>
                          <button type="button" onClick={() => setConfirmingId(m.id)}>Delete</button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}
