import { useEffect, useState } from 'react'
import { getDemo } from './api'

// Which store this window is talking to — asked ONCE and shared.
//
// Two things read it and they sit in different places: the badge in the app header (the
// ambient "these are invented records") and the mismatch alarm below it (the loud "this
// window was started as a demo and is NOT on one"). A module-level promise means one
// request rather than one per consumer, and — more usefully — it means they can never
// disagree, which for a notice about whose data is on screen is the whole point.
//
// Three states throughout: `null` is "haven't asked yet", and neither consumer renders
// anything on it. Silence never claims a real record is fake, and never fires the alarm in
// the moment before the answer arrives.

// Was this window STARTED as a demo? Vite sets the mode from `--mode demo` (demo.bat). It
// is a build-time fact, so it cannot drift the way a fetched flag can — which is exactly
// what makes it worth comparing against the fetched one.
export const DEMO_BUILD = import.meta.env.MODE === 'demo'

let pending = null

function fetchDemo() {
  if (!pending) {
    pending = getDemo()
      .then((d) => Boolean(d?.demo))
      .catch(() => null)   // no answer is not a claim either way
  }
  return pending
}

export function useDemoState() {
  const [demo, setDemo] = useState(null)
  useEffect(() => {
    let cancelled = false
    fetchDemo().then((v) => { if (!cancelled) setDemo(v) })
    return () => { cancelled = true }
  }, [])
  return demo
}
