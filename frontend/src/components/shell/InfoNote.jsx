import { useRef } from 'react'
import { InfoCircleIcon } from '../icons'
import { clampToViewport } from './viewportClamp'

// The ⓘ privacy note beside the Imaging and Documents titles: focusable, shows its text
// on hover/focus, and keeps that text on screen near a narrow screen's edge. `prefix`
// selects the page's own classes (`dcm` / `docs`), which share their styling in App.css.
export default function InfoNote({ prefix, label = 'Privacy note', children }) {
  const bubble = useRef(null)
  // Clamp after the browser has applied the :hover/:focus styles that show the bubble.
  const show = () => requestAnimationFrame(() => clampToViewport(bubble.current))
  return (
    <span className={`${prefix}__info`} tabIndex={0} role="note" aria-label={label}
          onMouseEnter={show} onFocus={show}>
      <InfoCircleIcon size={16} />
      <span className={`${prefix}__info-bubble`} ref={bubble}>{children}</span>
    </span>
  )
}
