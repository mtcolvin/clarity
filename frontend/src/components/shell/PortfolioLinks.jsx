import { STATIC_DEMO } from '../../api'
import { ExternalLinkIcon } from '../icons'

// The published demo's way back out: to the site that links to it, and to the source.
//
// STATIC BUILD ONLY, and only when configured (`.env.static`). Someone who clones the repo
// and runs Clarity on their own record has no use for a link to the author's portfolio, and
// a fork that publishes its own demo points these somewhere else or leaves them unset — in
// which case nothing renders.
//
// It sits at the right of the app header rather than in a strip of its own. The imaging and
// documents panes size themselves to the viewport minus a FIXED header height, so a second
// bar above the header would push their bottom edge off-screen; the header has the room.
// Except on a phone, where the "Static demo" label already fills the bar — there the links
// move to the foot of the nav drawer instead (`placement="drawer"`). Both copies are always
// rendered and CSS shows exactly one of them, so the choice follows the window, not a guess
// made once at load.
const HOME_URL = import.meta.env.VITE_DEMO_HOME_URL
const HOME_LABEL = import.meta.env.VITE_DEMO_HOME_LABEL || 'Back'
const REPO_URL = import.meta.env.VITE_DEMO_REPO_URL

export default function PortfolioLinks({ placement = 'header' }) {
  if (!STATIC_DEMO || (!HOME_URL && !REPO_URL)) return null
  return (
    <nav className={`portfolio-links portfolio-links--${placement}`} aria-label="About this demo">
      {HOME_URL && (
        <a className="portfolio-links__link" href={HOME_URL}>
          <span aria-hidden="true">←</span> {HOME_LABEL}
        </a>
      )}
      {REPO_URL && (
        <a
          className="portfolio-links__link portfolio-links__link--repo"
          href={REPO_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          View repo<ExternalLinkIcon />
        </a>
      )}
    </nav>
  )
}
