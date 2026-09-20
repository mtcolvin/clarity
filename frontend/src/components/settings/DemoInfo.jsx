import { useEffect, useState } from 'react'
import { getDemo } from '../../api'

// Settings → Demo. Says which store this instance is open on, and how to start the other
// one. It is INFORMATION, not a switch, and that is the decision worth recording.
//
// A toggle here would have to repoint four module-level globals in a process that is
// already holding the real record — HEALTH_DB plus dicom_store.IMAGING_DIR,
// reports.ARCHIVE_DIR and docstore.DOCS_DIR, each captured at import — and invalidate at
// least dicom_store's scan cache, which maps series ids to FILE PATHS. Miss that one cache
// and the viewer serves real slices under a banner reading "demo data": a scanned
// requisition in this library carries a name, MRN and DOB burned into its PIXELS. The
// switch that looks convenient is the switch that can put a real medical image on a screen
// you turned around on purpose.
//
// So the isolation stays where it can't be undone by a bug: a separate PROCESS, with the
// real stores not merely hidden but unreachable. This panel just makes that easy to find,
// and — because it reads the same in-database marker the banner does — tells you which one
// you are actually looking at rather than which one you meant to open.
export default function DemoInfo() {
  const [demo, setDemo] = useState(null)   // null = not answered yet

  useEffect(() => {
    let cancelled = false
    getDemo()
      .then((d) => { if (!cancelled) setDemo(Boolean(d?.demo)) })
      .catch(() => { if (!cancelled) setDemo(null) })
    return () => { cancelled = true }
  }, [])

  return (
    <div className="settings settings--prose">
      <p className="settings__intro muted small">
        Demo mode shows the app with an invented record, so you can put it in front of
        someone without showing your own history.
      </p>

      <div className="settings__row">
        <span className="settings__label">This window</span>
        <p className="settings__desc muted small">
          {demo === null
            ? 'Couldn’t reach the backend to check which store it is open on.'
            : demo
              ? 'Open on the DEMO store — every page carries the amber badge beside the '
                + 'app name, and nothing here is a real record.'
              : 'Open on YOUR record. Nothing on screen is invented.'}
        </p>
      </div>

      <div className="settings__row">
        <span className="settings__label">Start the demo</span>
        <p className="settings__desc muted small">
          Run <code>demo.bat</code> in the project folder. It builds{' '}
          <code>demo_store/</code> the first time and opens a second copy of the app at{' '}
          <code>localhost:5174</code>; this one keeps running, untouched, at 5173.
        </p>
      </div>

      <div className="settings__row">
        <span className="settings__label">Why it isn’t a switch</span>
        <p className="settings__desc muted small">
          Demo mode is a separate store and a separate process, so your record is not
          hidden from it — it is unreachable by it. A toggle here would leave both inside
          one running program, where a single stale cache could serve a real image under a
          banner saying it was invented. Imaging is the case that makes it unfixable: a
          scanned form can carry a name and MRN in the pixels themselves.
        </p>
      </div>
    </div>
  )
}
