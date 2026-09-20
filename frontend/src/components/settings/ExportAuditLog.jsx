import { useEffect, useState } from 'react'
import { getExportAudit, getExportResults } from '../../api'
import Markdown from '../../markdown'

// "External sends" — the read-only, AFTER-the-fact half of the charter's transparency
// rule (the ExportPanel preview is the before-send half). Renders the gateway audit
// log's external entries verbatim: every send or attempted send, with the exact payload
// that left (or tried to leave) the machine. Local file read only — no model, no egress,
// and deliberately visible even while the export capability is OFF, so turning the
// feature back off never hides what it already did.
//
// Each entry also carries the RESPONSE that came back, joined on `audit_id` (the gateway
// stamps each audit entry with an id and the saved result records it). Sent and received
// belong together: reading a model's reasoning without the facts it saw — or seeing a
// payload leave with no idea what it produced — is half a record either way.
//
// Two rows can't join: a saved result from before `audit_id` existed (no send to point
// at), and a send whose response failed to archive (ExportResultOut.saved === false).
// Both are surfaced explicitly rather than hidden — an unexplained gap in a transparency
// record is worse than a labelled one.
export default function ExportAuditLog() {
  const [entries, setEntries] = useState(null) // null = still loading
  const [results, setResults] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getExportAudit(), getExportResults()])
      .then(([a, r]) => {
        if (cancelled) return
        setEntries(a.entries)
        setResults(r.results)
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [])

  const resultByAuditId = {}
  for (const r of results) if (r.audit_id) resultByAuditId[r.audit_id] = r
  // Saved responses with no send to attach to (pre-`audit_id` rows).
  const orphans = results.filter((r) => !r.audit_id)

  return (
    <div className="audit">
      <h4 className="settings__group">External sends</h4>
      <p className="settings__desc muted small">
        The local record of everything this app has sent (or tried to send) to an external
        provider — exactly what left the machine, with the response that came back, newest
        first. Kept on this machine only; shown even while external export is off.
      </p>
      {error && (
        <p className="form__error">Couldn&rsquo;t load the send record: {error}</p>
      )}
      {entries !== null && entries.length === 0 && (
        <p className="muted small">No external sends recorded.</p>
      )}
      {entries !== null &&
        entries.map((e, i) => {
          const result = e.id ? resultByAuditId[e.id] : undefined
          return (
            <details className="audit__entry" key={e.id ?? `${e.ts}-${i}`}>
              <summary className="audit__summary">
                <span className="audit__ts">{e.ts.slice(0, 19).replace('T', ' ')} UTC</span>
                {' · '}
                <strong>{e.payload?.[0]?.scope ?? e.payload?.[0]?.metric ?? e.task}</strong>
                {' → '}
                {e.provider ?? 'unknown provider'}
                {e.model ? ` (${e.model})` : ''}
                {e.error && <span className="audit__failed"> · attempt failed</span>}
                {!e.error && result && <span className="audit__replied"> · replied</span>}
              </summary>
              {e.error && (
                <p className="audit__error-detail">
                  The send was attempted but no response was served: {e.error}
                </p>
              )}
              <p className="muted small audit__meta">
                task: {e.task}
                {' · redactions: '}
                {e.redactions.length === 0
                  ? 'none'
                  : e.redactions.map((r) => `${r.type} (${r.count})`).join(', ')}
                {Object.keys(e.provider_settings).length > 0 && (
                  <>
                    {' · provider settings: '}
                    {Object.entries(e.provider_settings)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(', ')}
                  </>
                )}
              </p>

              {/* The response, attached to the send that produced it. Model reasoning —
                  same framing the response itself carried when it was first shown. */}
              {result && (
                <div className="audit__response">
                  <div className="audit__response-head">
                    Response{result.model ? ` from ${result.model}` : ''} — model reasoning:
                    possibilities to discuss with a clinician, not a diagnosis
                  </div>
                  <div className="md">
                    <Markdown text={result.output} />
                  </div>
                </div>
              )}
              {!result && !e.error && e.id && (
                <p className="muted small">
                  No saved response attached to this send — it may have failed to archive.
                </p>
              )}

              {/* The payload verbatim — same faithful-and-complete bar as the
                  preview: the record is what was sent, never a summary of it. */}
              <details className="audit__payload-wrap">
                <summary>Show exactly what was sent</summary>
                <pre className="audit__payload">{JSON.stringify(e.payload, null, 2)}</pre>
              </details>
            </details>
          )
        })}

      {orphans.length > 0 && (
        <>
          <h5 className="settings__group">Responses without a linked send</h5>
          <p className="settings__desc muted small">
            Saved before sends carried an id, so there is nothing to attach them to. The
            response is intact; only the link is missing.
          </p>
          {orphans.map((r) => (
            <details className="audit__entry" key={r.id}>
              <summary className="audit__summary">
                <span className="audit__ts">{r.created_at}</span>
                {' · '}
                <strong>{r.scope || 'Export'}</strong>
                {r.model ? ` · ${r.model}` : ''}
              </summary>
              <div className="md">
                <Markdown text={r.output} />
              </div>
              {r.metrics.length > 0 && (
                <p className="muted small">Metrics sent: {r.metrics.join(', ')}</p>
              )}
            </details>
          ))}
        </>
      )}
    </div>
  )
}
