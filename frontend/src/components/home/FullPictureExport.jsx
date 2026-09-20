import { useEffect, useState } from 'react'
import { getMetrics } from '../../api'
import ExportPanel from '../metrics/ExportPanel'

// Export the FULL health picture to an external model — every metric as one bundle, so the
// model can float hedged possibilities across the whole picture (CLAUDE.md "Hypothesis
// floating & multi-metric scope"). A whole-account action, so it lives on Home rather than
// a single metric's page. Reuses ExportPanel's gated / scroll-gated-preview / confirmed
// flow; the preview groups the payload per metric so it stays reviewable at this scale.
//
// "Full picture" means the WHOLE record, not just the labs — `includeContext` adds the
// profile (sex, age, weight/height), conditions, medications, timeline events, imaging
// studies and the radiology report text. That context is what makes the labs legible: a
// creatinine trend reads differently on a drug that raises it, and an out-of-range result
// three days after a procedure is not the same finding as one out of nowhere. This is the
// ONLY export that sends it — a single metric or a panel stays minimal.
// Home drives this from a header BUTTON (see HomePage), so the panel mounts in
// `autoStart` mode — it opens straight into the preview rather than showing a second
// trigger of its own. `onClose` puts the button back in charge.
export default function FullPictureExport({ onClose }) {
  const [metrics, setMetrics] = useState(null)
  useEffect(() => {
    getMetrics()
      .then((rows) => setMetrics(rows.map((r) => r.metric)))
      .catch(() => setMetrics([]))
  }, [])
  if (!metrics || metrics.length === 0) return null
  return (
    <section className="rsec home__full-export">
      <h2 className="rsec__head">Full picture export</h2>
      <ExportPanel
        metrics={metrics}
        scopeLabel="Full health picture"
        includeContext
        autoStart
        onClose={onClose}
        triggerLabel={`Your full health picture — ${metrics.length} metrics, plus conditions, medications, events and imaging`}
      />
    </section>
  )
}
