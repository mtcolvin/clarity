import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getMetrics, getObservations, getFlags, getHistory, getChartConfig, deleteObservation, getCollections, getMetricPanel, getMetricSettings, saveMetricSettings } from '../api'
import Modal from '../components/Modal'
import ActionMenu from '../components/ActionMenu'
import { GearIcon } from '../components/icons'
import MetricPicker from '../components/metrics/MetricPicker'
import MetricChart from '../components/metrics/MetricChart'
import QualitativeTimeline from '../components/metrics/QualitativeTimeline'
import FlagList from '../components/metrics/FlagList'
import HistoryPanel from '../components/metrics/HistoryPanel'
import MultiExportControls from '../components/metrics/MultiExportControls'
import BaselineMode, { MIN_COMPUTABLE_READINGS } from '../components/metrics/BaselineMode'
import BaselineExplainer from '../components/metrics/BaselineExplainer'
import ObservationForm from '../components/metrics/ObservationForm'
import ObservationTable from '../components/metrics/ObservationTable'
import { valueOnly, displayNormal } from '../components/metrics/readingFormat'
import ChartLegend from '../components/metrics/ChartLegend'
import { seriesDecimals, fixedFormatter } from '../format'
import DisplayNameModal from '../components/metrics/DisplayNameModal'
import UnitModal from '../components/metrics/UnitModal'
import GroupModal from '../components/metrics/GroupModal'
import Loading from '../components/shell/Loading'

// The Metrics section: ALL the single-metric apparatus that used to live in the
// dashboard — entry form, PDF import, picker, chart, flag list, history, summary,
// baseline-mode control, and the readings table. The orchestration here (state,
// effects, handlers) is lifted verbatim out of the old App.jsx; only two things
const LAST_METRIC_KEY = 'ht-last-metric'

// Which metric the page opens on when the URL doesn't name one.
//
// It used to be `names[0]` — the first metric ALPHABETICALLY, which on this record is
// "24Hr Urine - Copper 24Hr", because digits sort before letters. That is an accident of
// collation, not a choice, and it meant the page opened on a one-off urine collection
// from two years ago every single time.
//
// Now: the metric you looked at LAST (remembered per browser, like the theme), else the
// most recently MEASURED one — which is what "where is my record right now" actually
// means — else, only if neither is available, the alphabetical first.
function defaultMetric(rows) {
  if (!rows.length) return ''
  const names = rows.map((r) => r.metric)
  try {
    const last = localStorage.getItem(LAST_METRIC_KEY)
    if (last && names.includes(last)) return last
  } catch { /* storage disabled — fall through to the data-driven default */ }
  // `latest_on` is null for a DERIVED metric (it has no stored rows of its own), so a
  // computed metric never becomes the default — which is right: it is a view of other
  // metrics, not the thing you measured.
  const dated = rows.filter((r) => r.latest_on)
  if (dated.length) {
    return dated.reduce((a, b) => (b.latest_on > a.latest_on ? b : a)).metric
  }
  return names[0]
}

// change for routing: the selected metric is mirrored in the URL as ?metric=<name>
// (so the view is bookmarkable and survives refresh / cross-page navigation), and
// the page no longer owns the header or the Overview/ChangesDigest (those are the
// shell's and Home's now).
export default function MetricsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  // The metric named in the URL, captured ONCE as the initial preference; after
  // mount, `selected` owns the choice and writes it back to the URL.
  const [initialMetric] = useState(() => searchParams.get('metric') || undefined)
  const [metrics, setMetrics] = useState(null) // null = still loading the list
  const [unitByMetric, setUnitByMetric] = useState({}) // metric name -> current unit
  // Derived (computed) metrics: name -> its "computed from ..." caption. A derived
  // metric is read-only — no add/edit/delete/rename, and its chart gaps don't bridge.
  const [derivedByMetric, setDerivedByMetric] = useState({})
  // Derived metrics that are a documented EXCEPTION to the "clinically standard" bar
  // (e.g. NLR): name -> warning-level advisory text, rendered prominently. Empty for
  // every standard metric.
  const [advisoryByMetric, setAdvisoryByMetric] = useState({})
  // Verbose (lab) label -> shorthand DISPLAY label. Presentation only: `selected` and
  // every API call stay on the verbose label, which is the stable one the routes use;
  // both labels resolve to the same metric_id (the match key). Empty for metrics with no
  // alias set (they show their lab name).
  const [aliasByMetric, setAliasByMetric] = useState({})
  // Metric names with ≥1 reading in a timed collection (24h urine, etc.) — drives the
  // picker's "Timed collections" optgroup so they cluster without a name prefix.
  const [collectionMetrics, setCollectionMetrics] = useState([])
  // Canonical name -> USER GROUP label (e.g. an arterial blood-gas panel). Drives the
  // picker's per-group optgroups. Empty for ungrouped metrics.
  const [groupByMetric, setGroupByMetric] = useState({})
  // id -> collection record, for the readings-table "24h" badge + its volume/duration tooltip.
  const [collectionById, setCollectionById] = useState({})
  // The selected metric's "panel" (metrics sharing a timed collection with it) — drives the
  // "export this panel" multi-metric action. Empty for a metric with no collection.
  const [panelMetrics, setPanelMetrics] = useState([])
  // Which export flow is open below the header: 'none' | 'metric' | 'set'. The two header
  // buttons toggle it; the export UI renders below the picker so the header stays a header.
  const [exportMode, setExportMode] = useState('none')
  const [selected, setSelected] = useState('')
  const [series, setSeries] = useState([])
  const [flags, setFlags] = useState([])
  const [history, setHistory] = useState(null) // grouped historical anomalies { metric, groups }
  const [chartConfig, setChartConfig] = useState(null) // { thresholds, personal_baseline_mean }
  // MetricChart's own computed X-domain, reported up via its onDomainChange —
  // feeds QualitativeTimeline's "mixed case" (a metric with BOTH a numeric
  // chart and qualitative rows) so the strip aligns to the SAME date domain
  // instead of computing its own from just the qualitative dates. Tagged with
  // the metric name so a stale domain from the PREVIOUS metric can never leak
  // into the current one before the new chart's effect fires (checked at the
  // render site below via chartDomain?.metric === selected) — no reset effect
  // needed, the tag makes staleness self-correcting.
  const [chartDomain, setChartDomain] = useState(null) // { metric, domain, ticks, step } | null
  // The selected metric's personal-baseline settings. Owned HERE rather than inside
  // BaselineMode because two surfaces render from them — the Manage-metric menu item
  // that turns the mode on/off, and BaselineMode's own active/suggestion callouts —
  // and two independent fetches of one setting could disagree.
  const [baselineSettings, setBaselineSettings] = useState(null) // { metric, ...settings }
  const [error, setError] = useState(null)
  const [loadingMetric, setLoadingMetric] = useState(false)
  const [reloadKey, setReloadKey] = useState(0) // bump to force a series/flags refetch
  const [editing, setEditing] = useState(null) // row being edited (with metric), or null
  const [modalOpen, setModalOpen] = useState(false) // add/edit modal visibility
  const [formDirty, setFormDirty] = useState(false) // form has unsaved changes
  const [discarding, setDiscarding] = useState(false) // inline "Discard changes?" banner armed
  const [namingDisplay, setNamingDisplay] = useState(false) // display-name modal visibility
  const [editingUnit, setEditingUnit] = useState(false) // unit-relabel modal visibility
  const [editingGroup, setEditingGroup] = useState(false) // group modal visibility

  // Re-fetch the (server-authoritative) metric list. Keeps the picker honest as
  // metrics appear (first reading) or vanish (last reading deleted). Selection:
  // prefer `preferred`, else keep the current one if it still exists, else first.
  function loadMetrics(preferred) {
    // Refresh the collection map alongside metrics (a new reading may have created one);
    // fire-and-forget so it doesn't gate the picker. Powers the table's "24h" badge.
    getCollections()
      .then((cs) => setCollectionById(Object.fromEntries(cs.map((c) => [c.id, c]))))
      .catch(() => setCollectionById({}))
    return getMetrics()
      .then((rows) => {
        // `/metrics` returns [{ metric, unit }]; keep names as the array the rest
        // of the UI expects, and a name->unit map for the form's unit lock.
        const names = rows.map((r) => r.metric)
        setMetrics(names)
        setUnitByMetric(Object.fromEntries(rows.map((r) => [r.metric, r.unit])))
        setDerivedByMetric(
          Object.fromEntries(
            rows.filter((r) => r.derived).map((r) => [r.metric, r.derived_description]),
          ),
        )
        setAdvisoryByMetric(
          Object.fromEntries(
            rows
              .filter((r) => r.derived && r.derived_advisory)
              .map((r) => [r.metric, r.derived_advisory]),
          ),
        )
        setAliasByMetric(
          Object.fromEntries(rows.filter((r) => r.alias).map((r) => [r.metric, r.alias])),
        )
        setCollectionMetrics(rows.filter((r) => r.in_collection).map((r) => r.metric))
        setGroupByMetric(
          Object.fromEntries(rows.filter((r) => r.group).map((r) => [r.metric, r.group])),
        )
        setSelected((cur) =>
          preferred && names.includes(preferred)
            ? preferred
            : names.includes(cur)
              ? cur
              : defaultMetric(rows),
        )
      })
      .catch((e) => setError(e.message))
  }

  // Load the metric list once on mount, preferring the metric named in the URL
  // (?metric=) — this is how a Home → Overview click, a bookmark, or a refresh
  // lands directly on a specific metric.
  useEffect(() => {
    loadMetrics(initialMetric)
  }, [initialMetric])

  // Keep the URL's ?metric= in step with the selected metric, so refresh and
  // bookmarking reflect what's on screen. `replace` so picking metrics doesn't
  // pile up history entries. Skipped while empty (e.g. an empty DB).
  useEffect(() => {
    if (!selected) return
    setSearchParams({ metric: selected }, { replace: true })
    // Remembered so the next visit opens here rather than at whatever sorts first.
    try { localStorage.setItem(LAST_METRIC_KEY, selected) } catch { /* not fatal */ }
  }, [selected, setSearchParams])

  // The selected metric's panel (its collection siblings) for the "export this panel"
  // action — empty for a derived or non-collection metric.
  useEffect(() => {
    if (!selected || selected in derivedByMetric) {
      setPanelMetrics([])
      return
    }
    let cancelled = false
    getMetricPanel(selected)
      .then((r) => !cancelled && setPanelMetrics(r.panel))
      .catch(() => !cancelled && setPanelMetrics([]))
    return () => { cancelled = true }
  }, [selected, derivedByMetric])

  // Personal-baseline settings for the selected metric. TAGGED with the metric they
  // were fetched for — the same self-correcting trick chartDomain uses above — so the
  // previous metric's mode can't render against the new one while its fetch is in
  // flight, without an effect that resets state up front.
  useEffect(() => {
    if (!selected || selected in derivedByMetric) return
    let cancelled = false
    getMetricSettings(selected)
      .then((d) => !cancelled && setBaselineSettings({ metric: selected, ...d }))
      .catch(() => !cancelled && setBaselineSettings(null))
    return () => { cancelled = true }
  }, [selected, derivedByMetric])

  // Save a settings patch, then refetch the metric so the chart/table/history reflect
  // the recontextualized (or restored) flags. Returns the updated settings so the
  // caller (BaselineMode's note editor) can sync its draft.
  async function applyBaselineSettings(patch) {
    const updated = await saveMetricSettings(selected, patch)
    setBaselineSettings({ metric: selected, ...updated })
    setReloadKey((k) => k + 1)
    return updated
  }

  // Reload series + flags whenever the selected metric changes. The `cancelled`
  // guard drops responses from a stale selection if the user switches quickly.
  useEffect(() => {
    // No metric selected only happens when the list is empty: loadMetrics resolves
    // `selected` to a real name otherwise, in the same batched update as setMetrics,
    // and the body render is gated on metrics.length — so there's no stale state to
    // clear here. Just skip the fetch.
    if (!selected) return
    let cancelled = false
    // Loading flag set as THIS effect's own fetch begins — the set-state-in-effect
    // rule over-flags this legitimate effect-owned-fetch case (the post-fetch writes
    // below are already inside .then/.catch/.finally callbacks).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoadingMetric(true)
    Promise.all([
      getObservations(selected), getFlags(selected), getHistory(selected),
      getChartConfig(selected),
    ])
      .then(([s, f, h, cc]) => {
        if (cancelled) return
        setSeries(s)
        setFlags(f)
        setHistory(h)
        setChartConfig(cc)
        setError(null)
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoadingMetric(false))
    return () => {
      cancelled = true
    }
  }, [selected, reloadKey])

  // After an add or edit: refresh the metric list (an add can introduce a new
  // metric), select the saved metric, and force a series/flags refetch so the
  // change shows immediately. EDIT auto-closes the modal; ADD keeps it open (the
  // form clears itself and shows its own green confirmation for the next entry).
  function handleSaved(metric) {
    const wasEdit = editing != null
    setFormDirty(false)
    if (wasEdit) {
      setModalOpen(false)
      setEditing(null)
      setDiscarding(false)
    }
    loadMetrics(metric).then(() => setReloadKey((k) => k + 1))
  }

  // After setting a display name: close the modal and refresh the list. The SELECTION
  // is unchanged — an alias doesn't move the metric's identity (its canonical name), so
  // unlike a rename there's no new name to follow; only the label re-renders.
  function handleDisplayNameSet() {
    setNamingDisplay(false)
    loadMetrics(selected)
  }

  // After a unit relabel: close, refresh the metrics list (new unit) AND bump reloadKey so
  // the chart/table re-fetch the series — unlike an alias, a unit relabel changes the
  // readings' displayed unit, so the plotted series must be re-pulled.
  function handleUnitSet() {
    setEditingUnit(false)
    loadMetrics(selected).then(() => setReloadKey((k) => k + 1))
  }

  // After a group change: close and refresh the metrics list so the picker re-groups.
  // Group is display-only (picker optgroup) — the series is unaffected, so no reloadKey bump.
  function handleGroupSet() {
    setEditingGroup(false)
    loadMetrics(selected)
  }

  // Open the modal in add-mode (no row) — the "+ Add" trigger beside the picker.
  function openAdd() {
    setEditing(null)
    setFormDirty(false)
    setDiscarding(false)
    setModalOpen(true)
  }

  // Edit a table row → open the modal pre-filled (replaces the old scroll-to-form).
  function handleEdit(row) {
    setEditing({ ...row, metric: selected }) // augment with the (locked) metric
    setFormDirty(false)
    setDiscarding(false)
    setModalOpen(true)
  }

  // Single close channel for the modal. If the form has unsaved edits, arm the
  // inline discard banner instead of closing; otherwise close cleanly. (Saving
  // routes through handleSaved, which clears dirty first, so it never prompts.)
  const requestClose = useCallback(() => {
    if (formDirty) {
      setDiscarding(true)
      return
    }
    closeModal()
  }, [formDirty])

  // MetricChart's onDomainChange — see the chartDomain state comment above.
  // Tags the reported domain with the metric it was computed FOR (`selected`,
  // closed over here), which is what makes staleness self-correcting at the
  // render site without a separate reset effect.
  const handleChartDomain = useCallback((info) => {
    setChartDomain({ metric: selected, ...info })
  }, [selected])

  function closeModal() {
    setModalOpen(false)
    setEditing(null)
    setFormDirty(false)
    setDiscarding(false)
  }

  // The rail's facts. `series` is oldest-first (db.get_series), so the last row is the
  // latest reading; the formatter is the readings table's, so both render a value with
  // the same decimals. Empty while a metric has no readings — the rail then shows its
  // identity and actions only.
  const fmtValue = fixedFormatter(seriesDecimals(series))
  const latest = series.length ? series[series.length - 1] : null
  // Settings only count when they belong to the metric on screen (see the tag above).
  const baseline = baselineSettings?.metric === selected ? baselineSettings : null

  // Owns the delete API call + refresh; the table only handles the confirm UI.
  async function handleDelete(row) {
    try {
      await deleteObservation(row.id)
    } catch (e) {
      setError(e.message)
      return
    }
    setEditing((cur) => (cur && cur.id === row.id ? null : cur))
    await loadMetrics()
    setReloadKey((k) => k + 1)
  }

  return (
    <>
      {error && <p className="error">Couldn’t reach the API: {error}</p>}

      {metrics === null && !error && <Loading what="metrics" />}

      {metrics !== null && (
        <>
          {/* No "Metrics" page title: the metric's own name is the page heading, in
              the rail below. A title above a picker that names the same thing said it
              twice. The nav still marks which section you're in. */}
          {/* Personal-baseline explainer: an auto-once welcome banner, first visit
              only (its own local fetch/dismiss state — see BaselineExplainer). Sits
              above the picker so it reads as a page-top explainer, not a per-metric
              note; renders regardless of whether any metric is selected yet. */}
          <BaselineExplainer />
          {metrics.length === 0 ? (
            <div className="metrics__empty">
              <p className="muted">No data yet.</p>
              <button type="button" className="btn-primary" onClick={openAdd}>
                + Add reading
              </button>
            </div>
          ) : (
            <>
              {/* The metric RAIL (left, sticky) states what you're looking at and what
                  you can do to it; the RECORD (right) is the metric itself, as ruled
                  sections with no cards. The identity and the actions therefore stay on
                  screen while the readings scroll, and the page has ONE heading — the
                  metric's own name — instead of a page title above a picker repeating it. */}
              <div className="metric">
                <aside className="metric__rail">
                  <h2 className="metric__name">{aliasByMetric[selected] || selected}</h2>
                  {/* No unit line here: it already rides the latest reading below, and
                      every value in the readings table carries it. */}
                  <div className="metric__pick-row">
                    <MetricPicker variant="pill"
                                  metrics={metrics} selected={selected} onChange={setSelected}
                                  derivedMetrics={derivedByMetric}
                                  aliasByMetric={aliasByMetric}
                                  collectionMetrics={collectionMetrics}
                                  groupByMetric={groupByMetric} />
                  </div>

                  {/* Notices about the metric itself sit with the metric's identity,
                      not above its chart: they qualify what you're looking at. All
                      three share one shape (.notice — a left rule, a label, flush
                      text) so a warning and a caption differ in colour and wording
                      rather than in layout. */}
                  {selected in advisoryByMetric && (
                    <p className="notice notice--warn" role="note">
                      <span className="notice__label">Not a standard test</span>
                      {advisoryByMetric[selected]}
                    </p>
                  )}
                  {/* Derived metric caption: names its inputs and that it's computed +
                      read-only, so the missing edit/add controls read as intentional. */}
                  {selected in derivedByMetric && (
                    <p className="notice">
                      <span className="notice__label">Computed</span>
                      {derivedByMetric[selected]}
                    </p>
                  )}
                  {/* Methodology note (#9): display-only prose for a metric whose
                      interpretation depends on another (e.g. BUN → read with creatinine).
                      Descriptive, never a flag. */}
                  {chartConfig?.methodology_note && (
                    <p className="notice">
                      <span className="notice__label">Read with</span>
                      {chartConfig.methodology_note}
                    </p>
                  )}
                  {/* Personal-baseline mode is a per-stored-metric setting; not offered
                      for a derived metric (it has no settings row of its own). Only its
                      ACTIVE and SUGGESTION states render here — turning it on is a
                      Manage-metric menu item (see the menu's "This metric" section). */}
                  {baseline && (
                    <BaselineMode
                      key={`baseline-${selected}`}
                      metric={selected}
                      data={baseline}
                      onApply={applyBaselineSettings}
                    />
                  )}

                  {/* Facts about the metric as a whole, from the series already loaded —
                      the latest reading and its interval read through the readings
                      table's own formatters, so the rail and the table can't disagree. */}
                  {latest && (
                    <>
                      <div className="stat">
                        <span className="stat__k">Latest</span>
                        <span className="stat__hero">
                          <span className="stat__big">{valueOnly(latest, fmtValue)}</span>
                          {latest.unit && <span className="stat__unit">{latest.unit}</span>}
                        </span>
                      </div>
                      <div className="stat">
                        <span className="stat__k">Drawn</span>
                        <span className="stat__v">{latest.observed_on}</span>
                      </div>
                      <div className="stat">
                        <span className="stat__k">Interval</span>
                        <span className="stat__v">{displayNormal(latest, fmtValue)}</span>
                      </div>
                      <div className="stat">
                        <span className="stat__k">Readings</span>
                        <span className="stat__v">
                          {series.length} since {series[0].observed_on}
                        </span>
                      </div>
                    </>
                  )}

                  <div className="metric__acts">
                    <button type="button" className="btn-primary" onClick={openAdd}>
                      + Add reading
                    </button>
                    {selected && (
                    <ActionMenu
                      label="Manage metric"
                      ariaLabel="Manage this metric"
                      icon={<GearIcon size={15} />}
                      sections={[
                        {
                          label: 'This metric',
                          items: [
                            // Setting a DISPLAY name works for both stored and derived
                            // (computed) metrics. This replaced the old "Rename": for a stored
                            // metric a rename REPLACES the lab-wording label (a future import
                            // under it would no longer resolve), whereas an alias ADDS a label;
                            // a derived metric has no lab label at all, so its alias is a pure
                            // display override.
                            {
                              key: 'display-name',
                              label: 'Edit display name',
                              hint: 'Show a shorthand label instead of the lab wording',
                              onSelect: () => setNamingDisplay(true),
                            },
                            // Personal-baseline mode: judge readings against this metric's own
                            // history instead of only the lab range. Offered once there are
                            // enough numeric readings to compute a baseline at all — the same
                            // hard floor BaselineMode enforces. A toggle, so it renders as a
                            // menuitemcheckbox and reads back its current state.
                            ...(baseline
                              && baseline.candidacy.numeric_count >= MIN_COMPUTABLE_READINGS
                              ? [{
                                  key: 'baseline',
                                  label: 'Track against your own baseline',
                                  hint: baseline.personal_baseline_mode
                                    ? 'On — readings are judged against your own history'
                                    : 'Judge readings against your own history, not just the lab range',
                                  active: baseline.personal_baseline_mode,
                                  onSelect: () => applyBaselineSettings({
                                    personal_baseline_mode: !baseline.personal_baseline_mode,
                                  }),
                                }]
                              : []),
                            // Relabel the metric's unit (not a value conversion), and assign it
                            // to a picker group — stored metrics only: a derived metric's unit
                            // is fixed by its computation and it already groups under "Computed".
                            ...(selected in derivedByMetric
                              ? []
                              : [
                                  {
                                    key: 'unit',
                                    label: 'Edit unit',
                                    hint: 'Relabel the unit — values are not converted',
                                    onSelect: () => setEditingUnit(true),
                                  },
                                  {
                                    key: 'group',
                                    label: 'Edit group',
                                    hint: 'Cluster this metric in the picker',
                                    onSelect: () => setEditingGroup(true),
                                  },
                                ]),
                          ],
                        },
                        {
                          label: 'Export',
                          items: [
                            {
                              key: 'export-metric',
                              label: 'Export this metric',
                              active: exportMode === 'metric',
                              onSelect: () =>
                                setExportMode((m) => (m === 'metric' ? 'none' : 'metric')),
                            },
                            {
                              key: 'export-set',
                              label: 'Export a set of metrics',
                              active: exportMode === 'set',
                              onSelect: () => setExportMode((m) => (m === 'set' ? 'none' : 'set')),
                            },
                          ],
                        },
                      ]}
                    />
                    )}
                  </div>
                </aside>

                <div className="metric__record">
              {/* The export flow for whichever menu item is active. */}
              <MultiExportControls
                mode={exportMode}
                selected={selected}
                metrics={metrics}
                panelMetrics={panelMetrics}
                aliasByMetric={aliasByMetric}
                onClose={() => setExportMode('none')}
              />

              {loadingMetric ? (
                <Loading what={selected} />
              ) : series.length === 0 ? (
                <p className="muted">No observations for {selected} yet.</p>
              ) : (
                <>
                  {/* The metric's notices (advisory / computed-from / read-with) and the
                      personal-baseline control live in the RAIL above, beside the
                      identity they qualify — not here above the chart. */}
                  {/* Trend. The legend is suppressed here and rendered below the
                      readings table instead — it's reference material you consult,
                      not something to read on the way to the numbers. */}
                  <section className="rsec">
                    <h3 className="rsec__head">Trend</h3>
                    <MetricChart
                      series={series}
                      flags={flags}
                      thresholds={chartConfig?.thresholds ?? []}
                      personalBaselineMean={chartConfig?.personal_baseline_mean ?? null}
                      onDomainChange={handleChartDomain}
                      legend={false}
                    />
                  </section>
                  {/* Qualitative timeline strip (#4): renders whenever this metric has
                      >=1 qualitative row — below the real chart in the mixed case
                      (today only Urine Protein), or as the ONLY visual in the
                      standalone case (23 of 24 qualitative-carrying metrics have zero
                      numeric readings, ever, so MetricChart above rendered only its
                      empty-state text). sharedAxis is passed ONLY when the domain
                      MetricChart just reported was computed for THIS metric — the
                      chartDomain?.metric === selected check is what keeps a stale
                      domain from a previous metric from ever reaching the strip. */}
                  {series.some((r) => r.result_type === 'qualitative') && (
                    <QualitativeTimeline
                      series={series}
                      sharedAxis={chartDomain?.metric === selected ? chartDomain : null}
                    />
                  )}
                  {/* Current state, then the whole history — stacked rather than
                      side by side: the record column is half the old page width, and
                      two flag lists in ~300px each read worse than one after the other. */}
                  <FlagList flags={flags} />
                  <HistoryPanel history={history} flags={flags} />
                  <section className="rsec">
                    <h3 className="rsec__head">Readings</h3>
                    <ObservationTable
                      series={series}
                      flags={flags}
                      onEdit={handleEdit}
                      onDelete={handleDelete}
                      readOnly={selected in derivedByMetric}
                      collectionById={collectionById}
                    />
                  </section>
                  {/* Chart legend + guideline definitions, last: what the marks mean
                      and where each cutoff comes from. */}
                  <ChartLegend
                    series={series}
                    flags={flags}
                    thresholds={chartConfig?.thresholds ?? []}
                    personalBaselineMean={chartConfig?.personal_baseline_mean ?? null}
                  />
                </>
              )}
                </div>
              </div>
            </>
          )}

          {/* Add/edit modal. Add-mode shows the form + PDF import; edit-mode shows
              the form only (importing is irrelevant to editing one row). */}
          <Modal
            open={modalOpen}
            onClose={requestClose}
            title={editing ? 'Edit reading' : 'Add reading'}
          >
            {discarding && (
              <div className="modal__discard" role="alert">
                <span>Discard changes?</span>
                <div className="modal__discard-actions">
                  <button type="button" className="danger" onClick={closeModal}>
                    Discard
                  </button>
                  <button type="button" onClick={() => setDiscarding(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <ObservationForm
              key={editing?.id ?? 'new'} // remount to cleanly pre-fill on edit / reset on cancel
              // Derived metrics are computed, not enterable — keep them out of the
              // add-form datalist, and pass the map so the form also blocks a derived
              // name typed by hand (pointing at the inputs to add instead). The backend
              // 409s a derived write regardless, as the final backstop.
              metrics={metrics.filter((m) => !(m in derivedByMetric))}
              derivedMetrics={derivedByMetric}
              unitByMetric={unitByMetric}
              editing={editing}
              onSaved={handleSaved}
              onCancelEdit={requestClose}
              onDirtyChange={setFormDirty}
            />

          </Modal>

          {/* Set the selected metric's DISPLAY name. The lab-wording label is kept too;
              both labels resolve to the same metric_id, so imports still find it. */}
          <DisplayNameModal
            key={`display-${selected}`} // remount per metric so it pre-fills the current alias
            open={namingDisplay}
            metric={selected}
            isDerived={selected in derivedByMetric}
            currentAlias={aliasByMetric[selected] || ''}
            onClose={() => setNamingDisplay(false)}
            onSet={handleDisplayNameSet}
          />

          {/* Relabel the selected metric's unit across its readings (values unchanged). */}
          <UnitModal
            key={`unit-${selected}`} // remount per metric so it pre-fills the current unit
            open={editingUnit}
            metric={selected}
            currentUnit={unitByMetric[selected] || ''}
            onClose={() => setEditingUnit(false)}
            onSet={handleUnitSet}
          />

          {/* Assign the selected metric to a display-only picker group. */}
          <GroupModal
            key={`group-${selected}`} // remount per metric so it pre-fills the current group
            open={editingGroup}
            metric={selected}
            currentGroup={groupByMetric[selected] || ''}
            existingGroups={[...new Set(Object.values(groupByMetric))].sort((a, b) => a.localeCompare(b))}
            onClose={() => setEditingGroup(false)}
            onSet={handleGroupSet}
          />
        </>
      )}
    </>
  )
}
