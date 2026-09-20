import { useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import AppHeader from './components/shell/AppHeader'
import DemoBanner from './components/shell/DemoBanner'
import NavDrawer from './components/shell/NavDrawer'
import HomePage from './pages/HomePage'
import MetricsPage from './pages/MetricsPage'
import TimelinePage from './pages/TimelinePage'
import ProfilePage from './pages/ProfilePage'
import SettingsPage from './pages/SettingsPage'
import ImagingPage from './pages/ImagingPage'
import DocumentsPage from './pages/DocumentsPage'
import './App.css'

// App shell: a persistent header with the hamburger, the slide-in nav drawer, and
// the routed section below. Each nav section is its own URL (bookmarkable, back-
// button friendly, refresh-stable). The per-section state lives in the page
// components — App only owns the drawer's open/closed flag.
export default function App() {
  const [drawerOpen, setDrawerOpen] = useState(false)

  return (
    <div className="app-shell">
      <AppHeader onMenuClick={() => setDrawerOpen(true)} drawerOpen={drawerOpen} />
      {/* Only the MISMATCH alarm lives here now — the ordinary demo notice is a badge in
          the header. See DemoBanner for why the two are different sizes. */}
      <DemoBanner />
      <NavDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      <main className="app">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/metrics" element={<MetricsPage />} />
          {/* Conditions & medications moved onto Profile (it's the same permanent-record
              register as demographics and collections). The old path still resolves so
              bookmarks — and any timeline entry saved before the link changed — land on
              the tab rather than bouncing to Home via the catch-all. */}
          <Route path="/conditions-medications"
                 element={<Navigate to="/profile?tab=conditions" replace />} />
          <Route path="/imaging" element={<ImagingPage />} />
          {/* Immunizations was a "Coming soon" stub with its own nav entry; it is now a
              Profile tab holding real records. The old path redirects for the same reason
              /conditions-medications does — a bookmark should land on the content. */}
          <Route path="/immunizations"
                 element={<Navigate to="/profile?tab=immunizations" replace />} />
          <Route path="/timeline" element={<TimelinePage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          {/* Unknown path -> Home. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
