import { useState } from 'react'

// Medications table with a two-step inline delete, matching the readings/conditions
// tables. `active` is derived server-side (no end date) and shown as a badge; an
// ended medication shows its end date instead.
export default function MedicationList({ medications, onEdit, onDelete }) {
  const [confirmingId, setConfirmingId] = useState(null)

  if (!medications.length) {
    return <p className="muted">No medications recorded yet.</p>
  }

  return (
    <table className="readings">
      <thead>
        <tr>
          <th>Name</th>
          <th>Dose</th>
          <th>Frequency</th>
          <th>Start</th>
          <th>End</th>
          <th>Notes</th>
          <th aria-label="actions" />
        </tr>
      </thead>
      <tbody>
        {medications.map((m) => {
          const confirming = confirmingId === m.id
          return (
            <tr key={m.id}>
              <td>{m.name}</td>
              <td className="muted">{m.dose || '—'}</td>
              <td className="muted">{m.frequency || '—'}</td>
              <td className="muted">{m.start_date || '—'}</td>
              <td>
                {m.active ? (
                  <span className="badge badge--active">active</span>
                ) : (
                  <span className="muted">{m.end_date}</span>
                )}
              </td>
              <td className="muted">{m.notes || '—'}</td>
              <td className="readings__actions">
                {confirming ? (
                  <>
                    <button type="button" className="danger"
                            onClick={() => { setConfirmingId(null); onDelete(m) }}>
                      Confirm delete
                    </button>
                    <button type="button" onClick={() => setConfirmingId(null)}>Cancel</button>
                  </>
                ) : (
                  <>
                    <button type="button" onClick={() => onEdit(m)}>Edit</button>
                    <button type="button" onClick={() => setConfirmingId(m.id)}>Delete</button>
                  </>
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
