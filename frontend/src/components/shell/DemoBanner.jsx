import { DEMO_BUILD, useDemoState } from '../../demoState'

// The MISMATCH alarm, and only that: this window was started as a demo (`--mode demo`) but
// the backend it reached says it is open on a REAL store.
//
// It stays a full-width strip while the ordinary demo notice moved into the header, and the
// asymmetry is deliberate. The reassurance is ambient — you want it present, not
// interrupting. This is the opposite: it means a real medical record is on screen,
// unlabelled, in a window you opened specifically to show to someone. It is exactly what a
// mistyped API base produces (a demo window quietly talking to the real instance on :8000),
// which is not hypothetical — it is the bug that shipped in the first launcher. An
// interruption is the correct size for it.
export default function DemoBanner() {
  const demo = useDemoState()
  if (!DEMO_BUILD || demo !== false) return null
  return (
    <div className="demo-banner demo-banner--wrong" role="alert">
      <strong>Not demo data</strong>
      <span>
        This window was started as a demo but is connected to a REAL record. Close it and
        check that the demo backend is running on its own port.
      </span>
    </div>
  )
}
