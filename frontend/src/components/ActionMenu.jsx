import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

// Space to leave between the popup and the viewport edge.
const EDGE_GAP = 12

// A dependency-free dropdown menu button, in the same spirit as Modal/NavDrawer:
// no library, explicit ARIA, Esc-to-close, click-outside-to-close, and arrow-key
// navigation between items. It exists so a row of same-weight buttons (Display
// name / Edit unit / Group / Export …) can collapse into ONE secondary control
// beside the primary action, instead of competing with it for attention.
//
// `sections` is [{ label?, items: [{ key, label, hint?, onSelect, active? }] }].
// A section's label renders as a quiet group heading (and as the group's
// aria-label). An item that declares `active` is a TOGGLE — it renders as
// role="menuitemcheckbox" with aria-checked, which is the honest semantic for
// "Export metric" (its panel is either open or it isn't); items without it are
// plain menuitems that open a modal.
//
// Closing is unconditional here: every item is either a toggle or opens its own
// modal, so there is nothing unsaved for this component to guard.
//
// `icon` and `label` are independent: pass both for a normal button, or an icon with
// NO label for an icon-only trigger. In that icon-only mode `ariaLabel` is the
// control's ONLY name, so it is required — an icon button with no accessible name is
// unusable by screen reader; it's also set as `title` so a sighted user gets the same
// words on hover. `align="right"` anchors the popup to the trigger's right edge, for a
// trigger near the right of its container (a left-anchored popup would overflow).
export default function ActionMenu({ label, ariaLabel, icon, align = 'left', sections }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)
  const buttonRef = useRef(null)
  const menuRef = useRef(null)
  const menuId = useId()

  // Close when a pointer goes down anywhere outside. Bound on mousedown (not click) so
  // the trigger's own click can't immediately re-close what it opened. The popup is
  // PORTALLED, so it is not inside wrapRef — it has to be tested separately, or a click
  // on a menu item would unmount the item before its own click handler ran.
  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (wrapRef.current?.contains(e.target)) return
      if (menuRef.current?.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // A fixed-position popup can't follow its trigger, so any scroll (including the
  // rail's own) closes it rather than leaving it stranded mid-page. Capture phase, to
  // catch scrolling inside a container as well as the page.
  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open])

  // Fit the popup to the space it actually has: open UPWARD when there isn't room
  // below, and cap the height so it can scroll rather than run off-screen. This is
  // measurement, so it writes to the DOM node directly instead of through state — and
  // it matters most where the trigger sits in a STICKY column: there, scrolling the
  // page doesn't move the trigger, so anything past the viewport edge is unreachable
  // rather than merely below the fold.
  useLayoutEffect(() => {
    const menu = menuRef.current
    const button = buttonRef.current
    if (!open || !menu || !button) return
    const rect = button.getBoundingClientRect()
    const below = window.innerHeight - rect.bottom - EDGE_GAP * 2
    const above = rect.top - EDGE_GAP * 2
    const up = menu.scrollHeight > below && above > below
    menu.style.maxHeight = `${Math.max(140, Math.floor(up ? above : below))}px`
    // Horizontal anchor: to the trigger's left edge, or its right edge when the caller
    // asked for right alignment. Clamped so neither choice can leave the viewport.
    const width = menu.offsetWidth
    const left = align === 'right' ? rect.right - width : rect.left
    menu.style.left = `${Math.min(Math.max(EDGE_GAP, left), window.innerWidth - width - EDGE_GAP)}px`
    menu.style.top = up ? '' : `${rect.bottom + 6}px`
    menu.style.bottom = up ? `${window.innerHeight - rect.top + 6}px` : ''
  }, [open, align])

  // On open, focus the first item so the menu is usable from the keyboard.
  useEffect(() => {
    if (!open) return
    menuRef.current?.querySelector('[role^="menuitem"]')?.focus()
  }, [open])

  function closeAndRefocus() {
    setOpen(false)
    buttonRef.current?.focus()
  }

  // Arrow/Home/End move focus between items; Esc returns focus to the trigger.
  function onMenuKeyDown(e) {
    if (e.key === 'Escape') {
      e.stopPropagation() // don't also close a surrounding dialog
      closeAndRefocus()
      return
    }
    const items = [...(menuRef.current?.querySelectorAll('[role^="menuitem"]') ?? [])]
    if (items.length === 0) return
    const i = items.indexOf(document.activeElement)
    let next = null
    if (e.key === 'ArrowDown') next = items[(i + 1) % items.length]
    else if (e.key === 'ArrowUp') next = items[(i - 1 + items.length) % items.length]
    else if (e.key === 'Home') next = items[0]
    else if (e.key === 'End') next = items[items.length - 1]
    if (next) {
      e.preventDefault()
      next.focus()
    }
  }

  return (
    <div className="menu" ref={wrapRef}>
      <button
        type="button"
        ref={buttonRef}
        className={`menu__button${icon && !label ? ' menu__button--icon' : ''}${open ? ' menu__button--open' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={ariaLabel}
        title={icon ? ariaLabel || label : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && !open) {
            e.preventDefault()
            setOpen(true)
          }
        }}
      >
        {icon}
        {label}
      </button>

      {open && createPortal(
        <div
          className="menu__list"
          id={menuId}
          role="menu"
          aria-label={ariaLabel || label}
          ref={menuRef}
          onKeyDown={onMenuKeyDown}
        >
          {sections.map((section, si) => (
            <div
              key={section.label ?? `section-${si}`}
              className="menu__group"
              role="group"
              aria-label={section.label || undefined}
            >
              {section.label && (
                <p className="menu__group-label" aria-hidden="true">{section.label}</p>
              )}
              {section.items.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  role={item.active === undefined ? 'menuitem' : 'menuitemcheckbox'}
                  aria-checked={item.active === undefined ? undefined : !!item.active}
                  className={`menu__item${item.active ? ' menu__item--active' : ''}`}
                  onClick={() => {
                    setOpen(false)
                    item.onSelect()
                  }}
                >
                  <span className="menu__item-label">{item.label}</span>
                  {item.hint && <span className="menu__item-hint">{item.hint}</span>}
                </button>
              ))}
            </div>
          ))}
        </div>,
        document.body,
      )}
    </div>
  )
}
