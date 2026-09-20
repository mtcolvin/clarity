import { InfoCircleIcon } from './icons'

// A small ⓘ that reveals `text` in a hover/focus tooltip — used to tuck a
// section's descriptive prose out of its header while keeping it discoverable.
// Keyboard-accessible: the trigger is a real <button> (focusable), and the
// bubble also shows on :focus-visible (see .hint CSS). Pure presentation.
export default function InfoHint({ text, label = 'What this section shows' }) {
  return (
    <span className="hint">
      <button type="button" className="hint__trigger" aria-label={label}>
        <InfoCircleIcon size={15} />
      </button>
      <span className="hint__bubble" role="tooltip">{text}</span>
    </span>
  )
}
