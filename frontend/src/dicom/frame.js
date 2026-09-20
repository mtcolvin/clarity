// Client-side windowing: turn one slice's pixel VALUES into greys, in the browser.
//
// The viewer used to fetch a windowed PNG per slice, which made every cached frame specific
// to one window — so changing window/level threw the whole series away and refetched it (a
// measured 9.4 s for a 984-slice series), and the preload had to be gated behind the drag to
// stop it starving the one frame you were waiting on. No conventional DICOM viewer has that
// problem: desktop viewers (RadiAnt, Horos, Weasis) and web ones (Cornerstone/OHIF) alike
// decode the pixel VALUES once and window them on the client as you drag. This is that.
//
// The arithmetic here MIRRORS dicom_store's `_apply_voi` / `_to_stored_units` exactly, and
// that duplication is the price of moving the work to the client. It is not left to
// vigilance: tests/test_frame_payload.py renders the same slice through both paths and
// requires the greys to agree, so a change to one side that isn't made to the other fails.

// The stored-integer types the payload can carry, with the offset that turns a value into a
// lookup index. i4/u4 are absent on purpose — a 4-billion-entry LUT is not a lookup table,
// and no modality here stores 32-bit pixels (the server declines those, and the viewer falls
// back to the server-rendered PNG).
const DTYPES = {
  i1: { ctor: Int8Array, lo: -128, size: 256 },
  u1: { ctor: Uint8Array, lo: 0, size: 256 },
  i2: { ctor: Int16Array, lo: -32768, size: 65536 },
  u2: { ctor: Uint16Array, lo: 0, size: 65536 },
}

// PS3.3 C.11.2.1. The DEFAULT (LINEAR) is defined over (w − 1) centred on (c − 0.5), NOT
// c ± w/2 — that is the separate LINEAR_EXACT function, and using it shifts every grey by
// up to 4 of 255 on a narrow window (the error scales as 1/w).
export function voiGrey(v, wc, ww, fn) {
  if (fn === 'SIGMOID') {
    return 255 / (1 + Math.exp((-4 * (v - wc)) / Math.max(ww, 1e-6)))
  }
  if (fn === 'LINEAR_EXACT') {
    const lo = wc - ww / 2
    const hi = wc + ww / 2
    return Math.min(Math.max((v - lo) / Math.max(hi - lo, 1e-6), 0), 1) * 255
  }
  const c = wc - 0.5
  const w = Math.max(ww - 1, 1e-6)
  return Math.min(Math.max((v - c) / w + 0.5, 0), 1) * 255
}

// Parse the server's self-describing blob:
//   [4-byte LE header length][UTF-8 JSON header][pixel bytes][packed out-of-field mask]
export function parseFrame(buffer) {
  const view = new DataView(buffer)
  const headerLen = view.getUint32(0, true)
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, headerLen)))
  const spec = DTYPES[header.dtype]
  if (!spec) throw new Error(`unsupported pixel type ${header.dtype}`)

  const count = header.rows * header.cols
  const pixels = new spec.ctor(buffer, 4 + headerLen, count)
  const maskOffset = 4 + headerLen + count * spec.ctor.BYTES_PER_ELEMENT
  const mask = header.masked
    ? new Uint8Array(buffer, maskOffset, Math.ceil(count / 8))
    : null
  return { ...header, spec, pixels, mask }
}

// One Uint8 grey per POSSIBLE stored value. This is what makes a window/level drag cheap:
// 65 536 evaluations of the VOI function once, then a table lookup per pixel — rather than
// the function itself 262 144 times per frame.
//
// Cached one deep, because the table depends on the WINDOW and the file's rescale, not on
// which slice you are looking at: every frame in a series shares it. Rebuilding per frame
// cost 0.29 ms each (measured) — small, but it is pure waste at 20 frames a second, and a
// single-entry cache is the whole fix since the window only changes when the user moves it.
let lutCache = null
let lutKey = ''

function buildLut(frame, wc, ww) {
  const { spec } = frame
  const key = `${frame.dtype}|${frame.slope}|${frame.intercept}|${frame.voi}|${frame.invert}|${wc}|${ww}`
  if (lutKey === key && lutCache) return lutCache
  const lut = new Uint8ClampedArray(spec.size)
  for (let i = 0; i < spec.size; i++) {
    const value = (spec.lo + i) * frame.slope + frame.intercept
    const grey = voiGrey(value, wc, ww, frame.voi)
    // MONOCHROME1 means the minimum sample is WHITE; invert for normal display. Applied
    // before the mask, so out-of-field stays black either way — it isn't image data.
    lut[i] = frame.invert ? 255 - grey : grey
  }
  lutCache = lut
  lutKey = key
  return lut
}

// The RGBA buffer is reused per canvas size for the same reason: a 512² frame is a 1 MB
// allocation, and 20 of them a second is garbage the collector has to chase mid-playback.
// Made through the CONTEXT (`createImageData`) rather than the global `ImageData`
// constructor: the constructor is a browser global that a headless environment need not
// have — the smoke probe runs the real pages in jsdom, where it doesn't exist — while
// `createImageData` is part of the 2D context we already require.
let imageCache = null
let imageKey = ''

function imageFor(ctx, cols, rows) {
  const key = `${cols}x${rows}`
  if (imageKey !== key || !imageCache) {
    imageCache = ctx.createImageData(cols, rows)
    imageKey = key
  }
  return imageCache
}

// Draw a parsed frame into a canvas at the given window. Returns nothing; the canvas is
// resized to the frame's own pixel dimensions, which is what keeps its BOX equal to the
// image's box (every pointer mapping on the imaging page depends on that).
export function renderFrame(canvas, frame, wc, ww) {
  const { rows, cols, pixels, mask, spec } = frame
  if (canvas.width !== cols || canvas.height !== rows) {
    canvas.width = cols
    canvas.height = rows
  }
  // `getContext` genuinely returns null where 2D canvas isn't available (a headless
  // environment, or too many live contexts). Nothing to draw on is not an error worth
  // taking the page down for.
  // A 2D context can be genuinely absent (a headless environment, or too many live
  // contexts), and a stub one can hand back nothing usable — jsdom, which the smoke probe
  // runs the real pages in, returns a context whose createImageData yields undefined.
  // Nothing to draw on is not an error worth taking the page down for.
  const ctx = canvas.getContext('2d')
  const image = ctx && imageFor(ctx, cols, rows)
  if (!image?.data) return
  const lut = buildLut(frame, wc, ww)
  const rgba = image.data
  for (let i = 0, j = 0; i < pixels.length; i++, j += 4) {
    // np.packbits is MSB-first within each byte, so pixel i is bit (7 - i % 8).
    const padded = mask && (mask[i >> 3] >> (7 - (i & 7))) & 1
    const grey = padded ? 0 : lut[pixels[i] - spec.lo]
    rgba[j] = grey
    rgba[j + 1] = grey
    rgba[j + 2] = grey
    rgba[j + 3] = 255
  }
  ctx.putImageData(image, 0, 0)
}
