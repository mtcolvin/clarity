import { useId } from 'react'
import { STATIC_DEMO } from '../../api'
import { ExternalLinkIcon } from '../icons'

// The published demo's way back out: to the site that links to it, and to the source.
//
// STATIC BUILD ONLY, and only when configured (`.env.static`). Someone who clones the repo
// and runs Clarity on their own record has no use for a link to the author's portfolio, and
// a fork that publishes its own demo points these somewhere else or leaves them unset — in
// which case nothing renders.
//
// And only on the HOST they belong to (`VITE_DEMO_LINKS_HOST`): the same build is reachable
// at the repo's github.io address too, and there a "back to blot.world" button would claim
// a visitor came from a site they never saw. Checked at runtime, since one artifact is
// served under both names.
//
// It sits at the right of the app header rather than in a strip of its own. The imaging and
// documents panes size themselves to the viewport minus a FIXED header height, so a second
// bar above the header would push their bottom edge off-screen; the header has the room.
// Except on a phone, where the "Static demo" label already fills the bar — there the links
// move to the foot of the nav drawer instead (`placement="drawer"`). Both copies are always
// rendered and CSS shows exactly one of them, so the choice follows the window, not a guess
// made once at load.
//
// The home link is a copy of blot.world's own "mini nav" — a frosted pill with a back arrow,
// the BLOT mark cut through it, and the wordmark stepping down in weight letter by letter —
// so it reads as that site's control rather than this app's. Its typeface is a ~3 KB subset
// of Roboto Flex (just these letters, weight axis only, OFL — licence beside the file),
// SELF-HOSTED: the app takes no webfont from a CDN. It is small enough that Vite inlines it
// into the stylesheet, so it costs no request either.
const HOME_URL = import.meta.env.VITE_DEMO_HOME_URL
const HOME_LABEL = import.meta.env.VITE_DEMO_HOME_LABEL || 'Back'
const REPO_URL = import.meta.env.VITE_DEMO_REPO_URL
const LINKS_HOST = import.meta.env.VITE_DEMO_LINKS_HOST

// blot.world's mark, as its mini nav draws it (projects/*/index.html, the logo-cut mask).
const BLOT_MARK = 'M991,460.892L991,467.417C990.891,471.541 990.574,475.688 990.043,479.868C985.994,511.733 969.382,546.346 934.452,588.386C910.036,617.773 886.483,628.622 864.884,628.983C843.104,629.347 822.351,618.772 803.15,601.339C781.514,581.694 761.573,553.12 743.353,526.84C732.706,511.483 722.691,496.992 712.824,486.256C706.296,479.154 700.646,473.227 694.144,472.875C688.497,472.57 684.012,477.895 677.96,486.659C667.609,501.651 656.963,525.889 645.189,561.882C624.028,626.57 594.224,674.799 567.479,713.734C518.847,784.532 463.748,816.88 412.069,822.169C406.628,822.726 401.22,823 395.854,823C348.855,823 305.12,801.988 271.212,766.077C230.671,723.142 204,658.105 204,583.15C204,502.498 234.88,410.363 312.59,321.927C417.276,202.792 515.293,156.353 603.237,156.003C603.77,156.001 604.303,156 604.836,156C760.712,156 874.851,246.86 934.732,332.382C968.829,381.081 989.926,420.198 991,460.892ZM429.775,332.043C368.872,386.834 339.368,425.638 310.535,510.048C288.666,574.07 296.348,629.231 331.119,679.616C353.445,711.967 375.334,727.662 397.28,730.179C418.739,732.64 439.297,722.479 458.566,706.838C503.108,670.68 540.149,605.196 561.946,562.113C591.8,503.102 616.674,424.109 619.608,360.732C621.284,324.538 616.936,293.587 597.836,278.396C575.999,261.028 548.344,265.774 510.267,279.007C482.05,288.814 466.82,298.716 429.775,332.043ZM837.246,342.426C803.429,308.395 771.489,288.698 746.968,279.148C733.294,273.823 722.532,271.555 715.878,272.522C714.92,272.661 714.747,273.573 714.588,274.515C714.347,275.942 714.254,277.489 714.247,279.137C714.228,284.039 714.981,289.584 716.186,295.564C723.559,332.177 747.03,381.749 757.783,409.859C767.355,434.879 801.075,501.32 839.443,528.626C848.906,535.361 858.483,539.775 868.084,537.94C878.041,536.037 886.981,527.525 895.925,512.194C927.84,457.492 909.454,415.088 837.246,342.426Z'
const WORDMARK = ['B', 'L', 'O', 'T', '.', 'W', 'O', 'R', 'L', 'D']

function onLinksHost() {
  if (!LINKS_HOST) return true
  return typeof window !== 'undefined' && window.location.hostname === LINKS_HOST
}

function MiniNav({ href, label }) {
  // Two copies render (header + drawer), so each needs its own mask id.
  const maskId = `blot-cut-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const mask = `url(#${maskId})`
  return (
    <a className="mininav" href={href} aria-label={`Back to ${label}`}>
      <span className="mininav__blur" style={{ mask, WebkitMask: mask }} aria-hidden="true" />
      <svg className="mininav__bg" viewBox="0 0 170 40" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <mask id={maskId} maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse">
            <rect x="0" y="0" width="170" height="40" fill="white" />
            <g transform="translate(46,20) scale(0.028) translate(-500,-490)">
              <path fill="black" d={BLOT_MARK} />
            </g>
          </mask>
        </defs>
        <rect className="mininav__rect" x="0" y="0" width="170" height="40" mask={mask} />
      </svg>
      <span className="mininav__inner">
        <svg className="mininav__arrow" width="18" height="18" viewBox="3 3 18 18" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
             aria-hidden="true">
          <path d="M19 12H5M12 19l-7-7 7-7" />
        </svg>
        <span className="mininav__title" aria-hidden="true">
          {WORDMARK.map((ch, i) => <span key={i}>{ch}</span>)}
        </span>
      </span>
    </a>
  )
}

export default function PortfolioLinks({ placement = 'header' }) {
  if (!STATIC_DEMO || (!HOME_URL && !REPO_URL) || !onLinksHost()) return null
  return (
    <nav className={`portfolio-links portfolio-links--${placement}`} aria-label="About this demo">
      {HOME_URL && <MiniNav href={HOME_URL} label={HOME_LABEL} />}
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
