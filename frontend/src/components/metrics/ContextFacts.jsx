// The faithful render of the NON-metric half of a full-picture export payload — the
// profile, conditions, medications, events, imaging and radiology reports assembled by
// picture.py. Sibling to BundleFacts (which renders one metric's readings/findings), and
// shared the same way: the preview and the "what was sent" block alongside a result both
// use it, so the two can never drift.
//
// Everything here renders from `bundle` — the actual outbound payload the gateway built,
// AFTER its allowlist and scrub. That is the point: this is the truth of what leaves, not
// a re-derivation of what we think we sent. The report EDITORS live in ExportPanel and are
// a separate thing (a draft you are still changing); this section shows the result.

function Section({ title, count, children }) {
  return (
    <>
      <h4 className="export__section">{title} ({count})</h4>
      {count === 0 ? <p className="muted small">None.</p> : children}
    </>
  )
}

// A value plus its unit, or an em dash — used for the measurement histories, whose units
// are stored exactly as entered (lb vs kg) and are never converted.
const measure = (m) => `${m.value}${m.unit ? ` ${m.unit}` : ''}`

export default function ContextFacts({ bundle }) {
  const p = bundle.profile ?? {}
  const conditions = bundle.conditions ?? []
  const medications = bundle.medications ?? []
  const events = bundle.events ?? []
  const imaging = bundle.imaging ?? []
  const reports = bundle.reports ?? []

  return (
    <>
      <h4 className="export__section">Profile</h4>
      <div className="export__finding">
        Biological sex: {p.sex ?? '—'}<br />
        Age: {p.age_years ?? '—'}{p.age_years != null ? ' years' : ''}<br />
        {/* Stated explicitly rather than left to inference: a reader checking what leaves
            should be able to confirm the absence, not just fail to spot it. */}
        <span className="muted small">
          Your date of birth is not sent — only the age computed from it.
        </span>
      </div>

      <Section title="Weight history" count={p.weight?.length ?? 0}>
        <table className="readings">
          <thead><tr><th>Date</th><th>Weight</th></tr></thead>
          <tbody>
            {(p.weight ?? []).map((m) => (
              <tr key={m.recorded_on}><td>{m.recorded_on}</td><td>{measure(m)}</td></tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Height history" count={p.height?.length ?? 0}>
        <table className="readings">
          <thead><tr><th>Date</th><th>Height</th></tr></thead>
          <tbody>
            {(p.height ?? []).map((m) => (
              <tr key={m.recorded_on}><td>{m.recorded_on}</td><td>{measure(m)}</td></tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Conditions" count={conditions.length}>
        <table className="readings">
          <thead>
            <tr><th>Onset</th><th>Condition</th><th>Status</th><th>Notes</th></tr>
          </thead>
          <tbody>
            {conditions.map((c, i) => (
              <tr key={i}>
                <td>{c.onset_on ?? '—'}</td>
                <td>{c.name}{c.icd10 ? ` (${c.icd10})` : ''}</td>
                <td>{c.status}{c.resolved_on ? ` ${c.resolved_on}` : ''}</td>
                <td>{c.notes ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Medications" count={medications.length}>
        <table className="readings">
          <thead>
            <tr><th>Started</th><th>Medication</th><th>Dose</th><th>Ended</th><th>Notes</th></tr>
          </thead>
          <tbody>
            {medications.map((m, i) => (
              <tr key={i}>
                <td>{m.start_date ?? '—'}</td>
                <td>{m.name}</td>
                <td>{[m.dose, m.frequency].filter(Boolean).join(', ') || '—'}</td>
                <td>{m.active ? 'ongoing' : (m.end_date ?? '—')}</td>
                <td>{m.notes ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Events" count={events.length}>
        <table className="readings">
          <thead><tr><th>Date</th><th>Type</th><th>Title</th><th>Notes</th></tr></thead>
          <tbody>
            {events.map((e, i) => (
              <tr key={i}>
                <td>{e.date}</td><td>{e.type}</td><td>{e.title}</td><td>{e.notes ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Imaging studies" count={imaging.length}>
        <table className="readings">
          <thead>
            <tr><th>Date</th><th>Study</th><th>Modality</th><th>Body part</th><th>Images</th></tr>
          </thead>
          <tbody>
            {imaging.map((s, i) => (
              <tr key={i}>
                <td>{s.study_date ?? '—'}</td>
                <td>{s.description ?? '—'}</td>
                <td>{s.modalities?.join('/') || '—'}</td>
                <td>{s.body_parts?.join(', ') || '—'}</td>
                <td>{s.n_images} in {s.n_series} series</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Radiology report text" count={reports.length}>
        {reports.map((r, i) => (
          <div className="export__report" key={i}>
            <div className="export__report-head">
              {r.study_date ?? 'Undated'}{r.study_description ? ` — ${r.study_description}` : ''}
            </div>
            {/* Pre-formatted: a report's line breaks carry its structure, and this is the
                exact string that goes over the wire. */}
            <pre className="export__report-text">{r.text}</pre>
          </div>
        ))}
      </Section>
    </>
  )
}
