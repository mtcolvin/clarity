import { useState } from 'react'
import { seriesDecimals, fixedFormatter } from '../../format'
import { displayValue, displayNormal } from './readingFormat'

// Readings for the selected metric, newest first, each with edit + delete.
// Delete is two-step (Delete -> Confirm/Cancel) so nothing is removed on a
// single click; only one row can be armed at a time.
// Render a reading's value per result_type: numeric "133 mg/dL", censored
// "<5 mg/dL", qualitative "Positive". `fmt` applies the metric's shared decimal
// count so every value in the column reads with the SAME precision (14.0, not 14).
// A small "24h" chip for a reading that belongs to a timed collection, hovering to show
// the collection's volume/duration/completion. `collectionById` is the id -> record map;
// a missing entry still shows a bare chip (the link exists even if the record didn't load).
function collectionBadge(r, collectionById) {
  if (r.collection_id == null) return null
  const c = collectionById[r.collection_id]
  const label = c?.kind === '24h_urine' || !c?.kind ? '24h' : c.kind
  const bits = []
  if (c?.volume_ml != null) bits.push(`${c.volume_ml} mL`)
  if (c?.duration_hours != null) bits.push(`${c.duration_hours} h`)
  if (c?.completed_on) bits.push(`completed ${c.completed_on}`)
  const title = bits.length ? `Timed collection — ${bits.join(' · ')}` : 'Timed collection'
  return <span className="readings__coll" title={title}>{label}</span>
}

export default function ObservationTable({ series, flags = [], onEdit, onDelete, readOnly = false, collectionById = {} }) {
  const [confirmingId, setConfirmingId] = useState(null)
  const rows = [...series].reverse()
  // One decimal count for this metric's whole series, so the value + Expected
  // columns read uniformly (matches the chart's per-metric precision).
  const fmt = fixedFormatter(seriesDecimals(series))

  // Personal-baseline mode: map each reading's date to its personal_range flag so
  // the row can show the recontextualized (neutral) status instead of reading as
  // an out-of-range concern. `established` tells case 2 ("within your established
  // range") from case 3 (too little history yet — state only the lab-range fact).
  const personalRangeByDate = new Map(
    flags.filter((f) => f.kind === 'personal_range' && f.observed_on).map((f) => [f.observed_on, f]),
  )

  return (
    <table className="readings">
      <thead>
        <tr>
          <th>Date</th>
          <th>Value</th>
          <th>Expected</th>
          <th aria-label="actions" />
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          // Derived-metric rows have no stored id — key/confirm by observed_on
          // (unique per metric) so React keys don't collide on null.
          const rowKey = r.id ?? r.observed_on
          const confirming = confirmingId === rowKey
          const type = r.result_type ?? 'numeric'
          // Editable: numeric AND censored (the form + PUT round-trip both,
          // including the operator). Qualitative edit (value_text/normal_text) is
          // not wired yet, so it stays disabled.
          const editable = type !== 'qualitative'
          return (
            <tr key={rowKey}>
              <td>{r.observed_on}{collectionBadge(r, collectionById)}</td>
              <td>
                {displayValue(r, fmt)}
                {/* "not charted" applies only to genuinely-unplotted kinds.
                    Numeric (dots) AND censored (arrows) are charted now; only
                    qualitative (and future range-as-text) carry the badge. */}
                {type === 'qualitative' && (
                  <span className="muted small" title="Not plotted on the chart yet"> · not charted</span>
                )}
                {(() => {
                  const pr = personalRangeByDate.get(r.observed_on)
                  if (!pr) return null
                  return (
                    <span className="muted small baseline-tag">
                      {' '}· {pr.detail?.established
                        ? 'within your established range'
                        : 'outside lab range'}
                    </span>
                  )
                })()}
              </td>
              <td className="muted">{displayNormal(r, fmt)}</td>
              <td className="readings__actions">
                {readOnly ? (
                  // Derived (computed) metric: read-only, no edit/delete.
                  <span className="muted small">computed</span>
                ) : confirming ? (
                  <>
                    <button
                      type="button"
                      className="danger"
                      onClick={() => {
                        setConfirmingId(null)
                        onDelete(r)
                      }}
                    >
                      Confirm delete
                    </button>
                    <button type="button" onClick={() => setConfirmingId(null)}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onEdit(r)}
                      disabled={!editable}
                      title={editable ? undefined : 'Editing qualitative results is not supported yet'}
                    >
                      Edit
                    </button>
                    <button type="button" onClick={() => setConfirmingId(rowKey)}>
                      Delete
                    </button>
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
