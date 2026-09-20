import { useEffect, useRef, useState } from 'react'
import { CloseIcon, SearchIcon } from '../icons'

// The app's collapsing search control: a magnifier that expands into a field. This is the
// ONLY search control in the app — the Documents page's inline copy was folded into it,
// because two implementations of one affordance drift, and the drift showed up as two
// slightly different Escape behaviours (one cleared the picked document, the other didn't).
//
// Collapsed by default on purpose: search here is occasional, and a list you can read is
// browsable without it. Escape and the toggle both close AND clear — a live filter hiding
// behind a collapsed icon would leave you looking at a short list with no visible reason.
//
// ONE BUTTON, TWO GLYPHS. The magnifier BECOMES a cross when the field opens; there is no
// separate × beside it. A dedicated close button meant two controls sitting side by side
// doing the same job (the magnifier was already the toggle in both directions), and the
// cross is what the button MEANS once the field is open. Both icons are always rendered,
// stacked in the same box and cross-faded with a quarter turn — one glyph swapped for
// another cannot be animated, for the same reason the expansion itself couldn't be until
// the whole control stopped unmounting its own parts.
//
// EVERY PART IS ALWAYS MOUNTED, and open/closed is a class on the wrapper. That is what
// makes the expansion animatable: the first version swapped one subtree (a button) for
// another (a field), and there is nothing to transition between two different elements.
// The cost is that the collapsed field must be taken out of the tab order and the
// accessibility tree by hand — hence tabIndex/aria-hidden below, rather than the
// unmounting that used to do it for free.
//
// `count` is rendered verbatim when open (e.g. "3 matches", "Searching…", "No matches"),
// so each caller phrases its own result line; this component never counts anything.
// `onOpenChange` lets a caller react to the expansion — Documents hides its type filter
// while searching, since relevance order has replaced type order.
export default function SearchField({
  value, onChange, placeholder, label, count = null, onOpenChange,
}) {
  const [open, setOpen] = useState(false)
  const inputRef = useRef(null)

  // Focus on expand. `autoFocus` can't do it any more: the input is mounted the whole
  // time, so there is no mount for it to fire on.
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  function set(next) {
    setOpen(next)
    onOpenChange?.(next)
  }

  function close() {
    set(false)
    onChange('')
  }

  return (
    <div className={`searchfield${open ? ' searchfield--open' : ''}`}>
      <button
        type="button"
        className="searchfield__toggle"
        onClick={() => (open ? close() : set(true))}
        aria-label={open ? 'Close search' : label}
        aria-expanded={open}
        title={open ? 'Close search' : label}
      >
        <span className="searchfield__glyph searchfield__glyph--search">
          <SearchIcon size={16} />
        </span>
        <span className="searchfield__glyph searchfield__glyph--close">
          <CloseIcon size={16} />
        </span>
      </button>

      <input
        ref={inputRef}
        type="search"
        className="searchfield__input"
        value={value}
        placeholder={placeholder}
        aria-label={label}
        aria-hidden={!open}
        tabIndex={open ? 0 : -1}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Escape') close() }}
      />

      <span className="searchfield__count muted small" aria-hidden={!open}>
        {open ? count : null}
      </span>
    </div>
  )
}
