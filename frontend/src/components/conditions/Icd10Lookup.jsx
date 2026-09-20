import { useState } from 'react'
import ICD10 from '../../data/icd10.json'

// A small, optional ICD-10 lookup helper for the condition form. SUGGESTION, not
// restriction: the code field stays free text; this just makes a common code easy
// to find by condition name. Picking a result fills BOTH name and code.
//
// Privacy posture: the list is a STATIC bundled asset (frontend/src/data/icd10.json,
// public-domain ICD-10-CM common subset). Filtering is 100% client-side — no
// network call, nothing leaves the machine.
const MAX_RESULTS = 20

export default function Icd10Lookup({ onPick }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')

  const q = query.trim().toLowerCase()
  const matches = q
    ? ICD10.filter(
        (e) => e.name.toLowerCase().includes(q) || e.code.toLowerCase().includes(q),
      ).slice(0, MAX_RESULTS)
    : []

  if (!open) {
    return (
      <button type="button" className="icd10__toggle" onClick={() => setOpen(true)}>
        Look up code
      </button>
    )
  }

  return (
    <div className="icd10">
      <div className="icd10__bar">
        <input
          type="text"
          className="icd10__search"
          placeholder="Search by condition (e.g. Gilbert, diabetes)…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />
        <button
          type="button"
          className="icd10__close"
          onClick={() => {
            setOpen(false)
            setQuery('')
          }}
        >
          Close
        </button>
      </div>
      {q && (
        <ul className="icd10__results">
          {matches.length === 0 ? (
            <li className="icd10__empty muted">No matches — you can type the name and code manually.</li>
          ) : (
            matches.map((e) => (
              <li key={e.code}>
                <button
                  type="button"
                  className="icd10__result"
                  onClick={() => {
                    onPick(e) // fills both name and code
                    setOpen(false)
                    setQuery('')
                  }}
                >
                  <span className="icd10__name">{e.name}</span>
                  <span className="icd10__code">{e.code}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}
