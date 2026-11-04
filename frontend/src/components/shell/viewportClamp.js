// Keep an open tooltip bubble on screen.
//
// The info bubbles are anchored to their icon's LEFT edge, which is right on a desktop
// and wrong on a phone: an icon near the right of a narrow screen pushes its bubble off
// the edge, cutting the text off. Call this once the bubble is showing (hover/focus) and
// it nudges the bubble left by exactly the overflow, never past the left margin either.
// `translate` rather than `transform`, so it can't clobber a transform the CSS sets.
export function clampToViewport(el, margin = 8) {
  if (!el) return
  el.style.translate = ''
  const r = el.getBoundingClientRect()
  if (!r.width) return                       // not showing (display: none)
  const vw = document.documentElement.clientWidth
  let dx = 0
  if (r.right > vw - margin) dx = vw - margin - r.right
  if (r.left + dx < margin) dx = margin - r.left
  if (dx) el.style.translate = `${Math.round(dx)}px 0`
}
