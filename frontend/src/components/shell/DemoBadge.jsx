import { useState } from 'react'
import { useDemoState } from '../../demoState'
import { STATIC_DEMO } from '../../api'

// The demo notice, IN the app header beside the app name.
//
// It used to be a full-width strip under the header. In the header it costs no vertical
// space at all — which matters on the one page that hands its whole viewport to a locked
// stage — and it sits next to the thing it qualifies: the app's own name, in the bar that
// is on screen no matter where you have navigated to.
//
// The sentence rides along on wide windows and drops on narrow ones. What must never drop
// is the LABEL, so the word "demo" survives at any width; the explanation is for the person
// being shown the screen, and they are looking at a laptop, not a phone.
//
// TWO DIFFERENT CLAIMS, and they are not interchangeable. Locally, "Demo data" answers the
// only question that matters — is this someone's real medical history? On the PUBLISHED
// build the reader is a stranger evaluating the software itself, and for them the record
// being invented is half the story: the other half is that there is no backend behind the
// page, so several things they are about to click cannot work. Saying only "demo data"
// there would leave them to discover that as a series of small breakages and conclude the
// app is broken rather than that the demo is static. So the static build says what it is
// and offers the limitations, once, on demand.
export default function DemoBadge() {
  const demo = useDemoState()
  const [open, setOpen] = useState(false)
  if (demo !== true) return null

  if (!STATIC_DEMO) {
    return (
      <span className="demo-badge" role="status">
        <strong>Demo data</strong>
        <span className="demo-badge__note">
          Invented records — not a real person’s medical history.
        </span>
      </span>
    )
  }

  return (
    <span className="demo-badge demo-badge--static" role="status">
      <strong>Static demo</strong>
      <span className="demo-badge__note">
        Invented records, no backend — read-only.
      </span>
      <button
        type="button"
        className="demo-badge__more"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? 'Hide details' : 'What’s limited?'}
      </button>
      {open && (
        <div className="demo-badge__panel">
          <p>
            This is a <strong>snapshot</strong> of Clarity running against an invented
            record — a folder of captured responses, with no server behind it. Everything
            you see is real output from the real application; what is missing is anything
            that needs a running backend.
          </p>
          <ul>
            <li><strong>Nothing can be changed.</strong> Adding, editing and deleting are
              disabled, and settings cannot be saved.</li>
            <li><strong>Document search</strong> answers a handful of pre-captured terms
              (try <em>thyroid</em> or <em>ferritin</em>). Anything else reports that it is
              not part of the snapshot.</li>
            <li><strong>External export is switched off</strong> and cannot be switched on.
              In the real app it is off by default too, and every send is previewed and
              confirmed.</li>
            <li><strong>Imaging measurements</strong> — region statistics need the original
              pixel data on a server. Scrolling, zoom, window/level and distance/angle all
              work here, because those run in the browser.</li>
          </ul>
          <p className="demo-badge__foot">
            The medical record shown is invented and describes no real person. Run Clarity
            locally to use it with your own records.
          </p>
        </div>
      )}
    </span>
  )
}
