import { useMemo, useState } from 'react'
import ExportPanel from './ExportPanel'

// The export FLOW that renders below the metrics header, driven by which header button is
// active (`mode`): 'metric' exports the selected metric on its own; 'set' lets you pick an
// arbitrary set (with a one-click "select this metric's timed-collection panel" shortcut)
// and export it together. Each mounts ExportPanel in autoStart mode (the header button was
// the trigger), so the preview opens straight away; `onClose` returns to the header. The
// full-picture export lives on Home.
export default function MultiExportControls({ mode, selected, metrics, panelMetrics = [],
                                             aliasByMetric = {}, onClose }) {
  const [filter, setFilter] = useState('')
  const [chosen, setChosen] = useState(() => new Set())
  const [runSet, setRunSet] = useState(false)

  const label = (m) => aliasByMetric[m] || m
  const toggle = (m) =>
    setChosen((s) => {
      const n = new Set(s)
      n.has(m) ? n.delete(m) : n.add(m)
      return n
    })
  const chosenList = useMemo(() => metrics.filter((m) => chosen.has(m)), [metrics, chosen])
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return q ? metrics.filter((m) => label(m).toLowerCase().includes(q) || m.toLowerCase().includes(q)) : metrics
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metrics, filter, aliasByMetric])

  function closeSet() {
    setRunSet(false)
    onClose?.()
  }

  if (mode === 'none') return null

  if (mode === 'metric') {
    return (
      <ExportPanel key={`metric-export-${selected}`} metric={selected} autoStart onClose={onClose} />
    )
  }

  // mode === 'set'
  return (
    <section className="metrics__export-area">
      {!runSet ? (
        <div className="metrics__multi-select">
          <p className="muted small">
            Pick the metrics to export together, then preview. The model may float possible
            explanations across them — possibilities to raise with your clinician, not a diagnosis.
          </p>
          {panelMetrics.length > 1 && (
            <button type="button" className="baseline__link"
                    onClick={() => setChosen(new Set(panelMetrics))}>
              Select this metric’s timed-collection panel ({panelMetrics.length})
            </button>
          )}
          <input
            className="metrics__multi-select-filter"
            placeholder="Filter metrics…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className="metrics__multi-select-list">
            {shown.map((m) => (
              <label key={m} className="metrics__multi-select-item">
                <input type="checkbox" checked={chosen.has(m)} onChange={() => toggle(m)} />
                <span>{label(m)}</span>
              </label>
            ))}
            {shown.length === 0 && <p className="muted small">No metrics match.</p>}
          </div>
          <div className="metrics__export-area-actions">
            <button type="button" className="btn-primary" disabled={chosen.size === 0}
                    onClick={() => setRunSet(true)}>
              Preview export of {chosen.size} metric{chosen.size === 1 ? '' : 's'}
            </button>
            {chosen.size > 0 && (
              <button type="button" className="baseline__link" onClick={() => setChosen(new Set())}>
                Clear
              </button>
            )}
            <button type="button" className="baseline__link" onClick={closeSet}>Cancel</button>
          </div>
        </div>
      ) : (
        <ExportPanel
          key={`set-export-${chosenList.join('|')}`}
          metrics={chosenList}
          scopeLabel="Selected metrics"
          autoStart
          onClose={closeSet}
        />
      )}
    </section>
  )
}
