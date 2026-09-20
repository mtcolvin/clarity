// Tiny fetch wrapper around the FastAPI backend. No app logic here — just
// transport, mirroring the backend's own thin-layer split.

import { routeKey } from './snapshot'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// STATIC DEMO MODE. The published demo has no backend at all: `build_static_demo.py`
// snapshots every GET response to a file whose path mirrors the route, and the build
// points API_BASE at that folder. So this is a transport switch and nothing more — no
// page, chart, or component knows the difference, which is the point: shipping a
// separate read-only fork of the UI would mean demoing something that is not the app.
//
// It is OFF unless the build sets it, so a normal local run is byte-identical to before.
export const STATIC_DEMO = import.meta.env.VITE_STATIC_DEMO === '1'

// A live route -> the snapshot file that answers it. See snapshot.js: the filename is
// computed identically here and in build_static_demo.py, so nothing depends on how a
// static host handles encoded slashes or spaces.
const snapshotUrl = (path, ext = 'json') => `${API_BASE}/${routeKey(path)}.${ext}`

export class StaticDemoError extends Error {}

async function getJSON(path) {
  const res = await fetch(STATIC_DEMO ? snapshotUrl(path) : `${API_BASE}${path}`)
  if (!res.ok) {
    // In the static demo a 404 is not a failure of the app — it means this particular
    // request was never snapshotted (an arbitrary search term, say). Say so in those
    // words, because "404" on a page that otherwise works reads as broken.
    if (STATIC_DEMO && res.status === 404) {
      throw new StaticDemoError('Not part of this demo snapshot.')
    }
    throw new Error(`${path} → ${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const getMetrics = () => getJSON('/metrics')
// Rename a metric (local relabel; carries readings + per-metric settings). Throws
// on 409 (name already exists) / 404 (unknown) / 400 (same name), detail on .message.
export const renameMetric = (metric, newName) =>
  sendJSON('PUT', `/metrics/${encodeURIComponent(metric)}/rename`, { new_name: newName })
// Set (or clear, with alias null/'') a metric's DISPLAY name (shorthand label). Pure
// presentation — for a stored metric it ADDS a label (both resolve to the same metric_id,
// the match key); for a derived metric it overrides the display label only. Throws on 409
// (a label another metric already shows/resolves by) / 404 (unknown stored metric).
export const setDisplayName = (metric, alias) =>
  sendJSON('PUT', `/metrics/${encodeURIComponent(metric)}/display-name`, { alias })
// RELABEL a metric's unit across all its numeric/censored readings — a pure label change,
// NOT a value conversion (values are stored as entered and untouched). For casing fixes
// ('mg/dl'->'mg/dL') or equivalent units ('EU/dL'->'mg/dL'). Throws on 409 (derived metric)
// / 404 (unknown or no numeric readings). Returns { metric, unit, readings_relabeled }.
export const setMetricUnit = (metric, unit) =>
  sendJSON('PUT', `/metrics/${encodeURIComponent(metric)}/unit`, { unit })
// Set (or clear) a metric's GROUP label — a display-only picker cluster (an <optgroup>).
// Pass '' or null to clear it. Throws on 409 (derived metric) / 404 (unknown metric).
// Returns { metric, group }.
export const setMetricGroup = (metric, group) =>
  sendJSON('PUT', `/metrics/${encodeURIComponent(metric)}/group`, { group })
// Resolve an incoming metric name (import/add de-dup): returns
// { query, exact: {metric, alias} | null, suggestions: [{metric, alias, score}] }.
// `exact` is what the name attaches to now; `suggestions` are fuzzy 'did you mean'
// near-matches when there's no exact hit.
export const resolveMetricName = (name) =>
  getJSON(`/metrics/resolve?name=${encodeURIComponent(name)}`)
// Resolve MANY names in one round trip (the import review's whole draft, 10–40 rows,
// rather than a request per row). Returns { results: [...] } POSITIONAL — results[i]
// is the resolution of names[i]. Same per-name logic as resolveMetricName server-side.
export const resolveMetricNames = (names) =>
  sendJSON('POST', '/metrics/resolve-batch', { names })
export const getObservations = (metric) =>
  getJSON(`/observations/${encodeURIComponent(metric)}`)
// Chart reference-line config: { thresholds: [[cutoff, source]...],
// personal_baseline_mean } — the robust center (median; legacy field name) is
// non-null only when pb mode is on.
export const getChartConfig = (metric) =>
  getJSON(`/chart-config/${encodeURIComponent(metric)}`)
export const getFlags = (metric) => getJSON(`/flags/${encodeURIComponent(metric)}`)
// Ranked, capped list of readings that stood out across this metric's history.
export const getHistory = (metric) => getJSON(`/history/${encodeURIComponent(metric)}`)
export const getSummary = (metric) => getJSON(`/summary/${encodeURIComponent(metric)}`)
// Cross-metric "since your last reading" digest: { moved, recent_days, total_metrics }.
// Only metrics that moved AND whose latest reading is within recent_days are returned.
export const getChanges = () => getJSON('/changes')

// Cross-metric overview: { current, history, total_metrics }. `current` (Section 1)
// is each metric's latest-reading flags; `history` (Section 2) is the aggregated
// historical-anomaly groups. Both ranked severity>magnitude>recency server-side.
export const getOverview = () => getJSON('/overview')

// Adjustable settings: each { key, value, default, type, label, description,
// minimum, maximum, step, unit, group }. minimum/maximum are null for the current
// display-volume settings (the seam for future bounded ones).
export const getSettings = () => getJSON('/settings')

// Read-only coverage roster: every tracked metric as { metric, has_thresholds,
// sources }, where sources are deduped bare source acronyms (only for metrics
// with guideline thresholds). Acronyms only — full per-rule detail is on the
// metric page. View-only.
export const getMetricsCoverage = () => getJSON('/metrics-coverage')

// A metric's personal-baseline state + live candidacy:
// { metric, personal_baseline_mode, note, suggestion_dismissed,
//   candidacy: { n, out_of_range, fraction, is_candidate } }.
export const getMetricSettings = (metric) =>
  getJSON(`/metric-settings/${encodeURIComponent(metric)}`)

// The one-time global personal-baseline explainer's seen-flag: { seen }.
// Absent/never-dismissed reads as seen: false.
export const getBaselineExplainer = () => getJSON('/baseline-explainer')
export const dismissBaselineExplainer = () =>
  sendJSON('POST', '/baseline-explainer/dismiss')

// The export handoff's capability gate (CLAUDE.md "The export handoff"): { enabled }.
// A real two-way toggle, not a one-way dismiss — revoking must be as easy as granting.
export const getExportEnabled = () => getJSON('/export/enabled')
export const putExportEnabled = (enabled) =>
  sendJSON('PUT', '/export/enabled', { enabled })

// Step 1: assemble the metric's bundle fresh and preview what would be sent —
// nothing sends here. Returns the gateway's faithful, complete preview:
// { task, provider, payload, excluded_fields, redactions, provider_settings,
//   confirmation_token }.
export const postExportPreview = (metric) =>
  sendJSON('POST', `/export/${encodeURIComponent(metric)}/preview`)
// Step 2: confirm a specific previewed payload. Throws (e.status === 409) if the
// data changed since the preview (the gateway's byte-compare self-refused).
export const postExportConfirm = (metric, confirmationToken) =>
  sendJSON('POST', `/export/${encodeURIComponent(metric)}/confirm`,
           { confirmation_token: confirmationToken })
// The read-only, after-the-fact record of external sends: { entries }, newest
// first, straight from the local gateway audit log. Not gated by the export
// toggle — what already left stays reviewable after the capability is off.
export const getExportAudit = () => getJSON('/export/audit')

// Saved export RESULTS (the model's responses), newest first: { results: [{ id, created_at,
// scope, metrics, provider, model, output }] }. Shown in Settings → External export beside
// the send audit. Not gated by the toggle (what came back stays reviewable).
export const getExportResults = () => getJSON('/export/results')

// Multi-metric export (a SET of metrics: a panel, a selection, or the full picture).
// Preview/confirm mirror the single-metric flow but take the metric list + a scope label.
// `opts` carries the FULL-PICTURE half: { includeContext, reports: [{ id, text }],
// texts: [{ kind, id, field, text }] } — the user's edited report prose and their edited
// row free text. Both preview and confirm send it, because the confirm route re-assembles
// the bundle from scratch: the token only matches if it is handed the identical inputs,
// which is also what binds those edits to what actually leaves.
const multiBody = (metrics, scopeLabel, opts) => ({
  metrics,
  scope_label: scopeLabel,
  include_context: !!opts.includeContext,
  reports: opts.reports ?? [],
  texts: opts.texts ?? [],
})
export const postMultiExportPreview = (metrics, scopeLabel, opts = {}) =>
  sendJSON('POST', '/export-multi/preview', multiBody(metrics, scopeLabel, opts))
export const postMultiExportConfirm = (metrics, scopeLabel, confirmationToken, opts = {}) =>
  sendJSON('POST', '/export-multi/confirm',
           { ...multiBody(metrics, scopeLabel, opts), confirmation_token: confirmationToken })
// The prose a full-picture export can carry, as editable drafts: { reports_available,
// reports: [{ id, study_date, study_description, text }], texts: [{ kind, id, field,
// label, text }] }. One route for both because they are the same risk. Reading it sends
// nothing.
export const getExportDrafts = () => getJSON('/export/drafts')
// The 'panel' of a collection metric: metrics sharing a timed collection with it (incl.
// itself). Returns { metric, panel: [...] }; panel is empty for a non-collection metric.
export const getMetricPanel = (metric) =>
  getJSON(`/metrics/${encodeURIComponent(metric)}/panel`)

// Write helper for POST/PUT/DELETE. On failure throws an Error carrying the HTTP
// status (so callers can special-case 409 duplicates) and the backend's detail
// text. Returns null for 204 (delete), otherwise the parsed JSON body.
async function sendJSON(method, path, body) {
  // No backend exists in the static demo, so a write cannot be attempted, let alone
  // succeed. Refuse here rather than let a fetch fail obscurely against a static host.
  if (STATIC_DEMO) {
    throw new StaticDemoError(
      'This is a read-only demo — changes are disabled. Run Clarity locally to edit your own record.')
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail
    try {
      detail = (await res.json()).detail
    } catch {
      /* response had no JSON body */
    }
    const err = new Error(detail ?? `${method} ${path} → ${res.status} ${res.statusText}`)
    err.status = res.status
    throw err
  }
  return res.status === 204 ? null : res.json()
}

// Persist a batch of setting edits { key: value }; returns the refreshed list.
export const saveSettings = (values) => sendJSON('PUT', '/settings', { values })

// Update a metric's personal-baseline settings (partial). Body may include any of
// { personal_baseline_mode, note, suggestion_dismissed }. Returns the refreshed
// metric-settings (with candidacy).
export const saveMetricSettings = (metric, body) =>
  sendJSON('PUT', `/metric-settings/${encodeURIComponent(metric)}`, body)

export const addObservation = (body) => sendJSON('POST', '/observations', body) // { id }
export const updateObservation = (id, body) => sendJSON('PUT', `/observations/${id}`, body)
export const deleteObservation = (id) => sendJSON('DELETE', `/observations/${id}`)

// Conditions: list / add / edit / delete. add returns { id }; edit returns the
// updated record.
export const getConditions = () => getJSON('/conditions')
export const addCondition = (body) => sendJSON('POST', '/conditions', body)
export const updateCondition = (id, body) => sendJSON('PUT', `/conditions/${id}`, body)
export const deleteCondition = (id) => sendJSON('DELETE', `/conditions/${id}`)

// Medications: list (each row carries a derived `active`) / add / edit / delete.
export const getMedications = () => getJSON('/medications')
export const addMedication = (body) => sendJSON('POST', '/medications', body)
export const updateMedication = (id, body) => sendJSON('PUT', `/medications/${id}`, body)
export const deleteMedication = (id) => sendJSON('DELETE', `/medications/${id}`)

// Events: list / add / edit / delete (point-in-time Timeline records).
export const getEvents = () => getJSON('/events')
export const addEvent = (body) => sendJSON('POST', '/events', body)
export const updateEvent = (id, body) => sendJSON('PUT', `/events/${id}`, body)
export const deleteEvent = (id) => sendJSON('DELETE', `/events/${id}`)

// The merged, newest-first Timeline across all sources (conditions, medications,
// events, labs). The client filters by kind and flips order locally.
export const getTimeline = () => getJSON('/timeline')

// Timed collections (24h urine, etc.): each { id, kind, completed_on, started_on,
// duration_hours, volume_ml, notes, n_readings }. n_readings gates delete (the backend
// refuses 409 while a collection still has readings). Create-first: make the collection,
// then add its analytes with collection_id set.
export const getCollections = () => getJSON('/collections')
export const createCollection = (body) => sendJSON('POST', '/collections', body)
export const updateCollection = (id, body) => sendJSON('PUT', `/collections/${id}`, body)
export const deleteCollection = (id) => sendJSON('DELETE', `/collections/${id}`)
// The analytes inside one collection, alphabetical by display label. Same row shape as a
// series row, so the client formats them with the reading formatter it already has.
export const getCollectionReadings = (id) => getJSON(`/collections/${id}/readings`)

// Immunizations: the vaccination record (a Profile tab). Plain CRUD — no analysis
// endpoint exists for these, because nothing here is analysed.
export const getImmunizations = () => getJSON('/immunizations')
export const addImmunization = (body) => sendJSON('POST', '/immunizations', body)
export const updateImmunization = (id, body) => sendJSON('PUT', `/immunizations/${id}`, body)
export const deleteImmunization = (id) => sendJSON('DELETE', `/immunizations/${id}`)

// Profile: singleton demographics (sex, DOB) + current weight/height, plus the
// append-only measurement history. Foundation data only — feeds no analysis.
export const getProfile = () => getJSON('/profile')
export const updateProfile = (body) => sendJSON('PUT', '/profile', body) // { sex, date_of_birth }
export const addProfileMeasurement = (body) => sendJSON('POST', '/profile/measurements', body)
export const getProfileHistory = (field) =>
  getJSON(`/profile/history/${encodeURIComponent(field)}`)
export const updateProfileMeasurement = (id, body) =>
  sendJSON('PUT', `/profile/measurements/${id}`, body)
export const deleteProfileMeasurement = (id) =>
  sendJSON('DELETE', `/profile/measurements/${id}`)

// --- Imaging (local DICOM viewer) ------------------------------------------------------
// Studies + allowlisted metadata + window presets; { available, reason, presets, studies }.
export const getImagingStudies = () => getJSON('/imaging/studies')
// The URL for one rendered slice PNG (used directly as an <img> src). Local render only.
// wc/ww optional (window center/width); omitted → the file's own default window.
// Pixel statistics for a rectangular region of one slice, in the modality's real units
// (HU for CT): { mean, sd, min, max, n_pixels, area_mm2, units }. Computed locally.
export const getImagingRoi = (seriesId, index, { x, y, w, h }) =>
  getJSON(`/imaging/series/${encodeURIComponent(seriesId)}/slice/${index}/roi`
          + `?x=${Math.round(x)}&y=${Math.round(y)}&w=${Math.round(w)}&h=${Math.round(h)}`)
// --- Radiology reports (local documents) -----------------------------------------------
// The written report that came on an imaging disc. Local only — never exported.
// { available, reason, reports: [{ id, study_id, study_date, study_description, formats }] }
export const getReports = () => getJSON('/reports')
// One report with its extracted text: { ..., text, source }.
export const getReport = (id) => getJSON(`/reports/${encodeURIComponent(id)}`)
// The URL of the original PDF (opened in a new tab; served with no-store).
export const reportPdfUrl = (id) => {
  const route = `/reports/${encodeURIComponent(id)}/pdf`
  return STATIC_DEMO ? snapshotUrl(route, 'pdf') : `${API_BASE}${route}`
}
// Imported clinical documents (docstore.py) — the split-up hospital record: discharge
// summary, ER record, operative/pathology reports, lab printouts. Same local-only posture
// as reports; separate id namespace.
export const getDocuments = () => getJSON('/documents')
// Full-text search across BOTH sources (split hospital record + radiology reports):
// { query, results: [{ kind, id, date, title, n_matches, snippets }] }. Local only.
export const searchDocuments = (q) =>
  getJSON(`/documents/search?q=${encodeURIComponent(q)}`)
export const getDocument = (id) => getJSON(`/documents/${encodeURIComponent(id)}`)
export const documentPdfUrl = (id) => {
  const route = `/documents/${encodeURIComponent(id)}/pdf`
  return STATIC_DEMO ? snapshotUrl(route, 'pdf') : `${API_BASE}${route}`
}
// One slice's pixel VALUES + everything needed to window them in the browser. See
// dicom/frame.js; the PNG route below stays for colour slices and as the fallback.
// Is this backend open on a seeded demo store? Answered from a marker inside the DATABASE,
// so it can't claim "demo" over the real record — see DemoBanner.
export const getDemo = () => getJSON('/demo')
export const imagingFrameUrl = (seriesId, index) => {
  const route = `/imaging/series/${encodeURIComponent(seriesId)}/frame/${index}`
  return STATIC_DEMO ? snapshotUrl(route, 'bin') : `${API_BASE}${route}`
}
export const imagingSliceUrl = (seriesId, index, { wc, ww } = {}) => {
  const qs = new URLSearchParams()
  if (wc != null) qs.set('wc', wc)
  if (ww != null) qs.set('ww', ww)
  const q = qs.toString()
  // The snapshot holds one PNG per slice at the file's own default window; a windowed
  // variant would be a different file per (wc, ww) pair, which is unbounded.
  if (STATIC_DEMO) {
    return snapshotUrl(`/imaging/series/${encodeURIComponent(seriesId)}/slice/${index}`, 'png')
  }
  return `${API_BASE}/imaging/series/${encodeURIComponent(seriesId)}/slice/${index}${q ? `?${q}` : ''}`
}
