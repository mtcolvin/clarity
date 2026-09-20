import { useEffect, useState } from 'react'
import { getBaselineExplainer, dismissBaselineExplainer, getSettings } from '../../api'
import { InfoCircleIcon } from '../icons'
import { baselineExplainerCopy } from './baselineExplainerCopy'

// The auto-once welcome explainer: shows exactly once, the first time
// GET /baseline-explainer reports unseen, then never again once dismissed.
// Entirely self-contained — its own fetch/dismiss state, isolated from the
// chart/flags/BaselineMode. A failed fetch just leaves it hidden (never
// blocks the page); a failed dismiss POST just means it may show again next
// visit, an acceptable, harmless degradation.
export default function BaselineExplainer() {
  const [seen, setSeen] = useState(true) // hidden by default until the fetch resolves otherwise
  const [copy, setCopy] = useState(null) // null until the live threshold values are in hand

  useEffect(() => {
    let cancelled = false
    Promise.all([getBaselineExplainer(), getSettings()])
      .then(([explainer, settings]) => {
        if (cancelled) return
        const byKey = Object.fromEntries(settings.map((s) => [s.key, s.value]))
        setCopy(
          baselineExplainerCopy({
            suggestFraction: byKey.personal_baseline_suggest_min_fraction,
            suggestMinReadings: byKey.personal_baseline_suggest_min_readings,
          }),
        )
        setSeen(explainer.seen)
      })
      .catch(() => {}) // stay hidden — harmless if it never gets to show
    return () => {
      cancelled = true
    }
  }, [])

  function dismiss() {
    setSeen(true) // hide immediately; don't wait on the network
    dismissBaselineExplainer().catch(() => {}) // best-effort — may reshow next visit if this fails
  }

  if (seen || !copy) return null

  return (
    <section className="baseline baseline--explainer" role="note">
      <div className="baseline__row">
        <InfoCircleIcon size={17} offset />
        <p className="baseline__msg">{copy}</p>
      </div>
      <div className="baseline__actions baseline__actions--end">
        <button type="button" className="baseline__primary-btn" onClick={dismiss}>
          Got it
        </button>
      </div>
    </section>
  )
}
