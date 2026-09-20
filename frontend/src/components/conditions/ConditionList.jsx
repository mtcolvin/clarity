import { useState } from 'react'

// Conditions table with Edit (form-reuse, like the readings table) and a two-step
// inline delete (Delete -> Confirm/Cancel). A resolved condition shows its
// resolution date alongside the onset date.
export default function ConditionList({ conditions, onEdit, onDelete }) {
  const [confirmingId, setConfirmingId] = useState(null)

  if (!conditions.length) {
    return <p className="muted">No conditions recorded yet.</p>
  }

  return (
    <table className="readings">
      <thead>
        <tr>
          <th>Name</th>
          <th>ICD-10</th>
          <th>Onset</th>
          <th>Status</th>
          <th>Notes</th>
          <th aria-label="actions" />
        </tr>
      </thead>
      <tbody>
        {conditions.map((c) => {
          const confirming = confirmingId === c.id
          return (
            <tr key={c.id}>
              <td>{c.name}</td>
              <td className="muted">{c.icd10 || '—'}</td>
              <td className="muted">
                {c.onset_on || '—'}
                {c.status === 'resolved' && (
                  <span className="records__resolved">
                    {' '}· {c.resolved_on ? `resolved on ${c.resolved_on}` : 'resolved (date unknown)'}
                  </span>
                )}
              </td>
              <td>{c.status}</td>
              <td className="muted">{c.notes || '—'}</td>
              <td className="readings__actions">
                {confirming ? (
                  <>
                    <button type="button" className="danger"
                            onClick={() => { setConfirmingId(null); onDelete(c) }}>
                      Confirm delete
                    </button>
                    <button type="button" onClick={() => setConfirmingId(null)}>Cancel</button>
                  </>
                ) : (
                  <>
                    <button type="button" onClick={() => onEdit(c)}>Edit</button>
                    <button type="button" onClick={() => setConfirmingId(c.id)}>Delete</button>
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
