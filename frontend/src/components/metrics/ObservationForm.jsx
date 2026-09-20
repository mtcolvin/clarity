import { useEffect, useState } from 'react'
import { addObservation, updateObservation, resolveMetricName, getCollections } from '../../api'
import CollectionModal from './CollectionModal'

// Local (not UTC) today as YYYY-MM-DD, so the default matches the user's clock.
function todayISO() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const str = (v) => (v == null ? '' : String(v))

// Suggestions for qualitative results — a datalist (free text still allowed),
// since real qualitative results are highly varied.
const QUAL_SUGGESTIONS = [
  'Positive', 'Negative', 'Detected', 'Not Detected', 'Reactive', 'Non-reactive',
  'Normal', 'Abnormal', 'Yellow', 'Clear', 'Cloudy', 'Trace', 'Few', 'Moderate',
]

// Reused for both add and edit. `editing` (a row augmented with its metric) is
// non-null in edit mode; the parent remounts via key so initial state pre-fills
// cleanly. In edit mode the metric is locked, and the result-type is locked to
// the row's existing type (only numeric rows are editable — ObservationTable
// disables Edit on non-numeric ones — so editing behaves exactly as before).
export default function ObservationForm({ metrics, derivedMetrics = {}, unitByMetric = {}, editing, onSaved, onCancelEdit, onDirtyChange }) {
  const isEdit = Boolean(editing)
  const [metric, setMetric] = useState(editing?.metric ?? '')
  const [resultType, setResultType] = useState(editing?.result_type ?? 'numeric')
  const [value, setValue] = useState(str(editing?.value)) // numeric + censored
  const [valueText, setValueText] = useState(editing?.value_text ?? '') // qualitative
  const [normalText, setNormalText] = useState(editing?.normal_text ?? '') // qualitative expected-normal
  const [operator, setOperator] = useState(editing?.operator ?? '<') // censored
  const [unit, setUnit] = useState(editing?.unit ?? '')
  // Dimensionless (no unit) — a ratio/index like APTT Ratio or IGF-1 Z-Score. A
  // blank unit is a VALID unit (stored dimensionless metrics exist), so this is
  // opt-in intent, not an accidental omission: checking it clears+locks the unit
  // field and lifts the "unit required" rule. An existing metric whose unit is ''
  // auto-selects it (which also fixes: you couldn't otherwise add a reading to a
  // dimensionless metric, since the form always demanded a unit).
  const [dimensionless, setDimensionless] = useState((editing?.unit ?? null) === '')
  const [observedOn, setObservedOn] = useState(editing?.observed_on ?? todayISO())
  const [refLow, setRefLow] = useState(str(editing?.ref_low))
  const [refHigh, setRefHigh] = useState(str(editing?.ref_high))
  // Optional bound operators: '' = inclusive (the common case), or '<'/'<='/'>'/'>='
  // for a censored normal range (e.g. a normal of '≤10').
  const [refLowOp, setRefLowOp] = useState(editing?.ref_low_operator ?? '')
  const [refHighOp, setRefHighOp] = useState(editing?.ref_high_operator ?? '')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  // Add-mode only: a persistent green confirmation after a successful save,
  // showing which reading landed. Cleared once the form is edited again (below).
  const [saved, setSaved] = useState(null) // { metric, date } | null

  // Add-mode only: optional timed-collection linkage (create-first). Selecting a
  // collection fixes this reading's date to the collection's completion date (all its
  // analytes share it) and rides along as collection_id on save.
  const [collections, setCollections] = useState([])
  const [collectionId, setCollectionId] = useState(null)
  const [showNewCollection, setShowNewCollection] = useState(false)
  useEffect(() => {
    if (isEdit) return
    getCollections().then(setCollections).catch(() => setCollections([]))
  }, [isEdit])

  function chooseCollection(v) {
    if (v === '__new__') { setShowNewCollection(true); return }
    if (v === '') { setCollectionId(null); return }
    const id = Number(v)
    setCollectionId(id)
    const col = collections.find((c) => c.id === id)
    if (col) setObservedOn(col.completed_on) // analytes share the completion date
  }
  function handleCollectionCreated(col) {
    setShowNewCollection(false)
    setCollections((cs) => [col, ...cs])
    setCollectionId(col.id)
    setObservedOn(col.completed_on)
  }
  const collectionLabel = (c) =>
    `${c.completed_on} · ${c.kind}${c.volume_ml != null ? ` · ${c.volume_ml} mL` : ''}`

  // Dirty tracking for the modal's unsaved-changes guard. The baseline is a
  // snapshot of every field taken on mount (so an edit pre-fill isn't "dirty")
  // and reset after each save; PDF import is deliberately NOT tracked here.
  const fields = { metric, resultType, value, valueText, normalText, operator, unit, observedOn, refLow, refHigh, refLowOp, refHighOp, collectionId }
  const snapshot = JSON.stringify(fields)
  const [baseline, setBaseline] = useState(snapshot) // captured on mount, before any edit
  const dirty = snapshot !== baseline
  useEffect(() => {
    onDirtyChange?.(dirty)
  }, [dirty, onDirtyChange])

  // One unit per metric: once the metric is a known one, its unit is fixed, so
  // auto-fill and lock the field to prevent an accidental mismatch (the backend
  // also rejects mismatches as a backstop). Independent of result-type — it
  // always operates on the unit field; the type only changes whether unit is
  // required. A brand-new metric name leaves the unit free.
  const knownUnit = unitByMetric[metric.trim()]
  const unitLocked = isEdit || knownUnit != null

  // A COMPUTED metric can't be added directly — it's derived from its inputs. If the
  // typed name matches a derived metric, this holds its "computed from ..." caption
  // (naming the inputs to add instead), which gates submit and shows an inline hint.
  // Never fires in edit mode (the metric is a fixed non-derived stored row there).
  const derivedCaption = isEdit ? null : derivedMetrics[metric.trim()]

  // "Did you mean …?" — de-dup nudge for a metric name that would CREATE a new metric.
  // The backend already attaches an exact/alias/case match on its own; this catches the
  // fuzzy case (same analyte, different wording) BEFORE it fragments into a duplicate.
  // Advisory only: the user picks. Skipped in edit mode, for a known metric (the unit
  // lock already proves it exists), and for a derived name.
  const trimmedMetric = metric.trim()
  const mightBeNew = !isEdit && !derivedCaption && trimmedMetric.length >= 3 &&
                     knownUnit == null
  const [suggestions, setSuggestions] = useState([])
  useEffect(() => {
    if (!mightBeNew) {
      setSuggestions([])
      return
    }
    let cancelled = false
    // Debounced so typing doesn't hammer the endpoint.
    const t = setTimeout(() => {
      resolveMetricName(trimmedMetric)
        .then((r) => {
          if (cancelled) return
          // An `exact` hit needs no nudge — the write attaches to it automatically.
          setSuggestions(r.exact ? [] : r.suggestions)
        })
        .catch(() => { if (!cancelled) setSuggestions([]) })
    }, 350)
    return () => { cancelled = true; clearTimeout(t) }
  }, [trimmedMetric, mightBeNew])

  function handleMetricChange(name) {
    setMetric(name)
    const u = unitByMetric[name.trim()]
    if (u != null) { setUnit(u); setDimensionless(u === '') } // known metric: '' means dimensionless
  }

  function toggleDimensionless(checked) {
    setDimensionless(checked)
    if (checked) setUnit('') // dimensionless carries a blank unit
  }

  // Presentational input checks only — branches by result-type so numeric rules
  // never apply to the non-numeric paths.
  function validate() {
    if (!metric.trim()) return 'Metric is required.'
    if (derivedCaption) {
      return `“${metric.trim()}” is a computed metric — add its inputs instead. ${derivedCaption}`
    }
    if (resultType === 'qualitative') {
      if (!valueText.trim()) return 'Result text is required.'
    } else if (resultType === 'censored') {
      if (!operator) return 'Operator is required.'
      if (value.trim() === '' || Number.isNaN(Number(value))) return 'Value must be a number.'
      if (!dimensionless && !unit.trim()) return 'Unit is required.'
    }
    // Reference range (numeric + censored both use ref_low/ref_high as the
    // expected-normal; qualitative uses normal_text instead and has no range).
    if (resultType !== 'qualitative') {
      if (resultType === 'numeric' && !dimensionless && !unit.trim()) return 'Unit is required.'
      if (resultType === 'numeric'
          && (value.trim() === '' || Number.isNaN(Number(value)))) return 'Value must be a number.'
      const lo = refLow.trim() === '' ? null : Number(refLow)
      const hi = refHigh.trim() === '' ? null : Number(refHigh)
      if (lo !== null && Number.isNaN(lo)) return 'Reference low must be a number.'
      if (hi !== null && Number.isNaN(hi)) return 'Reference high must be a number.'
      if (lo !== null && hi !== null && lo > hi) return 'Reference low must be ≤ reference high.'
    }
    if (!observedOn) return 'Date is required.'
    return null
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setSubmitting(true)

    const body = {
      metric: metric.trim(),
      unit: unit.trim(),
      observed_on: observedOn,
      result_type: resultType,
    }
    if (!isEdit && collectionId) body.collection_id = collectionId
    if (resultType === 'qualitative') {
      body.value = null
      body.value_text = valueText.trim()
      if (normalText.trim() !== '') body.normal_text = normalText.trim()
    } else {
      // numeric + censored both use ref_low/ref_high for the expected-normal.
      body.value = Number(value)
      if (resultType === 'censored') body.operator = operator
      if (refLow.trim() !== '') body.ref_low = Number(refLow)
      if (refHigh.trim() !== '') body.ref_high = Number(refHigh)
      // Bound operators ride along only when the bound exists and an operator is
      // chosen; '' stays null (inclusive).
      if (refLow.trim() !== '' && refLowOp) body.ref_low_operator = refLowOp
      if (refHigh.trim() !== '' && refHighOp) body.ref_high_operator = refHighOp
    }

    try {
      if (isEdit) {
        await updateObservation(editing.id, body)
        onSaved(body.metric) // parent clears `editing`, remounting this as a blank add form
      } else {
        await addObservation(body)
        // Keep metric/unit/date/type for quick repeat entry; clear per-reading fields.
        setValue('')
        setValueText('')
        setNormalText('')
        setRefLow('')
        setRefHigh('')
        setRefLowOp('')
        setRefHighOp('')
        // Reset the dirty baseline to the post-save (cleared) field set, so the
        // form reads clean again right after saving, and show the confirmation.
        setBaseline(JSON.stringify({
          metric, resultType, value: '', valueText: '', normalText: '',
          operator, unit, observedOn, refLow: '', refHigh: '', refLowOp: '', refHighOp: '',
        }))
        setSaved({ metric: body.metric, date: body.observed_on })
        onSaved(body.metric)
      }
    } catch (err) {
      // sendJSON puts the backend's detail on err.message; for 409 that explains
      // either a duplicate date or a unit mismatch, both clear enough to surface.
      setError(err.message || 'Could not save the observation.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
    <form className="form" onSubmit={handleSubmit}>
      {/* The dialog header says "Edit reading"; this says WHICH one — the row it came
          from is behind the overlay. */}
      {isEdit && <p className="form__editing">{editing.observed_on}</p>}

      <div className="form__grid">
        <label>
          Metric
          {isEdit ? (
            <input value={metric} readOnly disabled />
          ) : (
            <>
              <input
                list="metric-options"
                value={metric}
                onChange={(e) => handleMetricChange(e.target.value)}
                placeholder="e.g. hba1c"
              />
              <datalist id="metric-options">
                {metrics.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              {derivedCaption && (
                <span className="form__hint">
                  Computed metric — add its inputs instead, not the result. {derivedCaption}
                </span>
              )}
              {suggestions.length > 0 && (
                <span className="form__hint form__suggest">
                  This would create a new metric. Did you mean{' '}
                  {suggestions.map((s, i) => (
                    <span key={s.metric}>
                      {i > 0 && ' / '}
                      <button type="button" className="form__suggest-pick"
                              onClick={() => handleMetricChange(s.metric)}>
                        {s.alias ? `${s.alias} (${s.metric})` : s.metric}
                      </button>
                    </span>
                  ))}
                  ?
                </span>
              )}
            </>
          )}
        </label>

        <label>
          Type
          <select
            value={resultType}
            onChange={(e) => setResultType(e.target.value)}
            disabled={isEdit}
            title={isEdit ? 'To change a reading’s type, delete it and add a new one' : undefined}
          >
            <option value="numeric">Numeric</option>
            <option value="qualitative">Qualitative</option>
            <option value="censored">Censored (&lt; &gt;)</option>
          </select>
        </label>

        {resultType === 'qualitative' ? (
          <label>
            Result
            <input
              list="qual-options"
              value={valueText}
              onChange={(e) => setValueText(e.target.value)}
              placeholder="e.g. Positive, Yellow"
            />
            <datalist id="qual-options">
              {QUAL_SUGGESTIONS.map((o) => (
                <option key={o} value={o} />
              ))}
            </datalist>
          </label>
        ) : null}

        {resultType === 'qualitative' && (
          <label>
            Expected <span className="optional">(optional)</span>
            <input
              list="qual-options"
              value={normalText}
              onChange={(e) => setNormalText(e.target.value)}
              placeholder="e.g. Negative"
            />
          </label>
        )}

        {resultType === 'censored' ? (
          <label>
            Value
            <span style={{ display: 'flex', gap: 4 }}>
              <select value={operator} onChange={(e) => setOperator(e.target.value)}>
                <option value="<">&lt;</option>
                <option value=">">&gt;</option>
                <option value="<=">&le;</option>
                <option value=">=">&ge;</option>
              </select>
              <input
                type="number"
                step="any"
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            </span>
          </label>
        ) : resultType === 'numeric' ? (
          <label>
            Value
            <input
              type="number"
              step="any"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </label>
        ) : null}

        <label>
          Unit {resultType === 'qualitative' && <span className="optional">(optional)</span>}
          <input
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder={dimensionless ? '— dimensionless —' : 'e.g. %'}
            readOnly={unitLocked || dimensionless}
            disabled={unitLocked || dimensionless}
          />
        </label>

        {/* Dimensionless opt-in (numeric/censored only — qualitative unit is already
            optional). Locked for a known metric/edit, where the unit is already fixed. */}
        {resultType !== 'qualitative' && (
          <label className="form__check">
            <input
              type="checkbox"
              checked={dimensionless}
              disabled={unitLocked}
              onChange={(e) => toggleDimensionless(e.target.checked)}
            />
            <span>No unit (dimensionless — e.g. a ratio or index)</span>
          </label>
        )}

        {/* Timed collection (add mode only): link this analyte to a 24h-urine-style
            collection. Choosing one fixes the date to the collection's completion date. */}
        {!isEdit && (
          <label>
            Timed collection <span className="muted">(optional)</span>
            <select value={collectionId ?? ''} onChange={(e) => chooseCollection(e.target.value)}>
              <option value="">— none (spot reading) —</option>
              {collections.map((c) => (
                <option key={c.id} value={c.id}>{collectionLabel(c)}</option>
              ))}
              <option value="__new__">+ New timed collection…</option>
            </select>
          </label>
        )}

        <label>
          Date
          <input
            type="date"
            value={observedOn}
            onChange={(e) => setObservedOn(e.target.value)}
            disabled={!isEdit && collectionId != null}
          />
          {!isEdit && collectionId != null && (
            <span className="form__hint">Set by the collection’s completion date.</span>
          )}
        </label>

        {/* Reference range = the expected-normal for both numeric and censored
            (censored normals are themselves numeric, e.g. "<5" with normal "<=10"
            → ref_high 10). Qualitative uses the Normal text field instead. */}
        {resultType !== 'qualitative' && (
          <>
            <label>
              Ref low <span className="optional">(optional)</span>
              {/* Small operator dropdown + value. '—' (blank) = inclusive, the
                  common case; '>' makes the lower bound strict (a censored normal). */}
              <span className="form__bound">
                <select
                  className="form__bound-op"
                  value={refLowOp}
                  onChange={(e) => setRefLowOp(e.target.value)}
                  aria-label="Ref low operator"
                >
                  <option value="">—</option>
                  <option value="<">&lt;</option>
                  <option value="<=">&le;</option>
                  <option value=">">&gt;</option>
                  <option value=">=">&ge;</option>
                </select>
                <input
                  type="number"
                  step="any"
                  value={refLow}
                  onChange={(e) => setRefLow(e.target.value)}
                />
              </span>
            </label>

            <label>
              Ref high <span className="optional">(optional)</span>
              <span className="form__bound">
                <select
                  className="form__bound-op"
                  value={refHighOp}
                  onChange={(e) => setRefHighOp(e.target.value)}
                  aria-label="Ref high operator"
                >
                  <option value="">—</option>
                  <option value="<">&lt;</option>
                  <option value="<=">&le;</option>
                  <option value=">">&gt;</option>
                  <option value=">=">&ge;</option>
                </select>
                <input
                  type="number"
                  step="any"
                  value={refHigh}
                  onChange={(e) => setRefHigh(e.target.value)}
                />
              </span>
            </label>
          </>
        )}
      </div>

      {error && <p className="form__error">{error}</p>}

      <div className="form__actions">
        <button type="submit" disabled={submitting || Boolean(derivedCaption)}>
          {submitting
            ? isEdit
              ? 'Saving…'
              : 'Adding…'
            : isEdit
              ? 'Save changes'
              : 'Add reading'}
        </button>
        {isEdit && (
          <button type="button" className="form__cancel" onClick={onCancelEdit}>
            Cancel
          </button>
        )}
        {/* Add-mode confirmation, right of the submit button. Hidden once the
            form is edited again (dirty), so it never reads as stale. */}
        {!isEdit && saved && !dirty && (
          <span className="form__saved">✓ Saved — {saved.metric}, {saved.date}</span>
        )}
      </div>
    </form>
    {!isEdit && (
      <CollectionModal
        open={showNewCollection}
        onClose={() => setShowNewCollection(false)}
        onCreated={handleCollectionCreated}
      />
    )}
    </>
  )
}
