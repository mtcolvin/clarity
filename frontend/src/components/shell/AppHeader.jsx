import { MenuIcon } from '../icons'
import DemoBadge from './DemoBadge'

// Persistent top bar on every route: the hamburger button (opens the nav drawer)
// and the app name. The button advertises the drawer it controls for assistive
// tech (aria-controls + aria-expanded).
export default function AppHeader({ onMenuClick, drawerOpen }) {
  return (
    <header className="app-header">
      <button
        type="button"
        className="app-header__menu"
        onClick={onMenuClick}
        aria-label="Open menu"
        aria-controls="nav-drawer"
        aria-expanded={drawerOpen}
      >
        <MenuIcon />
      </button>
      <span className="app-header__title">Clarity</span>
      {/* Beside the app's own name, in the one bar that is on screen wherever you have
          navigated to — and costing no vertical space, which matters on the imaging page,
          where the viewport belongs to the stage. */}
      <DemoBadge />
    </header>
  )
}
