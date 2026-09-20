// Minimal Markdown renderer for MODEL OUTPUT (the export handoff's response).
//
// Why hand-rolled instead of react-markdown: this renders text that came back from an
// external model into the user's page, and the safest possible renderer is one that
// CANNOT emit HTML at all. Everything below builds React elements — there is no
// dangerouslySetInnerHTML, no HTML parsing step, and no way for markup in the model's
// text to become live DOM. It also keeps a medical app's dependency tree at the four
// runtime packages it has today.
//
// Scope is deliberately the subset models actually emit in prose: headings, bold,
// inline code, bullet and numbered lists, and paragraphs. Anything unrecognized falls
// through as plain text rather than being mangled — an unsupported construct should
// look like what the model wrote, never disappear.
//
// NOT supported on purpose: `_italic_`. This app's own field names are snake_case
// (ref_low, personal_baseline_mean, n_readings) and appear verbatim in model output, so
// underscore-italics would corrupt real content. Asterisk italics (*word*) are safe and
// are supported.

// Inline spans, longest-delimiter-first so ** is consumed before *.
const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g

function renderInline(text, keyPrefix) {
  return text.split(INLINE).filter(Boolean).map((piece, i) => {
    const key = `${keyPrefix}-${i}`
    if (piece.startsWith('**') && piece.endsWith('**') && piece.length > 4) {
      return <strong key={key}>{piece.slice(2, -2)}</strong>
    }
    if (piece.startsWith('*') && piece.endsWith('*') && piece.length > 2) {
      return <em key={key}>{piece.slice(1, -1)}</em>
    }
    if (piece.startsWith('`') && piece.endsWith('`') && piece.length > 2) {
      return <code key={key}>{piece.slice(1, -1)}</code>
    }
    return piece
  })
}

const HEADING = /^(#{1,4})\s+(.*)$/
const BULLET = /^\s*[-*+]\s+(.*)$/
const ORDERED = /^\s*\d+[.)]\s+(.*)$/

// Group lines into blocks, then render each. A blank line always closes the open block;
// a list continues across consecutive item lines so one <ul> holds all its items.
export function Markdown({ text }) {
  if (!text) return null
  const lines = String(text).replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let para = []
  let list = null // { ordered: bool, items: [string] }

  const flushPara = () => {
    if (para.length) { blocks.push({ type: 'p', text: para.join(' ') }); para = [] }
  }
  const flushList = () => {
    if (list) { blocks.push({ type: 'list', ...list }); list = null }
  }
  const flushAll = () => { flushPara(); flushList() }

  for (const line of lines) {
    if (!line.trim()) { flushAll(); continue }

    const heading = HEADING.exec(line)
    if (heading) {
      flushAll()
      blocks.push({ type: 'h', level: heading[1].length, text: heading[2] })
      continue
    }

    const bullet = BULLET.exec(line)
    const ordered = ORDERED.exec(line)
    if (bullet || ordered) {
      flushPara()
      const isOrdered = Boolean(ordered)
      // A change of list type starts a new list rather than mixing markers.
      if (list && list.ordered !== isOrdered) flushList()
      if (!list) list = { ordered: isOrdered, items: [] }
      list.items.push((bullet || ordered)[1])
      continue
    }

    flushList()
    para.push(line.trim())
  }
  flushAll()

  return (
    <>
      {blocks.map((b, i) => {
        if (b.type === 'h') {
          // Clamp to h3..h5: this renders INSIDE a page that owns h1/h2, so a model
          // writing "# Summary" must not outrank the app's own headings.
          const Tag = `h${Math.min(5, b.level + 2)}`
          return <Tag key={i} className="md__h">{renderInline(b.text, `h${i}`)}</Tag>
        }
        if (b.type === 'list') {
          const Tag = b.ordered ? 'ol' : 'ul'
          return (
            <Tag key={i} className="md__list">
              {b.items.map((item, j) => (
                <li key={j}>{renderInline(item, `l${i}-${j}`)}</li>
              ))}
            </Tag>
          )
        }
        return <p key={i} className="md__p">{renderInline(b.text, `p${i}`)}</p>
      })}
    </>
  )
}

export default Markdown
