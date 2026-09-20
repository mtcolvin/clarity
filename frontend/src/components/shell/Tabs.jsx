import { useRef } from 'react'

// Reusable, controlled tab strip. Router-agnostic and state-agnostic: the parent
// owns the active id (and, if it wants, mirrors it to the URL) and passes the
// active panel's content as children. This component only renders the tablist +
// the panel wrapper and handles the WAI-ARIA tab semantics.
//
// Accessibility (the minimal standard set): role tablist/tab/tabpanel, aria-selected,
// aria-controls<->aria-labelledby linking each tab to its panel, roving tabindex
// (only the active tab is in the tab order), and Left/Right arrow navigation with
// automatic activation (focus follows selection). Home/End, vertical orientation,
// and manual-activation mode are intentionally not implemented.
export default function Tabs({ tabs, active, onSelect, ariaLabel, children }) {
  const tabRefs = useRef([])

  function onKeyDown(e) {
    const idx = tabs.findIndex((t) => t.id === active)
    if (idx === -1) return
    let next = null
    if (e.key === 'ArrowRight') next = (idx + 1) % tabs.length
    else if (e.key === 'ArrowLeft') next = (idx - 1 + tabs.length) % tabs.length
    if (next === null) return
    e.preventDefault()
    onSelect(tabs[next].id)
    tabRefs.current[next]?.focus()
  }

  return (
    <div className="tabs">
      <div className="tabs__list" role="tablist" aria-label={ariaLabel}>
        {tabs.map((t, i) => {
          const selected = t.id === active
          return (
            <button
              key={t.id}
              ref={(el) => (tabRefs.current[i] = el)}
              id={`tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`panel-${t.id}`}
              tabIndex={selected ? 0 : -1}
              className={`tabs__tab${selected ? ' tabs__tab--active' : ''}`}
              onClick={() => onSelect(t.id)}
              onKeyDown={onKeyDown}
            >
              {t.label}
            </button>
          )
        })}
      </div>
      <div
        role="tabpanel"
        id={`panel-${active}`}
        aria-labelledby={`tab-${active}`}
        className="tabs__panel"
        tabIndex={0}
      >
        {children}
      </div>
    </div>
  )
}
