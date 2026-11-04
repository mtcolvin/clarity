import { useRef } from 'react'
import { InfoCircleIcon } from './icons'
import { clampToViewport } from './shell/viewportClamp'

// A small ⓘ that reveals `text` in a hover/focus tooltip — used to tuck a
// section's descriptive prose out of its header while keeping it discoverable.
// Keyboard-accessible: the trigger is a real <button> (focusable), and the
// bubble also shows on :focus-visible (see .hint CSS). Pure presentation, except that
// an open bubble is nudged back on screen when its icon sits near a narrow screen's edge.
export default function InfoHint({ text, label = 'What this section shows' }) {
  const bubble = useRef(null)
  // Clamp after the browser has applied the :hover/:focus styles that show the bubble.
  const show = () => requestAnimationFrame(() => clampToViewport(bubble.current))
  return (
    <span className="hint" onMouseEnter={show} onFocus={show}>
      <button type="button" className="hint__trigger" aria-label={label}>
        <InfoCircleIcon size={15} />
      </button>
      <span className="hint__bubble" role="tooltip" ref={bubble}>{text}</span>
    </span>
  )
}
