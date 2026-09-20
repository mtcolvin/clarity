import { useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'

// The nav sections, in the fixed order. Every entry is now a real page — the last
// "Coming soon" stub (Immunizations) became a Profile tab with real records, and the
// ComingSoon component went with it. A future section earns an entry when it has
// content, rather than advertising an empty room.
const NAV_ITEMS = [
  { to: '/', label: 'Home', end: true },
  { to: '/metrics', label: 'Metrics' },
  { to: '/imaging', label: 'Imaging' },
  { to: '/timeline', label: 'Timeline' },
  { to: '/documents', label: 'Documents' },
  { to: '/profile', label: 'Profile' },
  { to: '/settings', label: 'Settings' },
]

// Slide-in navigation drawer + backdrop. Accessibility:
//   - role="dialog" aria-modal so it reads as a modal surface; <nav aria-label>.
//   - Esc closes (keydown listener active only while open).
//   - On open, focus moves to the first menu item; backdrop click closes.
//   - NavLink supplies the active marker (aria-current="page" + highlight) for the
//     current section automatically.
// Clicking any item navigates (NavLink) AND closes the drawer (onClose).
export default function NavDrawer({ open, onClose }) {
  const firstLinkRef = useRef(null)

  // Esc-to-close, bound only while open.
  useEffect(() => {
    if (!open) return
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Move focus into the drawer when it opens, so keyboard users land inside it.
  useEffect(() => {
    if (open) firstLinkRef.current?.focus()
  }, [open])

  if (!open) return null

  return (
    <>
      <div className="nav-backdrop" onClick={onClose} aria-hidden="true" />
      <div
        id="nav-drawer"
        className="nav-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Site menu"
      >
        <nav aria-label="Main" className="nav-drawer__nav">
          <ul className="nav-drawer__list">
            {NAV_ITEMS.map((item, i) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  ref={i === 0 ? firstLinkRef : undefined}
                  className={({ isActive }) =>
                    `nav-drawer__link${isActive ? ' nav-drawer__link--active' : ''}`
                  }
                  onClick={onClose}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </>
  )
}
