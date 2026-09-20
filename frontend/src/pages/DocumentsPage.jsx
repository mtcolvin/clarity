import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  getReports, getReport, reportPdfUrl,
  getDocuments, getDocument, documentPdfUrl, searchDocuments,
} from '../api'
import { InfoCircleIcon } from '../components/icons'
import SearchField from '../components/shell/SearchField'
import Loading from '../components/shell/Loading'

// Every clinical document held on this machine, from TWO local sources merged into one
// list: the radiologist's reports that came on the imaging discs (reports.py), and the
// imported hospital record split into its constituent documents (docstore.py) — discharge
// summary, ER record, operative and pathology reports, nursing chart, lab printouts.
//
// Read-only and 100% local: the backend reads both folders and serves text/PDF over
// loopback. These are prose that opens with the patient's own identifying details, so
// nothing here is ever uploaded — see reports.py and docstore.py for the posture.
//
// ?report=<id> / ?document=<id> deep-link one item (the imaging viewer links here with
// ?report=), mirroring the ?study= / ?metric= / ?tab= idiom used elsewhere.

// Mirrors docstore.MIN_QUERY: below this the backend returns nothing rather than matching
// everything, so the client shouldn't bother asking.
const MIN_QUERY = 2

// One shape for both sources, so the list and the reader don't each have to branch. `kind` is what tells the fetchers which endpoint to use.
const fromReport = (r) => ({
  key: `report:${r.id}`, kind: 'report', id: r.id,
  date: r.study_date, title: r.study_description || 'Radiology report',
  type: 'Radiology report',
  detail: r.n_discs > 1 ? `${r.n_discs} discs` : null,
  studyId: r.study_id,
})

const fromDocument = (d) => ({
  key: `document:${d.id}`, kind: 'document', id: d.id,
  date: d.date, title: d.title,
  type: d.title,
  // The document's ORIGINAL-language title is kept beside the label: it is what the
  // page actually says, and it is what to quote back to the clinic that issued it.
  detail: [d.title_original, d.n_pages ? `${d.n_pages} pp` : null].filter(Boolean).join(' · '),
  studyId: null,
})

export default function DocumentsPage() {
  const [reportIndex, setReportIndex] = useState(null)
  const [docIndex, setDocIndex] = useState(null)
  const [error, setError] = useState(null)
  const [picked, setPicked] = useState(null)     // set only once the user clicks
  const [typeFilter, setTypeFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState(null)         // null = not searching
  const [searchOpen, setSearchOpen] = useState(false)
  const [loaded, setLoaded] = useState(null)     // the loaded detail for openKey
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()

  useEffect(() => {
    // Independent: either source failing should not blank the other, so each settles on
    // its own and an empty index is a valid answer rather than an error for the page.
    getReports().then(setReportIndex).catch(() => setReportIndex({ available: false, reports: [] }))
    getDocuments().then(setDocIndex).catch(() => setDocIndex({ available: false, documents: [] }))
  }, [])

  const ready = reportIndex !== null && docIndex !== null

  const items = useMemo(() => {
    const merged = [
      ...(reportIndex?.reports ?? []).map(fromReport),
      ...(docIndex?.documents ?? []).map(fromDocument),
    ]
    // Newest first; undated sink to the bottom rather than sorting as the empty string.
    merged.sort((a, b) => (b.date || '').localeCompare(a.date || ''))
    return merged
  }, [reportIndex, docIndex])

  const types = useMemo(
    () => [...new Set(items.map((i) => i.type))].sort(), [items])

  // Search runs server-side over the OCR text — the one job that text still has now that
  // the reader shows the PDF. Debounced because every keystroke would otherwise re-read
  // the whole corpus; 200 ms is below the threshold where typing feels laggy.
  useEffect(() => {
    const q = query.trim()
    if (q.length < MIN_QUERY) return undefined     // nothing to fetch, and nothing to reset
    let cancelled = false
    const t = setTimeout(() => {
      searchDocuments(q)
        .then((r) => { if (!cancelled) setHits({ query: q, results: r.results }) })
        .catch(() => { if (!cancelled) setHits({ query: q, results: [] }) })
    }, 200)
    return () => { cancelled = true; clearTimeout(t) }
  }, [query])

  // Results are stored WITH the query they answer, so a stale result set can never be
  // displayed under a newer query. It also means the effect never has to reset state,
  // which is what a short query used to do synchronously.
  const trimmed = query.trim()
  const searching = trimmed.length >= MIN_QUERY
  const results = hits?.query === trimmed ? hits.results : null
  // While searching, the list IS the result set (ordered by match count, so the filter
  // and the type dropdown stand down — relevance is the ordering the user asked for).
  const byKey = useMemo(() => new Map(items.map((i) => [i.key, i])), [items])
  const shown = searching
    ? (results ?? []).map((h) => ({ ...(byKey.get(`${h.kind}:${h.id}`) ?? {}),
                         key: `${h.kind}:${h.id}`, kind: h.kind, id: h.id,
                         date: h.date, title: h.title,
                         nMatches: h.n_matches, snippet: h.snippets[0],
                         approximate: h.approximate }))
        .filter((h) => h.key)
    : (typeFilter === 'all' ? items : items.filter((i) => i.type === typeFilter))

  // Which item is open is DERIVED, not stored-then-corrected-in-an-effect: the user's
  // click wins, else a deep link, else the first of what's currently shown. Falling back
  // within `shown` matters — filtering to a type whose items exclude the open one would
  // otherwise leave the reader displaying something not in the list.
  const deepLinked = searchParams.get('report')
    ? `report:${searchParams.get('report')}`
    : searchParams.get('document') ? `document:${searchParams.get('document')}` : null
  const openKey = (picked && shown.some((i) => i.key === picked) ? picked : null)
    ?? (deepLinked && shown.some((i) => i.key === deepLinked) ? deepLinked : null)
    ?? shown[0]?.key
    ?? null
  const open = items.find((i) => i.key === openKey) ?? null

  useEffect(() => {
    if (!open) return undefined
    let cancelled = false
    const fetcher = open.kind === 'report' ? getReport : getDocument
    fetcher(open.id)
      .then((r) => {
        if (cancelled) return
        setLoaded({ ...r, key: open.key })
        setSearchParams(open.kind === 'report' ? { report: open.id } : { document: open.id },
                        { replace: true })
      })
      .catch((e) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [open, setSearchParams])

  // Derived rather than a flag set at the top of the effect: "loading" is exactly "the
  // item I'm holding isn't the one that's selected", which the data already says.
  const loadingText = Boolean(openKey) && loaded?.key !== openKey

  if (error) return <p className="error">Couldn’t reach the API: {error}</p>
  if (!ready) return <Loading what="documents" />

  if (items.length === 0) {
    return (
      <section className="docs">
        <h2>Documents</h2>
        <p className="muted">
          {docIndex?.reason || reportIndex?.reason || 'No documents found.'}
        </p>
        <p className="muted small">
          Radiology reports are copied out of an imaging disc’s <code>other_content</code>
          {' '}folder when you import it; hospital records are split into their constituent
          documents by the offline ingest. Everything stays on this machine.
        </p>
      </section>
    )
  }

  const pdfUrl = open?.kind === 'report' ? reportPdfUrl : documentPdfUrl

  return (
    <section className="docs">
      <div className="docs__head">
        <h2 className="docs__title">Documents</h2>
        <span className="docs__info" tabIndex={0} role="note" aria-label="Privacy note">
          <InfoCircleIcon size={16} />
          <span className="docs__info-bubble">
            Local only — read from this machine and never uploaded. Each document is
            shown as the original scan; nothing here is generated, translated, summarised
            or interpreted by this app.
          </span>
        </span>
      </div>

      <div className="docs__filter">
        {/* The type filter is meaningless while searching: results are ordered by match
            count, which IS the ordering the search asked for. */}
        {!searchOpen && (
          <label>
            Type{' '}
            <select value={typeFilter}
                    onChange={(e) => { setTypeFilter(e.target.value); setPicked(null) }}>
              <option value="all">All ({items.length})</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {t} ({items.filter((i) => i.type === t).length})
                </option>
              ))}
            </select>
          </label>
        )}

        {/* Search sits on the RIGHT and starts collapsed to its magnifier: it is an
            occasional action, and 51 documents are browsable without it. Expanding hides
            the type filter rather than crowding beside it — while searching, relevance
            order replaces type order, so both controls would be fighting over the list.
            The control itself is the shared SearchField — this page used to carry its own
            copy of it, which is how its Escape came to clear the picked document while
            Immunizations' did not. Closing still clears the query (a live filter behind a
            collapsed icon hides WHY the list is short); that now lives in the component. */}
        <div className="docs__search">
          <SearchField
            value={query}
            onChange={(v) => { setQuery(v); setPicked(null) }}
            onOpenChange={setSearchOpen}
            label="Search all documents"
            placeholder="Search all documents…"
            count={!searching ? null
              : results === null
                ? 'Searching…'
                : shown.length === 0
                  ? 'No matches'
                  : `${shown.length} match${shown.length === 1 ? '' : 'es'}`}
          />
        </div>
      </div>

      <div className="docs__layout">
        <ul className="docs__list">
          {shown.map((it) => (
            <li key={it.key}>
              <button
                type="button"
                className={`docs__item${it.key === openKey ? ' docs__item--on' : ''}`}
                onClick={() => setPicked(it.key)}
              >
                <span className="docs__item-date">{it.date || 'Undated'}</span>
                <span className="docs__item-desc">{it.title}</span>
                <span className="docs__item-kind muted small">
                  {searching
                    ? `${it.nMatches} match${it.nMatches === 1 ? '' : 'es'}${
                        it.approximate ? ' (approximate)' : ''}`
                    : (it.detail || it.type)}
                </span>
                {/* The snippet comes from OCR text, so it is marked as such and styled as
                    secondary: it is a locator telling you WHERE to look in the scan, not
                    the document's content. Clicking still opens the PDF. */}
                {searching && it.snippet && (
                  <span className="docs__item-snippet">{it.snippet}</span>
                )}
              </button>
            </li>
          ))}
        </ul>

        <article className="docs__reader">
          {loadingText && <Loading what="this document" />}
          {!loadingText && loaded && open && (
            <>
              <header className="docs__reader-head">
                <div>
                  <h3 className="docs__reader-title">{open.title}</h3>
                  <p className="muted small docs__reader-meta">
                    {/* Only the DATE is a figure; the rest of the line is prose, so the
                        mono face is scoped to it rather than to the whole sentence. */}
                    <span className="docs__reader-date">{open.date || 'Undated'}</span>
                    {open.detail ? ` · ${open.detail}` : ''}
                    {loaded.source_pages
                      ? ` · pages ${loaded.source_pages[0]}–${loaded.source_pages[1]} of the source record`
                      : ''}
                  </p>
                </div>
                <div className="docs__actions">
                  {open.studyId && (
                    <button type="button" className="docs__action"
                            onClick={() => navigate(`/imaging?study=${open.studyId}`)}>
                      View images
                    </button>
                  )}
                </div>
              </header>

              {/* THE SCAN IS THE DOCUMENT — the only thing rendered. The OCR transcription
                  is deliberately never shown: it is a lossy derivative that reads as
                  authoritative prose, and on this record it turns "L3, L5" into "13, 15".
                  Text is retained purely to power SEARCH. There is no "Original PDF" link
                  either; the PDF is right here, so a button opening the same bytes in a tab
                  was just a second route to what you are already looking at. */}
              <div className="docs__body">
                {(loaded.formats || []).includes('pdf')
                  ? <iframe className="docs__pdf" src={pdfUrl(open.id)} title={open.title} />
                  : <p className="muted">
                      No PDF for this document — nothing to display. Its text is still
                      searchable.
                    </p>}

              </div>

            </>
          )}
        </article>
      </div>
    </section>
  )
}
