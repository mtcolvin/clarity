import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'
import { applyStoredTheme } from './theme'
import { STATIC_DEMO } from './api'

// Routing differs ONLY in the published static demo, and it has to. Every section here is
// its own URL so it can be bookmarked, shared, and survive a refresh — but a static host
// has no SPA fallback: asking GitHub Pages for /metrics gets a 404 from the file server,
// because there is no file there and nothing to rewrite the request to index.html. The
// usual workaround is a 404.html that re-enters the app, which turns every deep link into
// a redirect and every wrong URL into a silent recovery. Hash routing needs no server
// cooperation at all: /#/metrics is one document plus a fragment, so refresh, back, and
// deep links all keep working exactly as they do locally.
const Router = STATIC_DEMO ? HashRouter : BrowserRouter

// BEFORE the first render, off a synchronous localStorage read: the theme has to be on
// <html> when the browser paints, or a dark-theme user sees a white flash on every load.
applyStoredTheme()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Router>
      <App />
    </Router>
  </StrictMode>,
)
