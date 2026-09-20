import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  getExportEnabled, getSettings, postExportPreview, postExportConfirm,
  postMultiExportPreview, postMultiExportConfirm, getExportDrafts,
} from '../../api'
import { LightbulbIcon } from '../icons'
import BundleFacts from './BundleFacts'
import ContextFacts from './ContextFacts'
import Markdown from '../../markdown'
import Loading from '../shell/Loading'

// Describes a data change between two preview bundles' reading counts, for the
// 409 (stale-token) path — computed CLIENT-SIDE from two preview fetches the
// browser already holds, not server-side. The backend stays stateless/no-cache
// by design (ROADMAP.md "PLAN OF RECORD" — no server-side payload cache), so a
// real diff would mean either caching the old payload server-side or trusting
// a client-submitted one; neither is "a couple of lines." A reading-count
// comparison IS cheap (both bundles are already in hand) and covers the common
// case (a new lab result landing) with a specific count; anything else
// (an edited reading, a flag/threshold shift) falls back to a generic, still
// honest message rather than attempting a full field-level diff.
function totalReadings(payload) {
  // Single bundle carries n_readings at top level; a multi bundle sums its per-metric ones.
  if (payload?.n_readings != null) return payload.n_readings
  return (payload?.metrics ?? []).reduce((s, b) => s + (b.n_readings ?? 0), 0)
}

function describeChange(oldBundle, newBundle) {
  const before = totalReadings(oldBundle)
  const after = totalReadings(newBundle)
  if (after > before) {
    const added = after - before
    return `${added} new reading${added > 1 ? 's' : ''} landed since you previewed this.`
  }
  if (after < before) {
    const removed = before - after
    return `${removed} reading${removed > 1 ? 's' : ''} were removed since you previewed this.`
  }
  return 'The underlying data changed since you previewed this.'
}

// The export handoff (CLAUDE.md "The export handoff"): send this metric's
// deterministically-assembled picture to an external model, under the gated,
// per-send-confirmed flow the charter requires. Takes over the interpretation
// slot on the metric view — the local interpretation tier (an on-demand Ollama
// pass) was found lossy as an inline surface and its assembler repurposed as this
// feature's payload (ROADMAP #16). That tier has since been REMOVED as dead code
// (its UI trigger was gone and its engine gate made it unreachable); only the
// assembler (explain.assemble_explain_context) lives on, here.
// Single-metric when `metric` is given; MULTI-metric when `metrics` (an array) is given —
// a panel, a selection, or the full picture, with a `scopeLabel`. The gate / scroll-gated
// preview / stateless confirm / result machinery is identical; only the API calls and the
// facts render (one bundle vs a group per metric) branch, so single-metric is unchanged.
// `includeContext` turns a multi-metric export into a FULL-PICTURE one: the payload gains
// the profile / conditions / medications / events / imaging / report half. Off elsewhere on
// purpose — a lab panel doesn't need the medication list, and the charter's data-
// minimization rule says send what the task needs and nothing more.
export default function ExportPanel({ metric, metrics = null, scopeLabel = '',
                                      triggerLabel = 'Export to an external model',
                                      includeContext = false,
                                      autoStart = false, onClose = null }) {
  const isMulti = Array.isArray(metrics)
  const withContext = isMulti && includeContext
  const [enabled, setEnabled] = useState(null) // null = still checking the gate
  const [providerInfo, setProviderInfo] = useState(null) // { value, label, description }
  // 'idle' | 'loading-preview' | 'preview' | 'sending' | 'result' | 'error'
  const [panelState, setPanelState] = useState('idle')
  const [preview, setPreview] = useState(null)
  const [staleNotice, setStaleNotice] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [scrolledThrough, setScrolledThrough] = useState(false)
  const sentinelRef = useRef(null)
  // Report drafts: [{ id, study_date, study_description, text }]. `text` is the user's
  // working copy — the extracted report to start, then whatever they edit it down to.
  // A report is prose with no fields, so neither the gateway's allowlist nor its regex
  // scrub can promise it holds no clinician name; this editor is the control that can
  // (CLAUDE.md "The export handoff"). Sent on BOTH preview and confirm so the token the
  // gateway computes binds the EDITED text, not the file on disk.
  const [reportDrafts, setReportDrafts] = useState([])
  // The same thing for the DB rows' own free text: [{ kind, id, field, label, text }].
  // A note reading "benign, per Dr. Rossi" is the same class of problem as a report
  // naming its radiologist — shorter, but no more automatically checkable — so it is
  // redactable in the same place at the same moment.
  const [textDrafts, setTextDrafts] = useState([])
  // True when a draft has been edited since the preview below it was built — so the
  // preview on screen no longer describes what would be sent. Confirm is blocked until
  // the preview is rebuilt; consent has to attach to a current payload, not a stale one.
  const [draftsDirty, setDraftsDirty] = useState(false)

  // Only non-empty REPORT drafts travel: emptying a box IS the decision to send nothing
  // for that report, and the server drops blanks the same way. Row text is sent even when
  // blank — there an empty string is a redaction of a field that otherwise HAS content,
  // so it must reach the server to override the stored value.
  const optsFor = (reports, texts) => ({
    includeContext: withContext,
    reports: (reports ?? []).filter((d) => d.text.trim())
                            .map((d) => ({ id: d.id, text: d.text })),
    texts: (texts ?? []).map((d) => ({ kind: d.kind, id: d.id, field: d.field, text: d.text })),
  })

  useEffect(() => {
    let cancelled = false
    getExportEnabled()
      .then((d) => !cancelled && setEnabled(d.enabled))
      .catch(() => !cancelled && setEnabled(false)) // fail closed — never assume enabled
    return () => {
      cancelled = true
    }
  }, [])

  // No metric-change reset effect needed: MetricsPage mounts this component
  // with key={`export-${selected}`}, so a metric switch is a fresh mount —
  // state resets naturally, never carrying a stale preview across metrics.

  // Scroll-gate: unlocks once the reader has reached the sentinel placed right
  // before the Confirm/Cancel row — either by scrolling to it, or because it
  // was already on-screen (a short payload needs no scroll). Deliberately a
  // manual getBoundingClientRect() check on scroll/resize, NOT
  // IntersectionObserver: verified live that IO's callback delivery — even
  // its spec-required INITIAL callback on observe() — rides on the browser's
  // rendering pipeline, which a backgrounded/non-visible document (document.
  // hidden === true — reproducible via automated browser control, not just a
  // hypothetical) may never schedule a step for on its own. A bare,
  // React-independent observer sat for 1000ms+ without firing while the
  // sentinel was genuinely on-screen and stationary; the moment a REAL scroll
  // forced a repaint, it fired instantly — confirming the pipeline dependency,
  // not a bug in the observer setup itself. A manual check tied to scroll/
  // resize events (page-level here, per this app's layout — no inner
  // scrolling container) plus one synchronous check on render doesn't depend
  // on that pipeline at all.
  useEffect(() => {
    if (panelState !== 'preview') return
    const checkReached = () => {
      const el = sentinelRef.current
      if (!el) return
      const viewportBottom = window.innerHeight || document.documentElement.clientHeight
      if (el.getBoundingClientRect().top <= viewportBottom) setScrolledThrough(true)
    }
    checkReached() // synchronous — covers "already visible, no scroll needed" immediately
    window.addEventListener('scroll', checkReached, { passive: true })
    window.addEventListener('resize', checkReached)
    return () => {
      window.removeEventListener('scroll', checkReached)
      window.removeEventListener('resize', checkReached)
    }
  }, [panelState, preview])

  async function loadDestination() {
    if (providerInfo) return providerInfo
    const rows = await getSettings()
    const def = rows.find((r) => r.key === 'export_provider')
    const opt = def?.options?.find((o) => o.value === def.value)
    const info = opt ?? { value: def?.value, label: def?.value ?? 'the provider', description: '' }
    setProviderInfo(info)
    return info
  }

  // Fetched at most once per mount: the drafts are the user's working copy from then on,
  // so re-fetching would silently discard their redactions.
  const draftsFetched = useRef(false)

  async function loadDrafts() {
    if (!withContext || draftsFetched.current) return { reports: reportDrafts, texts: textDrafts }
    draftsFetched.current = true
    try {
      const d = await getExportDrafts()
      const reports = (d.reports ?? []).map((r) => ({ ...r, text: r.text ?? '' }))
      const texts = (d.texts ?? []).map((t) => ({ ...t, text: t.text ?? '' }))
      setReportDrafts(reports)
      setTextDrafts(texts)
      return { reports, texts }
    } catch {
      // The drafts are one part of the picture, not a precondition for it — a failure
      // here means the export goes with the stored text, not that the export fails.
      return { reports: [], texts: [] }
    }
  }

  // `draftsArg` is passed explicitly on the first run because the setState calls above
  // haven't landed yet at that point; later calls read current state. The shape check is
  // deliberate rather than a null check: every caller here is a click handler, and wiring
  // one up as onClick={startPreview} would pass the event object instead — which is
  // truthy, so `??` would sail past it and fail later. (Exactly how this shipped broken.)
  async function startPreview(draftsArg) {
    const passed = draftsArg && Array.isArray(draftsArg.reports) ? draftsArg : undefined
    setPanelState('loading-preview')
    setError(null)
    setStaleNotice(null)
    setScrolledThrough(false)
    try {
      const d = passed
        ?? (draftsFetched.current ? { reports: reportDrafts, texts: textDrafts } : await loadDrafts())
      const previewReq = isMulti
        ? postMultiExportPreview(metrics, scopeLabel, optsFor(d.reports, d.texts))
        : postExportPreview(metric)
      const [p] = await Promise.all([previewReq, loadDestination()])
      setPreview(p)
      setDraftsDirty(false)
      setPanelState('preview')
    } catch (e) {
      setError(e.message || 'Could not build the export preview.')
      setPanelState('error')
    }
  }

  const currentDrafts = () => ({ reports: reportDrafts, texts: textDrafts })

  function editReport(id, text) {
    setReportDrafts((ds) => ds.map((d) => (d.id === id ? { ...d, text } : d)))
    setDraftsDirty(true)
  }

  function editText(kind, id, field, text) {
    setTextDrafts((ds) => ds.map((d) =>
      (d.kind === kind && d.id === id && d.field === field ? { ...d, text } : d)))
    setDraftsDirty(true)
  }

  // autoStart: the parent owns the trigger (a header button), so skip the idle button and
  // go straight to the preview once the gate check resolves to enabled.
  useEffect(() => {
    if (autoStart && enabled === true && panelState === 'idle') startPreview()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, enabled])

  function cancelPreview() {
    // Parent-controlled (header button): closing returns to the header, not a lone idle
    // button we'd otherwise be stuck on (autoStart hides it).
    if (onClose) { onClose(); return }
    setPanelState('idle')
    setPreview(null)
    setStaleNotice(null)
    setScrolledThrough(false)
  }

  async function handleConfirm() {
    setPanelState('sending')
    try {
      const r = isMulti
        ? await postMultiExportConfirm(metrics, scopeLabel, preview.confirmation_token,
                                       optsFor(reportDrafts, textDrafts))
        : await postExportConfirm(metric, preview.confirmation_token)
      setResult(r)
      setPanelState('result')
    } catch (e) {
      if (e.status === 409) {
        // Data changed since preview — refetch so the user reviews the CURRENT
        // picture; never auto-resubmit the stale one.
        try {
          const fresh = isMulti
            ? await postMultiExportPreview(metrics, scopeLabel, optsFor(reportDrafts, textDrafts))
            : await postExportPreview(metric)
          setStaleNotice(describeChange(preview.payload[0], fresh.payload[0]))
          setPreview(fresh)
          setScrolledThrough(false)
          setPanelState('preview')
        } catch (e2) {
          setError(e2.message || 'The data changed, and the updated preview could not be loaded.')
          setPanelState('error')
        }
      } else {
        setError(e.message || 'Could not send the export.')
        setPanelState('error')
      }
    }
  }

  function reset() {
    setResult(null)
    setStaleNotice(null)
    setError(null)
    setScrolledThrough(false)
    setPreview(null)
    // "Export again": in autoStart mode the idle button is hidden, so re-run the preview
    // rather than stranding on a blank idle; otherwise return to the idle trigger.
    if (autoStart) { startPreview(); return }
    setPanelState('idle')
  }

  if (enabled === null) return null // still checking the gate — avoid a flash of the off-state
  if (!enabled) {
    return (
      <p className="export__off muted">
        External export is off. <Link to="/settings" className="baseline__link">Enable it in Settings</Link>.
      </p>
    )
  }

  const bundle = preview?.payload?.[0]

  // Faithful facts render — one BundleFacts for a single metric, or a collapsed group per
  // metric for a multi-metric set (so a big full-picture payload stays reviewable, per the
  // charter). Used by BOTH the preview and the result's "what was sent," so they can't drift.
  const renderFacts = (b) => {
    if (!isMulti) return <BundleFacts bundle={b} />
    return (
      <>
        <p className="muted small">
          {b.scope ? `${b.scope} — ` : ''}{b.metrics.length} metric{b.metrics.length === 1 ? '' : 's'}.
        </p>
        {b.metrics.map((mb) => (
          <details key={mb.metric} className="export__metric-group">
            <summary>{mb.metric} <span className="muted small">({mb.readings.length} of {mb.n_readings} readings)</span></summary>
            <BundleFacts bundle={mb} />
          </details>
        ))}
        {/* A full-picture bundle carries the non-metric half as sibling top-level keys.
            Keyed off `profile` rather than the includeContext prop so this renders what
            the PAYLOAD actually contains — the same reason BundleFacts reads the bundle. */}
        {b.profile !== undefined && <ContextFacts bundle={b} />}
      </>
    )
  }

  // Every editable piece of prose in one box, deliberately ABOVE the faithful payload
  // render: you redact here, then read below what that produced. The two stay separate on
  // purpose — this is a working copy, and the payload section is the truth of what leaves
  // (it also shows the gateway's own automatic redactions, applied after this is submitted).
  //
  // Reports and row notes share this box rather than getting an editor each. They are the
  // same risk — free text where an identifier can hide — and giving them separate homes is
  // how one ends up redactable and the other only fixable by leaving the flow.
  const renderTextEditors = () => {
    if (!withContext || (reportDrafts.length === 0 && textDrafts.length === 0)) return null
    return (
      <div className="export__reports-edit">
        <h4 className="export__section">
          Free text in this export ({reportDrafts.length + textDrafts.length})
        </h4>
        <p className="muted small">
          Prose can&rsquo;t be checked automatically for names the way a column can. Edit
          anything here before sending — what you leave is exactly what gets sent, and your
          saved records are not changed. Emptying a report excludes it entirely.
        </p>

        {reportDrafts.map((d) => (
          <div className="export__report" key={`r-${d.id}`}>
            <div className="export__report-head">
              {d.study_date ?? 'Undated'}{d.study_description ? ` — ${d.study_description}` : ''}
              {!d.text.trim() && <span className="muted small"> — excluded</span>}
            </div>
            <textarea className="export__report-edit" rows={8} value={d.text}
                      spellCheck={false}
                      onChange={(e) => editReport(d.id, e.target.value)} />
          </div>
        ))}

        {textDrafts.map((d) => (
          <div className="export__report" key={`t-${d.kind}-${d.id}-${d.field}`}>
            <div className="export__report-head">
              {d.label} <span className="muted small">({d.field})</span>
            </div>
            <textarea className="export__report-edit" rows={2} value={d.text}
                      spellCheck={false}
                      onChange={(e) => editText(d.kind, d.id, d.field, e.target.value)} />
          </div>
        ))}

        {draftsDirty && (
          <p className="export__stale">
            You&rsquo;ve edited something since this preview was built — rebuild it so what
            you approve is what gets sent.
          </p>
        )}
        <button type="button" className="baseline__link"
                disabled={!draftsDirty || panelState === 'sending'}
                onClick={() => startPreview(currentDrafts())}>
          Rebuild preview with these edits
        </button>
      </div>
    )
  }

  // The result renders as its OWN standalone section — deliberately NOT
  // nested inside the .export__block workflow container below (trigger /
  // preview / error). The payload (cited facts, sent under the "Export to an
  // external model" identity) and the model's response (reasoning) must never
  // share one undifferentiated box: this is the visual tier boundary CLAUDE.md
  // "The export handoff" requires — the SAME violet + lightbulb "model reasoning"
  // language the removed InterpretationPanel used, so "model talking" reads
  // consistently (this panel now owns that treatment).
  if (panelState === 'result' && result) {
    return (
      <section className="export__result">
        <div className="export__result-header">
          <LightbulbIcon size={16} />
          Response from {result.engine}{result.model ? ` (${result.model})` : ''} — model reasoning: possibilities to discuss with a clinician, not a diagnosis
        </div>
        {/* Model output is Markdown (it emits **bold** headers and bullet lists), so it
            renders through the app's own renderer — React elements only, never HTML, so
            markup in a model response can't become live DOM. */}
        <div className="export__result-text md">
          <Markdown text={result.output} />
        </div>
        {/* Deterministic — always rendered from its own field, never woven
            into the model's text, so a future response can't omit it. */}
        <p className="export__disclaimer">{result.disclaimer}</p>
        {/* The archive write failed AFTER the send completed, so this response exists
            here and nowhere else — it will NOT appear under Settings → External export,
            and re-getting it would mean consenting to send the data again. Warn loudly
            enough that the text gets copied before this view is navigated away from. */}
        {result.saved === false && (
          <p className="form__error">
            ⚠ This response could not be saved to your local record — it won&rsquo;t appear
            under Settings → External export. Copy the text above if you want to keep it;
            getting it back would require sending your data again.
          </p>
        )}
        {!result.model && (
          <p className="muted small">
            Model unavailable — the external provider isn&rsquo;t wired yet in this build.
          </p>
        )}
        {/* Keep the sent facts co-visible with the response so the reasoning stays
            cross-checkable against exactly what the model saw (the "temporal severance"
            fix) — the SAME BundleFacts render as the preview, collapsed by default. */}
        {bundle && (
          <details className="export__sent">
            <summary>Show the facts that were sent</summary>
            {renderFacts(bundle)}
          </details>
        )}
        <button type="button" className="baseline__link" onClick={reset}>Export again</button>
        {onClose && (
          <button type="button" className="baseline__link" onClick={onClose}>Close</button>
        )}
      </section>
    )
  }

  // In autoStart mode the idle button is hidden (the parent's header button is the trigger);
  // the effect kicks off the preview, so idle is just a transient blank frame.
  if (autoStart && panelState === 'idle') return null

  return (
    <section className="export__block">
      {panelState === 'idle' ? (
        // The header row itself is the clickable trigger (the redundant
        // "Export this metric's picture…" sub-button was removed), mirroring the
        // personal-baseline quiet-link.
        // Wrapped, NOT passed as onClick={startPreview}: React would hand the click
        // event in as the `drafts` argument, and an event is not an array.
        <button type="button" className="export__header export__header--trigger"
                onClick={() => startPreview()}>
          {triggerLabel}
        </button>
      ) : (
        <div className="export__header">
          {triggerLabel}
        </div>
      )}

      {panelState === 'loading-preview' && <Loading what="the preview" inline />}

      {(panelState === 'preview' || panelState === 'sending') && bundle && (
        <>
          {providerInfo && (
            <p className="export__destination">
              This will be sent to <strong>{providerInfo.label}</strong>. {providerInfo.description}
            </p>
          )}
          {staleNotice && (
            <p className="export__stale">{staleNotice} Review the updated picture below.</p>
          )}
          <p className="muted small">
            This is the complete picture that would leave your machine — review it, then confirm.
          </p>

          {renderTextEditors()}
          {renderFacts(bundle)}

          {/* The instruction is the OTHER half of what the provider receives, and it
              shapes the entire answer — reviewing only the data leaves you unable to
              tell why a response reads the way it does. Collapsed by default: it's
              static developer text carrying none of your data, so it doesn't belong
              in the scroll path the consent gate measures, but it must be reachable. */}
          {preview.instruction && (
            <details className="export__sent">
              <summary>Show the instructions sent with this data</summary>
              <p className="export__instruction">{preview.instruction}</p>
              <p className="muted small">
                Fixed text written into the app — it contains none of your health data, and
                it is the same for every send. It is not part of the confirmation token,
                which binds the data above.
              </p>
            </details>
          )}

          {(preview.excluded_fields.length > 0 || preview.redactions.length > 0) && (
            <p className="export__warn">
              {preview.excluded_fields.length > 0 &&
                `${preview.excluded_fields.length} field(s) excluded: ${preview.excluded_fields.join(', ')}. `}
              {preview.redactions.length > 0 &&
                `Redacted: ${preview.redactions.map((r) => `${r.type} (${r.count})`).join(', ')}.`}
            </p>
          )}

          <div ref={sentinelRef} className="export__sentinel" />
          <hr className="export__divider" />
          <div className="baseline__actions">
            <button type="button" className="baseline__primary-btn export__confirm-btn"
                    disabled={!scrolledThrough || draftsDirty || panelState === 'sending'}
                    onClick={handleConfirm}>
              {panelState === 'sending'
                ? 'Sending…'
                : draftsDirty
                  ? 'Rebuild the preview to continue'
                  : scrolledThrough
                    ? `Send to ${providerInfo?.label ?? 'the provider'}`
                    : 'Scroll through the full payload to continue'}
            </button>
            <button type="button" className="baseline__link" onClick={cancelPreview}
                    disabled={panelState === 'sending'}>
              Cancel
            </button>
          </div>
        </>
      )}

      {panelState === 'error' && (
        <>
          <p className="form__error">{error}</p>
          <button type="button" className="baseline__link" onClick={reset}>Try again</button>
        </>
      )}
    </section>
  )
}
