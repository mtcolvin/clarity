import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTimeline, deleteEvent } from '../api'
import EventForm from '../components/timeline/EventForm'
import Modal from '../components/Modal'
import { TimelineViewIcon, CalendarViewIcon, ChevronIcon } from '../components/icons'
import Loading from '../components/shell/Loading'

// Per-kind label + color for the type tag, the filter chips, the entry dot, and the
// calendar dots. To add a future source (Documents/Imaging/Immunizations) the only
// frontend change is one entry here — filter chips and calendar dots derive from the
// kinds actually present, so a new source appears automatically.
// One colour per kind, chosen so the FILTER CHIPS are told apart at a glance. The previous
// set had three near-collisions — medication blue vs lab blue, and collection violet next to
// both — which made the chips read as one blur. These six sit far apart in hue AND differ in
// darkness, so they survive being shrunk to a 0.5rem dot.
const KIND_META = {
  condition: { label: 'Condition', color: '#2f9e44' },    // green
  medication: { label: 'Medication', color: '#1c7ed6' },  // blue
  event: { label: 'Event', color: '#f76707' },            // orange
  immunization: { label: 'Immunization', color: '#5f3dc4' }, // indigo
  collection: { label: 'Collection', color: '#ae3ec9' },  // magenta-purple
  imaging: { label: 'Imaging', color: '#0b7285' },        // deep teal
  lab: { label: 'Lab', color: '#c2255c' },                // crimson
}
const KIND_ORDER = ['condition', 'medication', 'event', 'immunization',
                    'collection', 'imaging', 'lab']

const EVENT_TYPE_LABELS = {
  visit: 'Visit', symptom: 'Symptom', life_event: 'Life event',
  procedure: 'Procedure', other: 'Other',
}
const SUBTYPE_LABELS = { onset: 'Onset', resolved: 'Resolved', started: 'Started', ended: 'Ended' }
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// A specific entry date renders as the stored ISO string (YYYY-MM-DD) per the Date
// Format charter — no reformatting. Month GROUP headers are period labels (a span, not
// a specific date), so they're the charter's natural-language exception ("March 2026").
function formatMonth(iso) {
  const [y, m] = iso.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { year: 'numeric', month: 'long' })
}

// One reading row inside a lab panel. Extracted so the NOTABLE list and the collapsed
// full list render identically — they're the same row in two places, and a copy-paste
// pair would eventually drift.
function ReadingRow({ reading, onOpen }) {
  return (
    <li>
      <button type="button" className="tl-reading" onClick={() => onOpen(reading.metric)}>
        <span className="tl-reading__metric">{reading.metric}</span>
        <span className="tl-reading__value">{reading.display}</span>
        {reading.notable && (
          <span className="tl-reading__notable" title="Notable that day">▲</span>
        )}
      </button>
    </li>
  )
}

// A lab panel: NOTABLE readings inline, everything else behind a collapsed disclosure.
// A full panel can run to 78 results, which buried the handful that stood out.
function LabPanel({ entry, onOpen }) {
  const readings = entry.detail.readings
  const notable = readings.filter((r) => r.notable)
  const rest = readings.filter((r) => !r.notable)
  const plural = (n) => (n === 1 ? '' : 's')

  return (
    <div className="tl-labs">
      <div className="tl-labs__head">
        <span className="tl-labs__title">Lab panel</span>
        <span className="tl-labs__count">{entry.detail.count} result{plural(entry.detail.count)}</span>
        {notable.length > 0 && (
          <span className="tl-labs__notable">{notable.length} notable</span>
        )}
      </div>

      {notable.length > 0 && (
        <ul className="tl-readings tl-readings--notable">
          {notable.map((r, j) => <ReadingRow key={`n${j}`} reading={r} onOpen={onOpen} />)}
        </ul>
      )}

      {rest.length > 0 && (
        <details className="tl-entry__labs">
          <summary>
            {notable.length > 0
              ? `Show the other ${rest.length} result${plural(rest.length)}`
              : `Show all ${rest.length} result${plural(rest.length)}`}
          </summary>
          <ul className="tl-readings">
            {rest.map((r, j) => <ReadingRow key={`r${j}`} reading={r} onOpen={onOpen} />)}
          </ul>
        </details>
      )}
    </div>
  )
}

function subtypeLabel(entry) {
  if (entry.kind === 'event') return EVENT_TYPE_LABELS[entry.subtype] ?? entry.subtype
  if (entry.kind === 'collection') return null  // the title already says "24-hour urine collection"
  if (entry.kind === 'imaging') return null     // the title already leads with the modality
  return SUBTYPE_LABELS[entry.subtype] ?? entry.subtype
}

// Group an already-ordered list into contiguous month buckets. The list is date-sorted,
// so same-month entries are adjacent — a month with no entries never starts a bucket.
function groupByMonth(ordered) {
  const groups = []
  let cur = null
  for (const e of ordered) {
    const ym = e.date.slice(0, 7)
    if (!cur || cur.ym !== ym) {
      cur = { ym, label: formatMonth(e.date), entries: [] }
      groups.push(cur)
    }
    cur.entries.push(e)
  }
  return groups
}

// The calendar overview: year -> 12 month cells, each with the set of kinds present and
// a total count. Built from the already-filtered list so toggling a filter updates both
// views the same way. Years are returned newest- or oldest-first per `order`.
function buildCalendar(entries, order) {
  const years = new Map()
  for (const e of entries) {
    const y = Number(e.date.slice(0, 4))
    const m = Number(e.date.slice(5, 7)) - 1
    if (!years.has(y)) {
      years.set(y, Array.from({ length: 12 }, () => ({ kinds: new Set(), count: 0 })))
    }
    const cell = years.get(y)[m]
    cell.kinds.add(e.kind)
    cell.count += 1
  }
  const sorted = [...years.keys()].sort((a, b) => (order === 'desc' ? b - a : a - b))
  return sorted.map((y) => ({ year: y, months: years.get(y) }))
}

function CalendarView({ entries, order, onPickMonth }) {
  const years = buildCalendar(entries, order)
  if (years.length === 0) return <p className="muted">Nothing to show for the selected filters.</p>
  return (
    <div className="tl-cal">
      {years.map(({ year, months }) => (
        <section key={year} className="tl-cal__year">
          <h3 className="tl-cal__year-label">{year}</h3>
          <div className="tl-cal__grid">
            {months.map((cell, m) => {
              const ym = `${year}-${String(m + 1).padStart(2, '0')}`
              const has = cell.count > 0
              return (
                <button
                  key={m}
                  type="button"
                  className={`tl-cal__cell${has ? '' : ' tl-cal__cell--empty'}`}
                  disabled={!has}
                  onClick={() => onPickMonth(ym)}
                  title={has ? `${cell.count} entr${cell.count === 1 ? 'y' : 'ies'}` : 'Nothing this month'}
                >
                  <span className="tl-cal__month">{MONTH_ABBR[m]}</span>
                  <span className="tl-cal__dots">
                    {KIND_ORDER.filter((k) => cell.kinds.has(k)).map((k) => (
                      <span key={k} className="tl-cal__dot" style={{ background: KIND_META[k].color }} />
                    ))}
                  </span>
                </button>
              )
            })}
          </div>
        </section>
      ))}
    </div>
  )
}

export default function TimelinePage() {
  const navigate = useNavigate()
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState({ condition: true, medication: true, event: true, collection: true, lab: true })
  const [order, setOrder] = useState('desc') // 'desc' = newest first
  const [view, setView] = useState('timeline') // 'timeline' | 'calendar'
  const [collapsed, setCollapsed] = useState(() => new Set()) // ym keys collapsed
  const [adding, setAdding] = useState(false)
  const [editingEvent, setEditingEvent] = useState(null)
  const [confirmingId, setConfirmingId] = useState(null) // event id armed for delete
  const [pendingFocus, setPendingFocus] = useState(null) // ym to scroll to after a view switch
  const sectionRef = useRef(null)
  const topbarRef = useRef(null)

  function loadTimeline() {
    return getTimeline().then(setEntries).catch((e) => setError(e.message))
  }
  useEffect(() => {
    loadTimeline()
  }, [])

  // Publish the ACTUAL rendered heights of BOTH sticky bars — the global app header and
  // this page's own header — so the month/year headers (which stick at app-header-h +
  // tl-topbar-h) sit exactly against them. Hardcoded heights can't stay correct: the page
  // header grows if the filters wrap, and rem→px rounds differently per zoom/DPI — either
  // opens the seam the spine dots peeked through. Measured here + a 2px overlap in CSS
  // closes it regardless of the real heights.
  useEffect(() => {
    const bar = topbarRef.current
    const section = sectionRef.current
    if (!bar || !section) return
    const appHeader = document.querySelector('.app-header')
    const apply = () => {
      section.style.setProperty('--tl-topbar-h', `${bar.offsetHeight}px`)
      if (appHeader) section.style.setProperty('--app-header-h', `${appHeader.offsetHeight}px`)
    }
    apply()
    const ro = new ResizeObserver(apply)
    ro.observe(bar)
    if (appHeader) ro.observe(appHeader)
    return () => ro.disconnect()
  }, [entries, view, adding, editingEvent])

  // Calendar → timeline focus: switch view, ensure the month is expanded, then scroll it
  // under the sticky headers. Runs after render so the target section exists in the DOM.
  useEffect(() => {
    if (!pendingFocus || view !== 'timeline') return
    const el = document.getElementById(`tl-month-${pendingFocus}`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setPendingFocus(null)
  }, [pendingFocus, view, entries])

  function afterEventSaved() {
    setAdding(false)
    setEditingEvent(null)
    loadTimeline()
  }

  async function handleDeleteEvent(id) {
    setConfirmingId(null)
    try {
      await deleteEvent(id)
      await loadTimeline()
    } catch (e) {
      setError(e.message)
    }
  }

  function toggleMonth(ym) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      next.has(ym) ? next.delete(ym) : next.add(ym)
      return next
    })
  }

  function focusMonth(ym) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      next.delete(ym) // a focused month is always shown expanded
      return next
    })
    setView('timeline')
    setPendingFocus(ym)
  }

  if (error && !entries) return <p className="error">Couldn’t reach the API: {error}</p>
  if (!entries) return <Loading what="timeline" />

  const kindsPresent = KIND_ORDER.filter((k) => entries.some((e) => e.kind === k))
  const visible = entries.filter((e) => filters[e.kind] !== false)
  const ordered = order === 'desc' ? visible : [...visible].reverse()
  const groups = groupByMonth(ordered)

  return (
    <section className="timeline" ref={sectionRef}>
      {/* Sticky header: title + view toggle + add on the first row, filters + sort on
          the second. The whole block stays put while you scroll, so BOTH the controls
          and the month headers below it stack against the app header. Its measured height
          is published to --tl-topbar-h (see the ResizeObserver effect above). */}
      <div className="timeline__topbar" ref={topbarRef}>
        <div className="timeline__topbar-row">
          <h2 className="timeline__title">Timeline</h2>
          <div className="timeline__topbar-actions">
            <div
              className={`timeline__viewtoggle${view === 'calendar' ? ' timeline__viewtoggle--calendar' : ''}`}
              role="group"
              aria-label="View"
            >
              <button
                type="button"
                className={`timeline__viewbtn${view === 'timeline' ? ' timeline__viewbtn--on' : ''}`}
                onClick={() => setView('timeline')}
                aria-pressed={view === 'timeline'}
                aria-label="Timeline view"
                title="Timeline view"
              >
                <TimelineViewIcon />
              </button>
              <button
                type="button"
                className={`timeline__viewbtn${view === 'calendar' ? ' timeline__viewbtn--on' : ''}`}
                onClick={() => setView('calendar')}
                aria-pressed={view === 'calendar'}
                aria-label="Calendar view"
                title="Calendar view"
              >
                <CalendarViewIcon />
              </button>
            </div>
            {!adding && !editingEvent && (
              <button type="button" className="btn-primary" onClick={() => setAdding(true)}>
                + Add event
              </button>
            )}
          </div>
        </div>

        <div className="timeline__controls">
          <div className="timeline__filters">
            {kindsPresent.map((k) => {
              const on = filters[k] !== false
              return (
                // The checkbox stays a real focusable input (visually hidden, not removed)
                // so keyboard and screen-reader use are unchanged; the pill is the paint.
                <label
                  key={k}
                  className={`timeline__filter${on ? ' timeline__filter--on' : ''}`}
                  style={{ '--kind': KIND_META[k].color }}
                >
                  <input
                    type="checkbox"
                    className="timeline__filter-input"
                    checked={on}
                    onChange={(e) => setFilters((f) => ({ ...f, [k]: e.target.checked }))}
                  />
                  <span className="timeline__filter-dot" />
                  {KIND_META[k].label}
                </label>
              )
            })}
          </div>
          {view === 'timeline' && (
            <button
              type="button"
              className="timeline__sort"
              onClick={() => setOrder((o) => (o === 'desc' ? 'asc' : 'desc'))}
            >
              {order === 'desc' ? 'Newest first' : 'Oldest first'}
              {/* Chevron points down for newest-first (descending), up for oldest-first. */}
              <span
                className={`timeline__sort-chevron${order === 'asc' ? ' timeline__sort-chevron--up' : ''}`}
                aria-hidden="true"
              >
                <ChevronIcon size={14} />
              </span>
            </button>
          )}
        </div>
      </div>

      {/* An overlay, not an inline form: inline it sat between the sticky header and the
          entries, pushing the whole timeline down while you filled it in — on a page whose
          headers are already position-sticky, that reflow is the thing to avoid. */}
      <Modal
        open={adding || editingEvent != null}
        onClose={() => { setAdding(false); setEditingEvent(null) }}
        title={editingEvent ? 'Edit event' : 'Add event'}
      >
        <EventForm
          key={editingEvent?.id ?? 'new'}
          editing={editingEvent}
          onSaved={afterEventSaved}
          onCancel={() => { setAdding(false); setEditingEvent(null) }}
        />
      </Modal>

      {view === 'calendar' ? (
        <CalendarView entries={visible} order={order} onPickMonth={focusMonth} />
      ) : groups.length === 0 ? (
        <p className="muted">Nothing to show for the selected filters.</p>
      ) : (
        groups.map((g) => {
          const isCollapsed = collapsed.has(g.ym)
          return (
            <section key={g.ym} id={`tl-month-${g.ym}`} className="timeline__group">
              <button
                type="button"
                className={`timeline__month${isCollapsed ? ' timeline__month--collapsed' : ''}`}
                aria-expanded={!isCollapsed}
                onClick={() => toggleMonth(g.ym)}
              >
                <span className="timeline__month-label">{g.label}</span>
                <span className="timeline__month-count">
                  {g.entries.length} entr{g.entries.length === 1 ? 'y' : 'ies'}
                </span>
                <span className="timeline__month-chevron" aria-hidden="true">
                  <ChevronIcon size={16} />
                </span>
              </button>

              {!isCollapsed && (
                <ul className="timeline__list">
                  {g.entries.map((e, i) => (
                    <li
                      key={`${e.kind}-${e.date}-${e.ref_id ?? i}`}
                      className={`tl-entry tl-kind--${e.kind}`}
                      style={{ '--kind': KIND_META[e.kind].color }}
                    >
                      <div className="tl-entry__head">
                        <span className="timeline__tag">{KIND_META[e.kind].label}</span>
                        <span className="tl-entry__date">{e.date}</span>
                        {e.subtype && <span className="tl-entry__subtype">{subtypeLabel(e)}</span>}
                      </div>

                      {/* Condition / medication: title links to the C/M section. */}
                      {(e.kind === 'condition' || e.kind === 'medication') && (
                        <button type="button" className="tl-entry__link" onClick={() => navigate(e.link)}>
                          {e.title}
                        </button>
                      )}

                      {/* Event: title + notes + edit / two-step delete. */}
                      {e.kind === 'event' && (
                        <div className="tl-entry__event">
                          <span className="tl-entry__title">{e.title}</span>
                          {e.detail?.notes && <p className="tl-entry__notes muted">{e.detail.notes}</p>}
                          <div className="readings__actions">
                            {confirmingId === e.ref_id ? (
                              <>
                                <button type="button" className="danger"
                                        onClick={() => handleDeleteEvent(e.ref_id)}>
                                  Confirm delete
                                </button>
                                <button type="button" onClick={() => setConfirmingId(null)}>Cancel</button>
                              </>
                            ) : (
                              <>
                                <button type="button" onClick={() => {
                                  setAdding(false)
                                  setEditingEvent({
                                    id: e.ref_id, event_date: e.date, event_type: e.subtype,
                                    title: e.title, notes: e.detail?.notes ?? '',
                                  })
                                }}>Edit</button>
                                <button type="button" onClick={() => setConfirmingId(e.ref_id)}>Delete</button>
                              </>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Immunization: the record lives on the Profile tab (which is also
                          where an UNDATED one is readable — those never reach the Timeline,
                          since a record with no date has no place on a line). The dose/site
                          line renders only when there is something in it, so a bare
                          "vaccine, date" record doesn't get an empty second row. */}
                      {e.kind === 'immunization' && (
                        <div className="tl-entry__event">
                          <button type="button" className="tl-entry__link" onClick={() => navigate(e.link)}>
                            {e.title}
                          </button>
                          {(e.detail.dose_label || e.detail.site) && (
                            <p className="tl-entry__notes muted">
                              {[e.detail.dose_label, e.detail.site].filter(Boolean).join(' · ')}
                            </p>
                          )}
                          {e.detail?.notes && <p className="tl-entry__notes muted">{e.detail.notes}</p>}
                        </div>
                      )}

                      {/* Collection: its own context; analyte VALUES are in the same-date Lab panel. */}
                      {e.kind === 'collection' && (
                        <div className="tl-entry__event">
                          <button type="button" className="tl-entry__link" onClick={() => navigate(e.link)}>
                            {e.title}
                          </button>
                          <p className="tl-entry__notes muted">
                            {e.detail.n_readings} analyte{e.detail.n_readings === 1 ? '' : 's'} in this collection
                            {' · '}see the day’s Lab panel for the values
                          </p>
                          {e.detail?.notes && <p className="tl-entry__notes muted">{e.detail.notes}</p>}
                        </div>
                      )}

                      {/* Imaging: a locally-stored DICOM study; links to the viewer with
                          the study preselected. The radiologist's REPORT belongs to this
                          study — it's the written half of the same exam, not a separate
                          event that happened to share a date — so it renders inside this
                          entry rather than as a row of its own. */}
                      {e.kind === 'imaging' && (
                        <div className="tl-entry__event">
                          <button type="button" className="tl-entry__link" onClick={() => navigate(e.link)}>
                            {e.title}
                          </button>
                          <p className="tl-entry__notes muted">
                            {e.detail.n_series} series · {e.detail.n_images} images · stored on this machine
                          </p>
                          {(e.detail.reports || []).map((r) => (
                            <button key={r.id} type="button" className="tl-entry__sublink"
                                    onClick={() => navigate(`/documents?report=${r.id}`)}>
                              Read the radiology report
                            </button>
                          ))}
                        </div>
                      )}

                      {/* Lab: notable readings inline, the rest collapsed (see LabPanel). */}
                      {e.kind === 'lab' && (
                        <LabPanel
                          entry={e}
                          onOpen={(metric) =>
                            navigate(`/metrics?metric=${encodeURIComponent(metric)}`)}
                        />
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )
        })
      )}
    </section>
  )
}
