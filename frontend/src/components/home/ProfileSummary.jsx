import { useEffect, useState } from 'react'
import { getProfile, getProfileHistory } from '../../api'
import WeightChart from '../profile/WeightChart'

// Glanceable CURRENT WEIGHT (plus a weight trend chart) on the home page, pulled
// from the Profile singleton's latest weight measurement and its history. Weight
// only — height rarely changes, so it stays on the Profile page. Renders nothing
// until loaded, on error, or when no weight has been recorded yet, so the home
// page never shows an empty placeholder.
//
// `recorded_on` is the stored ISO 'YYYY-MM-DD' string, shown verbatim per the date
// charter. Display-only: this reads the profile, it computes nothing. The chart
// (WeightChart) is likewise display-only — weight never enters the analysis engine.
export default function ProfileSummary() {
  const [weight, setWeight] = useState(null)
  const [history, setHistory] = useState([])
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([getProfile(), getProfileHistory('weight')])
      .then(([p, wh]) => {
        if (cancelled) return
        setWeight(p.weight ?? null)
        setHistory(wh)
      })
      .catch(() => !cancelled && setError(true))
    return () => {
      cancelled = true
    }
  }, [])

  if (error || !weight) return null

  // The current value rides INSIDE the chart container as its header (passed through
  // WeightChart → MetricChart), so the number and its trend read as one panel. Same
  // shape as the metric rail's latest reading: a big display-face figure, its unit
  // beside it, and the date it was recorded.
  const header = (
    <div className="profile-summary__line">
      <span className="stat__hero">
        <span className="stat__big">{weight.value}</span>
        <span className="stat__unit">{weight.unit}</span>
      </span>
      <span className="muted small">recorded {weight.recorded_on}</span>
    </div>
  )

  return (
    <section className="rsec">
      <h2 className="rsec__head">Weight</h2>
      <WeightChart history={history} header={header} />
    </section>
  )
}
