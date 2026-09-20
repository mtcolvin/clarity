/*
 * Frontend smoke probe — mounts every page under StrictMode against the real local backend,
 * clicks the safe interactive controls, and fails if a page throws or goes blank.
 *
 * WHY THIS EXISTS. Neither existing harness can see the frontend: `pytest` tests Python and
 * `sweep.py` diffs API responses. A React crash — one uncaught error and the whole tree
 * unmounts to a white page — passes `vite build` AND `eslint` cleanly. That is exactly what
 * happened: a `<details onToggle>` handler read `e.currentTarget.open` inside a state
 * UPDATER, React had already nulled currentTarget by the time the updater ran, and clicking
 * a series blanked the Imaging page. Build: clean. Lint: clean. This probe reproduced it in
 * one run.
 *
 * TWO DESIGN POINTS THAT MATTER:
 *  - StrictMode is mandatory, not decoration. The first version of this probe ran WITHOUT it
 *    and PASSED on the broken code, because React's eager-state optimisation happened to run
 *    the updater synchronously while currentTarget was still live. StrictMode defers it, and
 *    `main.jsx` uses StrictMode — a probe that doesn't mirror the real wrapper certifies
 *    builds that crash for the user.
 *  - It drives the REAL backend, GET-ONLY (enforced in env.js, not by avoiding buttons). Real
 *    responses are the point: the shapes that break a page are the odd real ones — a null
 *    unit, an empty series, a colour DICOM with no pixel spacing. Synthetic fixtures agree
 *    with the code by construction, which is how a shape bug hides. Nothing is written to
 *    disk; nothing leaves the machine; no request can mutate the database.
 *
 * Not a replacement for looking at the page — it proves a page RENDERS and SURVIVES
 * interaction, never that it looks right.
 */
import { installDom, blockedWrites } from './env.js'
import { routeKey } from '../src/snapshot.js'

const API = process.env.VITE_API_BASE || 'http://localhost:8000'

// The probe drives the live backend by default, but it can also be pointed at a BUILT
// static demo (see build_static_demo.py) to prove the published artifact actually
// renders — the one check that catches a snapshot whose filenames the client cannot
// find. There the routes are files, so the preflight has to ask for one by its snapshot
// name rather than its route.
const STATIC_DEMO = process.env.VITE_STATIC_DEMO === '1'
const probeUrl = (route) =>
  STATIC_DEMO ? `${API}/${routeKey(route)}.json` : `${API}${route}`

// The pages, and what to click on each. Selectors are declared per page so the probe's
// coverage is auditable rather than emergent.
const PAGES = [
  { path: '/', name: 'Home' },
  { path: '/metrics', name: 'Metrics' },
  { path: '/imaging', name: 'Imaging', click: ['details.dcm__study > summary', '.dcm__series'] },
  { path: '/timeline', name: 'Timeline', click: ['.timeline__month', '.tl-entry__labs > summary'] },
  // Profile carries three tabs now — its own content, conditions & medications (which
  // used to be a page of its own), and collections. GENERIC_CLICK's `.tabs__tab` walks
  // all three, so dropping the old page entry loses no coverage.
  { path: '/profile', name: 'Profile', click: ['.tabs__tab', '.collections__toggle'] },
  { path: '/settings', name: 'Settings', click: ['.tabs__tab'] },
  { path: '/documents', name: 'Documents', click: ['.docs__search-open', '.docs__item'] },
]

// Clicked on every page in addition to the per-page list: the disclosure/tab/expand family,
// which is where render-crashing state bugs live. `.tabs__tab` is here as well as per-page
// because several pages use the shared Tabs component.
const GENERIC_CLICK = ['details > summary', '.tabs__tab', 'button[aria-expanded]']

// A control whose LABEL says it acts is skipped. The GET-only fetch gate already makes a
// write impossible, so this is the second net — it also keeps the probe from wandering into
// modal flows that tell us nothing about a render crash.
const SKIP_LABEL = /delete|remove|confirm|save|send|export|import|rename|edit|clear|add\b/i

// Thresholds are measured against the ROUTED PAGE (`main.app`), never the whole root. The
// app shell — header, hamburger, nav — is ~700 characters and renders whether or not the page
// inside it worked, so a root-length check passes on a page that is still spinning or showing
// its error branch. That false green is not hypothetical: the first version of this probe
// reported all 9 pages PASS while every one of them was stuck on "Loading…", clicking nothing
// but the hamburger.
const MIN_PAGE_HTML = 80
const MAX_CLICKS_PER_PAGE = 12
const READY_TIMEOUT_MS = 10000
const LOADING_RE = /Loading|Loading…/i
const ERROR_RE = /Couldn’t reach the API|Couldn't reach the API|class="error"/

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function backendUp() {
  try {
    const res = await fetch(probeUrl('/metrics'))
    return res.ok
  } catch {
    return false
  }
}

// The visible text of the page's error paragraph, for a legible failure line.
function errorText() {
  const el = document.querySelector('main.app .error') || document.querySelector('main.app p')
  return (el?.textContent || '').trim().slice(0, 160)
}

// The first not-yet-clicked, safe-to-click element currently in the document.
function nextTarget(selectors) {
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      if (el.dataset.probeClicked) continue
      if (SKIP_LABEL.test((el.textContent || '').trim())) continue
      return el
    }
  }
  return null
}

async function probePage(React, createRoot, MemoryRouter, App, page) {
  const problems = []
  const note = (what, err) => problems.push(`${what}: ${err?.stack || err}`)

  const onWindowError = (e) => note('window error', e.error || e.message)
  const onRejection = (r) => note('unhandled rejection', r)
  window.addEventListener('error', onWindowError)
  process.on('unhandledRejection', onRejection)

  document.body.innerHTML = '<div id="root"></div>'
  const root = createRoot(document.getElementById('root'), {
    onUncaughtError: (err, info) => note(`uncaught${info?.componentStack ? ' (in' + info.componentStack.split('\n')[1] + ')' : ''}`, err),
    onCaughtError: (err) => note('caught by boundary', err),
  })

  root.render(
    <React.StrictMode>
      <MemoryRouter initialEntries={[page.path]}>
        <App />
      </MemoryRouter>
    </React.StrictMode>,
  )

  const rootEl = () => document.getElementById('root')
  const pageHtml = () => document.querySelector('main.app')?.innerHTML ?? ''

  // Wait for the page's own fetches to land rather than guessing a fixed delay: some
  // endpoints are genuinely slow (/imaging/studies stats 13,000 files to check its cache).
  const deadline = Date.now() + READY_TIMEOUT_MS
  while (Date.now() < deadline && (pageHtml().length < MIN_PAGE_HTML || LOADING_RE.test(pageHtml()))) {
    await sleep(100)
  }

  const html = pageHtml()
  // ORDER MATTERS: "still loading" is checked BEFORE "blank". A page whose loading
  // placeholder is shorter than MIN_PAGE_HTML — Documents renders a bare
  // "Loading documents…", 39 chars — otherwise trips the length check first and gets
  // reported as a BLANK page, sending you hunting a render crash that isn't there. The
  // failure is real either way; naming it wrong is what costs the time. (Observed: a cold
  // backend took ~10 s to answer /reports, because it probed the offline translator, whose
  // lazy argostranslate import cost that much — so Documents was genuinely still loading and
  // the probe called it blank. Translation has since been removed, taking the delay with it.)
  if (LOADING_RE.test(html)) problems.push(`still loading after ${READY_TIMEOUT_MS} ms`)
  else if (html.length < MIN_PAGE_HTML) problems.push(`page rendered ${html.length} chars (blank)`)
  else if (ERROR_RE.test(html)) problems.push(`rendered its error branch: ${errorText()}`)
  // PROBE_DUMP=metrics prints that page's markup — for working out why a page rendered
  // something other than what you expected. No leading slash: a Git Bash / MSYS shell
  // rewrites a value that starts with "/" into a Windows path. Home is `home`: its path is
  // bare "/", which strips to "", and an empty key can never match a set env var — so the
  // one page carrying the whole-account widgets was the one page you couldn't inspect.
  if (process.env.PROBE_DUMP && (page.path.replace(/^\//, '') || 'home') === process.env.PROBE_DUMP) {
    console.log(`\n--- ${page.path} markup ---\n${rootEl()?.innerHTML}\n--- end ---\n`)
  }

  // Interact. Targets are RE-QUERIED after every click, never collected once up front: a
  // click re-renders, which can replace or reveal DOM nodes — a list captured beforehand
  // goes stale (and silently stopped this probe after one click per page). Elements are
  // marked as they're used so each is clicked once. Each click is followed by a blank-page
  // check, because a crash shows up as the root emptying — the exact symptom `vite build`
  // and `eslint` cannot see.
  const selectors = [...(page.click || []), ...GENERIC_CLICK]
  let clicked = 0
  while (clicked < MAX_CLICKS_PER_PAGE) {
    const el = nextTarget(selectors)
    if (!el) break
    const label = (el.textContent || el.className || '').trim().slice(0, 60)
    el.dataset.probeClicked = '1'
    el.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }))
    clicked += 1
    await sleep(150)
    // A crash unmounts the whole tree, shell included — so the crash check is on the ROOT,
    // while the "did the page render" check above is on the page. Both matter.
    const rootLen = rootEl()?.innerHTML.length ?? 0
    if (rootLen < MIN_PAGE_HTML) {
      problems.push(`blanked after clicking "${label}" (root ${rootLen} chars)`)
      break
    }
  }

  // Some pages' main interaction is a <select>, not a button — Metrics is driven entirely by
  // its metric picker, and switching metric is exactly the path that re-renders a chart. So
  // also change each select to a different option.
  let changed = 0
  for (const sel of [...document.querySelectorAll('main.app select')].slice(0, 3)) {
    const other = [...sel.options].find((o) => o.value !== sel.value)
    if (!other) continue
    sel.value = other.value
    sel.dispatchEvent(new window.Event('change', { bubbles: true }))
    changed += 1
    await sleep(400)                     // a metric switch refetches series + flags
    const rootLen = rootEl()?.innerHTML.length ?? 0
    if (rootLen < MIN_PAGE_HTML) {
      problems.push(`blanked after selecting "${other.value}" (root ${rootLen} chars)`)
      break
    }
  }

  root.unmount()
  window.removeEventListener('error', onWindowError)
  process.off('unhandledRejection', onRejection)
  return { clicked, changed, problems }
}

async function main() {
  installDom()
  if (!(await backendUp())) {
    console.error(`\n  The backend isn't answering at ${API}.`)
    console.error('  This probe drives the real local API (GET-only) so it sees real response')
    console.error('  shapes. Start it (start.bat, or uvicorn api:app) and re-run.\n')
    process.exit(2)
  }

  const React = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { MemoryRouter } = await import('react-router-dom')
  const { default: App } = await import('../src/App.jsx')

  let failed = 0
  console.log(`frontend smoke probe — ${PAGES.length} pages, StrictMode, GET-only against ${API}\n`)
  for (const page of PAGES) {
    const { clicked, changed, problems } = await probePage(React, createRoot, MemoryRouter, App, page)
    if (problems.length === 0) {
      const acts = [`${clicked} click${clicked === 1 ? '' : 's'}`]
      if (changed) acts.push(`${changed} select change${changed === 1 ? '' : 's'}`)
      console.log(`  PASS  ${page.name}  (${acts.join(', ')})`)
    } else {
      failed += 1
      console.log(`  FAIL  ${page.name}`)
      for (const p of problems) console.log(`          ${p.split('\n').slice(0, 6).join('\n          ')}`)
    }
  }

  if (blockedWrites.length) {
    // Informational: a click reached a write. The gate refused it, and the page's error
    // branch is itself worth exercising — but it's printed so it can never be silent.
    console.log(`\n  ${blockedWrites.length} write request(s) refused by the GET-only gate:`)
    for (const w of new Set(blockedWrites)) console.log(`      ${w}`)
  }

  console.log(failed === 0 ? `\nall ${PAGES.length} pages survived.\n`
                           : `\n${failed} of ${PAGES.length} pages failed.\n`)
  process.exit(failed === 0 ? 0 : 1)
}

await main()
