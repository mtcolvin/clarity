import { useEffect, useState } from 'react'
import { getConditions, deleteCondition, getMedications, deleteMedication } from '../../api'
import ConditionList from './ConditionList'
import ConditionForm from './ConditionForm'
import MedicationList from './MedicationList'
import MedicationForm from './MedicationForm'
import Modal from '../Modal'
import Loading from '../shell/Loading'

// Conditions & Medications: two standalone record sections (status/dates, not
// values — no analysis touches them). list + add + EDIT (form-reuse, like the
// Metrics page's ObservationForm) + two-step delete for each. Each list loads on
// mount and after any add/edit/delete; the form is reused for add and edit,
// remounted via `key` so it pre-fills cleanly on Edit and resets on Cancel.
//
// Was a top-level PAGE; now a tab on Profile, which is where the rest of the permanent
// record already lives (demographics, physical measurements, timed collections) — the
// same register of "reference data about you", as opposed to the readings and events
// that change week to week. It renders no page title of its own: the tab names it, and
// the old <h2> would have restated "Profile" one line below the real one.
// `/conditions-medications` still resolves (App.jsx redirects it to this tab), so old
// bookmarks and any stale timeline link keep working.
//
// Each form opens as an OVERLAY from its section head. They used to stand permanently open
// at the top of their section, which put a six-field empty form between the heading and the
// records — so the common act (reading the list) paid for the rare one (adding a row). A
// dialog also fixes what the inline form needed a scrollIntoView to paper over: an edit
// form rendered at the top of the section could be nowhere near the row it belonged to.
// Add and edit are the same form in two modes, so opening either closes the other: two
// forms writing to one list is a way to lose an edit without noticing.
export default function ConditionsMedications() {
  const [conditions, setConditions] = useState(null)
  const [medications, setMedications] = useState(null)
  const [addingCondition, setAddingCondition] = useState(false)
  const [addingMedication, setAddingMedication] = useState(false)
  const [editingCondition, setEditingCondition] = useState(null)
  const [editingMedication, setEditingMedication] = useState(null)
  const [error, setError] = useState(null)
  const condFormOpen = addingCondition || editingCondition != null
  const medFormOpen = addingMedication || editingMedication != null

  function loadConditions() {
    return getConditions().then(setConditions).catch((e) => setError(e.message))
  }
  function loadMedications() {
    return getMedications().then(setMedications).catch((e) => setError(e.message))
  }

  useEffect(() => {
    loadConditions()
    loadMedications()
  }, [])

  function openAddCondition() {
    setEditingCondition(null)
    setAddingCondition(true)
  }
  function editCondition(c) {
    setAddingCondition(false)
    setEditingCondition(c)
  }
  function closeConditionForm() {
    setAddingCondition(false)
    setEditingCondition(null)
  }

  function openAddMedication() {
    setEditingMedication(null)
    setAddingMedication(true)
  }
  function editMedication(m) {
    setAddingMedication(false)
    setEditingMedication(m)
  }
  function closeMedicationForm() {
    setAddingMedication(false)
    setEditingMedication(null)
  }

  async function handleDeleteCondition(c) {
    try {
      await deleteCondition(c.id)
      // If the row being deleted is the one open in the form, close it — a form
      // pre-filled from a record that no longer exists would save a new one.
      setEditingCondition((cur) => (cur && cur.id === c.id ? null : cur))
      await loadConditions()
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleDeleteMedication(m) {
    try {
      await deleteMedication(m.id)
      setEditingMedication((cur) => (cur && cur.id === m.id ? null : cur))
      await loadMedications()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <section className="records">
      {error && <p className="error">Couldn’t reach the API: {error}</p>}

      <section className="records__section">
        <div className="records__head">
          <h3>Conditions</h3>
          {!condFormOpen && (
            <button type="button" onClick={openAddCondition}>+ Add condition</button>
          )}
        </div>
        <Modal
          open={condFormOpen}
          onClose={closeConditionForm}
          title={editingCondition ? 'Edit condition' : 'Add condition'}
        >
          <ConditionForm
            key={editingCondition?.id ?? 'new'}
            editing={editingCondition}
            onSaved={() => {
              closeConditionForm()
              loadConditions()
            }}
            onCancel={closeConditionForm}
          />
        </Modal>
        {conditions === null ? (
          <Loading what="conditions" />
        ) : (
          <ConditionList conditions={conditions} onEdit={editCondition} onDelete={handleDeleteCondition} />
        )}
      </section>

      <section className="records__section">
        <div className="records__head">
          <h3>Medications</h3>
          {!medFormOpen && (
            <button type="button" onClick={openAddMedication}>+ Add medication</button>
          )}
        </div>
        <Modal
          open={medFormOpen}
          onClose={closeMedicationForm}
          title={editingMedication ? 'Edit medication' : 'Add medication'}
        >
          <MedicationForm
            key={editingMedication?.id ?? 'new'}
            editing={editingMedication}
            onSaved={() => {
              closeMedicationForm()
              loadMedications()
            }}
            onCancel={closeMedicationForm}
          />
        </Modal>
        {medications === null ? (
          <Loading what="conditions" />
        ) : (
          <MedicationList medications={medications} onEdit={editMedication} onDelete={handleDeleteMedication} />
        )}
      </section>
    </section>
  )
}
