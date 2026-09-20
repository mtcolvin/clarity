import { useEffect, useRef } from 'react'

// A custom, dependency-free modal, mirroring the proven NavDrawer accessibility
// pattern: role="dialog" aria-modal, Esc-to-close (bound only while open), focus
// moved inside on open, backdrop-click closes, and a × close button. Two extras
// beyond the drawer: the body scroll is locked while open (so the dimmed page
// behind doesn't scroll), and the panel is top-anchored (not centered) with an
// internal scroll, sitting above the sticky app header.
//
// `onClose` is the single close channel — the parent decides what closing means
// (e.g. guard on unsaved changes), so this component never blocks a close itself.
export default function Modal({ open, onClose, title, children }) {
  const panelRef = useRef(null)

  // Esc-to-close, bound only while open.
  useEffect(() => {
    if (!open) return
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Lock body scroll while open, restoring whatever it was before.
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  // On open, move focus to the first ENABLED field in the body (so keyboard users
  // land on the first input, not a locked one and not the header's × button).
  // Falls back to the close button if the body has no focusable field.
  useEffect(() => {
    if (!open) return
    const fieldSel =
      'input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
    const body = panelRef.current?.querySelector('.modal__body')
    const target = body?.querySelector(fieldSel) || panelRef.current?.querySelector('.modal__close')
    target?.focus()
  }, [open])

  if (!open) return null

  return (
    <>
      <div className="modal-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="modal-wrap">
        <div
          className="modal"
          role="dialog"
          aria-modal="true"
          aria-label={title}
          ref={panelRef}
        >
          <div className="modal__header">
            <h2 className="modal__title">{title}</h2>
            <button
              type="button"
              className="modal__close"
              onClick={onClose}
              aria-label="Close"
            >
              ×
            </button>
          </div>
          <div className="modal__body">{children}</div>
        </div>
      </div>
    </>
  )
}
