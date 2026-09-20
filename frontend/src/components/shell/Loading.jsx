// The app's ONE loading placeholder. Every page and panel used to render its own
// `<p className="muted">Loading…</p>`, which meant fifteen slightly different waits: some
// said what they were loading and some didn't, and all of them were a line of grey prose
// that read like content rather than like a state.
//
// This is a labelled state instead — the same small tracked display face the section
// heads use, with a bar that fills and empties beneath it. The bar is deliberately NOT a
// progress bar: none of these fetches report progress, and a bar that pretends to know
// how far along it is would be lying about the one thing it appears to say. It sweeps to
// show the app is alive and nothing more.
//
// `what` names the thing being fetched ("timeline", "settings"). Naming it matters on a
// page with several panels, where an unlabelled wait doesn't say which one you're
// waiting for. `inline` drops to a single quiet line for a wait inside an already-open
// panel (an expanded collection's analytes), where the full block would be louder than
// the content it replaces.
export default function Loading({ what, inline = false }) {
  const label = what ? `Loading ${what}` : 'Loading'
  if (inline) {
    return <p className="loading loading--inline" role="status">{label}…</p>
  }
  return (
    <div className="loading" role="status">
      <span className="loading__label">{label}</span>
      <span className="loading__bar" aria-hidden="true"><span /></span>
    </div>
  )
}
