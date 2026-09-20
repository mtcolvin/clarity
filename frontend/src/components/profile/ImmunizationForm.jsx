import { useState } from 'react'
import { addImmunization, updateImmunization } from '../../api'

const EMPTY = { vaccine: '', administered_on: '', dose_label: '', amount: '',
                site: '', lot: '', notes: '' }

// A few common vaccines as a datalist — SUGGESTIONS only, never a closed list: the field
// stays free text because a record can name anything (a travel vaccine, a trial product,
// a brand rather than a component), and a dropdown that can't hold what your card says is
// worse than no dropdown.
const VACCINE_SUGGESTIONS = [
  'Influenza (quadrivalent)', 'COVID-19 (mRNA)', 'Tdap', 'Td booster',
  'MMR', 'Varicella', 'Hepatitis A', 'Hepatitis B', 'HPV',
  'Pneumococcal (PCV)', 'Meningococcal (MenACWY)', 'Shingles (RZV)', 'Polio (IPV)',
]

function fromEditing(editing) {
  if (!editing) return EMPTY
  return {
    vaccine: editing.vaccine ?? '',
    administered_on: editing.administered_on ?? '',
    dose_label: editing.dose_label ?? '',
    amount: editing.amount ?? '',
    site: editing.site ?? '',
    lot: editing.lot ?? '',
    notes: editing.notes ?? '',
  }
}

// Add/edit form for one immunization — ONE form in two modes, like ObservationForm and
// ConditionForm. Only the vaccine name is required; every other field is optional because
// a record recalled from a paper card may carry nothing else.
//
// The DATE is optional on purpose and an empty date saves as "unknown" rather than being
// rejected: a childhood shot with no date is a real record, and requiring one would push
// you to invent it. The form says so under the field instead of failing.
export default function ImmunizationForm({ editing, onSaved, onCancel }) {
  const [form, setForm] = useState(() => fromEditing(editing))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const isEdit = Boolean(editing)

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.vaccine.trim()) return setError('A vaccine name is required.')
    setError(null)
    setBusy(true)
    try {
      // Trim, and send empty optional fields as null so the record stores "unknown"
      // rather than "" — the list renders a dash for null, not a blank cell.
      const body = Object.fromEntries(
        Object.entries(form).map(([k, v]) => [k, v.trim() === '' ? null : v.trim()]),
      )
      if (isEdit) await updateImmunization(editing.id, body)
      else await addImmunization(body)
      onSaved()
    } catch (err) {
      setError(err.message || 'Could not save the immunization.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form" onSubmit={handleSubmit}>
      <label className="form__primary">
        Vaccine
        <input list="vaccine-options" value={form.vaccine} autoFocus
               onChange={(e) => set('vaccine', e.target.value)}
               placeholder="e.g. Influenza (quadrivalent)" />
        <datalist id="vaccine-options">
          {VACCINE_SUGGESTIONS.map((v) => <option key={v} value={v} />)}
        </datalist>
      </label>

      <div className="form__grid">
        <label>
          Date given <span className="optional">(optional)</span>
          <input type="date" value={form.administered_on}
                 onChange={(e) => set('administered_on', e.target.value)} />
          <span className="form__hint">
            Leave blank if you don’t know it — the record is kept as “date unknown”
            rather than guessed.
          </span>
        </label>
        {/* Two different questions, so two fields: WHICH dose in the series, and HOW
            MUCH went in. A single "dose" box would have to hold both "Booster" and
            "0.5 mL". */}
        <label>
          Dose <span className="optional">(optional)</span>
          <input value={form.dose_label} onChange={(e) => set('dose_label', e.target.value)}
                 placeholder="e.g. Dose 1, Booster, 2025-26 season" />
        </label>
        <label>
          Amount <span className="optional">(optional)</span>
          <input value={form.amount} onChange={(e) => set('amount', e.target.value)}
                 placeholder="e.g. 0.5 mL" />
          <span className="form__hint">
            The volume given, with its unit — stored as the record prints it.
          </span>
        </label>
        <label>
          Site <span className="optional">(optional)</span>
          <input value={form.site} onChange={(e) => set('site', e.target.value)}
                 placeholder="e.g. left deltoid" />
        </label>
        <label>
          Lot <span className="optional">(optional)</span>
          <input value={form.lot} onChange={(e) => set('lot', e.target.value)}
                 placeholder="as printed on the record" />
        </label>
        <label>
          Notes <span className="optional">(optional)</span>
          <input value={form.notes} onChange={(e) => set('notes', e.target.value)} />
        </label>
      </div>

      {error && <p className="form__error">{error}</p>}

      <div className="form__actions">
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Add immunization'}
        </button>
        <button type="button" className="form__cancel" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  )
}
