import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getOverview, getChanges } from '../api'
import ProfileSummary from '../components/home/ProfileSummary'
import Overview from '../components/home/Overview'
import ChangesDigest from '../components/home/ChangesDigest'
import FullPictureExport from '../components/home/FullPictureExport'

// Home: the whole-tracker summary — the weight trend, what stands out across every
// metric, what moved recently, and the full-picture export.
//
// The page OWNS the two summary fetches (/overview and /changes) rather than letting
// each child fetch its own. Both endpoints return `total_metrics`, and the facts strip
// at the top counts across both, so a single fetch here is the only way the strip and
// the sections below it can't disagree. Children are presentational.
export default function HomePage() {
  const navigate = useNavigate()
  const [overview, setOverview] = useState(null)
  const [changes, setChanges] = useState(null)
  // The export flow is opened from the header button and takes the full width below it.
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    let cancelled = false
    getOverview().then((d) => !cancelled && setOverview(d)).catch(() => {})
    getChanges().then((d) => !cancelled && setChanges(d)).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const totalMetrics = overview?.total_metrics ?? changes?.total_metrics ?? null
  const flagged = overview?.current?.length ?? null
  const recentDays = changes?.recent_days ?? null
  const moved = changes?.moved?.length ?? null

  return (
    <div className="home">
      {/* Header: at-a-glance counts on the left, the page's one primary action on the
          right — the same shape as the Metrics page, where the metric's facts sit
          beside "+ Add reading". Counts only: each is a plain tally of what the engine
          produced, and the sections below say what they are. */}
      <div className="home__top">
        {totalMetrics != null && (
          <div className="home__facts">
            <div className="stat">
              <span className="stat__k">Metrics tracked</span>
              <span className="stat__v">{totalMetrics}</span>
            </div>
            {flagged != null && (
              <div className="stat">
                <span className="stat__k">Flagged now</span>
                <span className="stat__v">{flagged}</span>
              </div>
            )}
            {moved != null && (
              <div className="stat">
                <span className="stat__k">Moved in {recentDays} days</span>
                <span className="stat__v">{moved}</span>
              </div>
            )}
          </div>
        )}
        <button
          type="button"
          className={`btn-primary${exporting ? ' btn-primary--active' : ''}`}
          aria-expanded={exporting}
          onClick={() => setExporting((e) => !e)}
        >
          Export full picture
        </button>
      </div>

      {/* Full width, and directly under the button that opened it: the preview is a wide
          table of everything about to leave the machine, and reading it is the safety
          step — it must not be squeezed into a column or pushed below the fold. */}
      {exporting && (
        <div className="home__wide">
          <FullPictureExport onClose={() => setExporting(false)} />
        </div>
      )}

      {/* Two columns, not one stack: full-width sections left long blank measures beside
          short content. The weight trend takes the wide column (a chart uses the width);
          the flag list and the digest read fine in a narrower one. */}
      <div className="home__main">
        <ProfileSummary />
      </div>

      {/* Both lists answer "what should I look at" — so they share ONE white panel and
          ONE scroll (.findings, the same container the Metrics page uses for current
          flags + notable readings), with each heading pinned while its rows scroll
          under it. Capped, so an expanded 48-row flag list can't run the page. */}
      <div className="home__side findings">
        <ChangesDigest data={changes} />
        <Overview
          data={overview}
          onSelectMetric={(metric) =>
            navigate(`/metrics?metric=${encodeURIComponent(metric)}`)
          }
        />
      </div>
    </div>
  )
}
