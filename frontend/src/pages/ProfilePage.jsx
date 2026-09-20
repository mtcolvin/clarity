import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  getProfile, updateProfile, getProfileHistory, deleteProfileMeasurement,
} from '../api'
import MeasurementSection from '../components/profile/MeasurementSection'
import WeightChart from '../components/profile/WeightChart'
import CollectionsManager from '../components/profile/CollectionsManager'
import ConditionsMedications from '../components/conditions/ConditionsMedications'
import Immunizations from '../components/profile/Immunizations'
import Tabs from '../components/shell/Tabs'
import Modal from '../components/Modal'
import Loading from '../components/shell/Loading'

const SEX_OPTIONS = [
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'other', label: 'Other' },
]

// Profile-page tabs. Everything here is the PERMANENT record — reference data about you,
// as opposed to the readings and events that change week to week: demographics and physical
// measurements ("Profile"), the conditions and medications that used to be their own
// top-level page, and the timed collections (24h urine, etc.) that group analytes. None of
// it is high-traffic, and each was too small to earn a nav entry of its own. The active tab
// mirrors to ?tab= (the SettingsPage idiom) so refresh/bookmark are stable.
const PROFILE_TABS = [
  { id: 'profile', label: 'Profile' },
  { id: 'conditions', label: 'Conditions & medications' },
  { id: 'immunizations', label: 'Immunizations' },
  { id: 'collections', label: 'Collections' },
]
const PROFILE_TAB_IDS = PROFILE_TABS.map((t) => t.id)

const sexLabel = (value) => SEX_OPTIONS.find((o) => o.value === value)?.label ?? value

// Age from DOB — DISPLAY-ONLY date arithmetic on a demographic field. Computed
// client-side, never stored/sent/used by any analysis (distinct from the deferred
// health-metric derivations). Returns null for an unset/implausible DOB.
function ageFromDob(iso) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null
  const [y, m, d] = iso.split('-').map(Number)
  const today = new Date()
  let age = today.getFullYear() - y
  if (today.getMonth() + 1 < m || (today.getMonth() + 1 === m && today.getDate() < d)) age--
  return age >= 0 && age < 200 ? age : null
}

// The Profile section: permanent demographics (sex, DOB) + time-varying physical
// measurements (weight, height). Foundation data only — nothing here feeds any
// analysis, flag, or chart. Renders cleanly on a fresh install (everything unset).
export default function ProfilePage() {
  const [profile, setProfile] = useState(null) // null = still loading
  const [sex, setSex] = useState('')           // '' = unset (null)
  const [dob, setDob] = useState('')
  const [weightHist, setWeightHist] = useState([])
  const [heightHist, setHeightHist] = useState([])
  const [editingBasics, setEditingBasics] = useState(false)
  const [savingBasics, setSavingBasics] = useState(false)
  const [basicsMsg, setBasicsMsg] = useState(null) // { ok } | { error }
  const [error, setError] = useState(null)

  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(() => {
    const t = searchParams.get('tab')
    return PROFILE_TAB_IDS.includes(t) ? t : PROFILE_TAB_IDS[0]
  })
  useEffect(() => {
    setSearchParams({ tab: activeTab }, { replace: true })
  }, [activeTab, setSearchParams])

  function load() {
    return Promise.all([getProfile(), getProfileHistory('weight'), getProfileHistory('height')])
      .then(([p, wh, hh]) => {
        setProfile(p)
        setSex(p.sex ?? '')
        setDob(p.date_of_birth ?? '')
        setWeightHist(wh)
        setHeightHist(hh)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }
  useEffect(() => { load() }, [])

  // Open the edit form, seeding the inputs from the saved profile (discards any
  // stray edits from a previously-cancelled session).
  function startEditBasics() {
    setSex(profile.sex ?? '')
    setDob(profile.date_of_birth ?? '')
    setBasicsMsg(null)
    setEditingBasics(true)
  }

  function cancelEditBasics() {
    setSex(profile.sex ?? '')
    setDob(profile.date_of_birth ?? '')
    setBasicsMsg(null)
    setEditingBasics(false)
  }

  async function saveBasics(e) {
    e.preventDefault()
    setSavingBasics(true)
    setBasicsMsg(null)
    try {
      const updated = await updateProfile({ sex: sex || null, date_of_birth: dob || null })
      setProfile(updated)
      setBasicsMsg({ ok: true })
      setEditingBasics(false)
    } catch (err) {
      setBasicsMsg({ error: err.message || 'Could not save.' })
    } finally {
      setSavingBasics(false)
    }
  }

  // Reload the current value (from /profile) + that field's history after add/delete.
  async function reloadField(field) {
    const [p, hist] = await Promise.all([getProfile(), getProfileHistory(field)])
    setProfile(p)
    if (field === 'weight') setWeightHist(hist)
    else setHeightHist(hist)
  }

  async function deleteMeasurement(field, m) {
    try {
      await deleteProfileMeasurement(m.id)
      await reloadField(field)
    } catch (e) {
      setError(e.message)
    }
  }

  if (error && !profile) return <p className="error">Couldn’t reach the API: {error}</p>
  if (!profile) return <Loading what="profile" />

  // Read view reflects the saved profile; edit view reflects the working inputs.
  const age = ageFromDob(editingBasics ? dob : (profile.date_of_birth ?? ''))

  return (
    <section className="profile">
      <h2>Profile</h2>
      {error && <p className="error">Couldn’t reach the API: {error}</p>}
      <Tabs tabs={PROFILE_TABS} active={activeTab} onSelect={setActiveTab}
            ariaLabel="Profile sections">
      {activeTab === 'profile' && (
      <>
      <p className="muted small">
        Personal reference data, stored locally. Not used by any analysis or chart —
        it’s here for future calculations (BMI, age-adjusted contexts).
      </p>

      {/* Demographics: sex + DOB. Read-only by default; Edit reveals the form. */}
      <section className="profile__basics">
        <div className="profile__basics-head">
          <h3>Demographics</h3>
          {!editingBasics && (
            <button type="button" onClick={startEditBasics}>Edit</button>
          )}
        </div>

        <dl className="profile__facts">
          <div className="profile__fact">
            <dt>Sex</dt>
            <dd>
              {profile.sex
                ? sexLabel(profile.sex)
                : <span className="muted">Not set</span>}
              <span className="muted small"> · for medical reference context</span>
            </dd>
          </div>
          {/* --num: this value is a figure, so it takes the mono face; "Male" beside it
              is a word and stays in the body face. */}
          <div className="profile__fact profile__fact--num">
            <dt>Date of birth</dt>
            <dd>
              {profile.date_of_birth ? (
                <>
                  {profile.date_of_birth}
                  {age != null && <span className="muted small"> · {age} years</span>}
                </>
              ) : (
                <span className="muted">Not set</span>
              )}
            </dd>
          </div>
        </dl>
        {basicsMsg?.ok && <p className="form__saved">✓ Saved</p>}
      </section>

      <Modal open={editingBasics} onClose={cancelEditBasics} title="Edit demographics">
        <form className="form" onSubmit={saveBasics}>
          <fieldset className="profile__sex">
            <legend>Sex <span className="muted small">(for medical reference context)</span></legend>
            <div className="segmented">
              {SEX_OPTIONS.map((o) => (
                <label key={o.value} className="segmented__option">
                  <input type="radio" name="sex" value={o.value}
                         checked={sex === o.value} onChange={() => setSex(o.value)} />
                  <span>{o.label}</span>
                </label>
              ))}
            </div>
            {sex !== '' && (
              <button type="button" className="profile__clear" onClick={() => setSex('')}>
                Clear
              </button>
            )}
          </fieldset>

          <label className="profile__dob">
            Date of birth
            <input type="date" value={dob} onChange={(e) => setDob(e.target.value)} />
            {age != null
              ? <span className="muted small profile__age">Currently: {age} years</span>
              : <span className="muted small profile__age">No date of birth set yet.</span>}
          </label>

          <div className="form__actions">
            <button type="submit" disabled={savingBasics}>
              {savingBasics ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="form__cancel" onClick={cancelEditBasics} disabled={savingBasics}>
              Cancel
            </button>
            {basicsMsg?.error && <span className="form__error">{basicsMsg.error}</span>}
          </div>
        </form>
      </Modal>

      <MeasurementSection
        field="height" label="Height"
        current={profile.height} history={heightHist}
        onAdded={() => reloadField('height')}
        onDelete={(m) => deleteMeasurement('height', m)}
      />
      <MeasurementSection
        field="weight" label="Weight"
        current={profile.weight} history={weightHist}
        chart={<WeightChart history={weightHist} />}
        onAdded={() => reloadField('weight')}
        onDelete={(m) => deleteMeasurement('weight', m)}
      />
      </>
      )}
      {activeTab === 'conditions' && <ConditionsMedications />}
      {activeTab === 'immunizations' && <Immunizations />}
      {activeTab === 'collections' && <CollectionsManager />}
      </Tabs>
    </section>
  )
}
