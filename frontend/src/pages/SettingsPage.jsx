import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Tabs from '../components/shell/Tabs'
import DemoInfo from '../components/settings/DemoInfo'
import SettingsPanel from '../components/settings/SettingsPanel'
import ThemeToggle from '../components/settings/ThemeToggle'
import ExportAuditLog from '../components/settings/ExportAuditLog'
import MetricsCoverage from '../components/settings/MetricsCoverage'

// Full-page Settings view, reached from the nav drawer. One tab per settings-
// registry group (the `group` strings on settings.py's SettingDefs — each tab's
// SettingsPanel filters to its group and is its own independent form), plus the
// read-only "Metric coverage" roster. The External export tab also carries the
// after-the-fact send record (ExportAuditLog). The active tab is mirrored to
// ?tab= so refresh/bookmark are stable — the same useSearchParams idiom
// MetricsPage uses for ?metric=. (An old ?tab=settings bookmark falls back to
// the first tab via the TAB_IDS validation.)
const TABS = [
  { id: 'display', label: 'Display' },
  { id: 'baseline', label: 'Personal baseline' },
  { id: 'export', label: 'External export' },
  { id: 'coverage', label: 'Metric coverage' },
  { id: 'demo', label: 'Demo' },
]
const TAB_IDS = TABS.map((t) => t.id)

export default function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  // Capture the URL's tab once as the initial preference; validate against the
  // known tabs, falling back to the first. After mount, `active` owns the choice
  // and writes itself back to the URL (mirrors MetricsPage's ?metric= handling).
  const [active, setActive] = useState(() => {
    const t = searchParams.get('tab')
    return TAB_IDS.includes(t) ? t : TAB_IDS[0]
  })

  useEffect(() => {
    setSearchParams({ tab: active }, { replace: true })
  }, [active, setSearchParams])

  return (
    <section className="settings-page">
      <h2>Settings</h2>
      <Tabs tabs={TABS} active={active} onSelect={setActive} ariaLabel="Settings sections">
        {active === 'display' && (
          <>
            <p className="muted small">
              These control how the dashboard LOOKS and how much it shows — they don’t
              change what counts as a finding.
            </p>
            {/* Outside SettingsPanel's registry form on purpose: the theme lives in this
                browser, not in the settings table, so it has no Save step to join. */}
            <div className="settings">
              <ThemeToggle />
            </div>
            <SettingsPanel groups={['Display volume']} />
          </>
        )}
        {active === 'baseline' && (
          <SettingsPanel groups={['Personal-baseline suggestions']} />
        )}
        {active === 'export' && (
          <>
            <SettingsPanel groups={['External export']} />
            {/* The after-the-fact record complements the export controls; read-only, so
                it lives outside the draft/Save form. ONE list: each send with the
                response it produced, joined on the audit id (ExportResultsLog's separate
                "what came back" section was merged in — two unjoined lists of the same
                events made the pairing the reader's problem). */}
            <ExportAuditLog />
          </>
        )}
        {active === 'coverage' && <MetricsCoverage />}
        {/* Information, not a switch — see DemoInfo for why that distinction is the whole
            design here. */}
        {active === 'demo' && <DemoInfo />}
      </Tabs>
    </section>
  )
}
