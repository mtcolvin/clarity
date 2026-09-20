// jsdom environment for the smoke probe. Everything here exists to make a React 19 client
// render believe it's in a browser; nothing here is application code.
//
// FETCH POLICY (the load-bearing safety rule): the probe drives the REAL local backend so it
// sees the REAL response shapes — that is the whole point, since synthetic fixtures are
// exactly what let a shape-mismatch crash slip through. But it is **GET-ONLY**: any other
// method is refused with a 405 and recorded. A probe that clicks around a page must not be
// able to write to, or delete from, the medical database, and that guarantee lives here in
// one place rather than in a per-page list of "don't click this". Nothing is written to disk
// and nothing leaves the machine.
import { JSDOM } from 'jsdom'

export const blockedWrites = []

export function installDom({ url = 'http://localhost:5173/' } = {}) {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>',
                        { url, pretendToBeVisual: true })
  const { window } = dom

  globalThis.window = window
  globalThis.document = window.document
  // navigator/location are getter-only on globalThis in Node, so they need defineProperty.
  for (const key of ['navigator', 'location']) {
    Object.defineProperty(globalThis, key, { value: window[key], configurable: true })
  }
  for (const key of ['history', 'HTMLElement', 'HTMLCanvasElement', 'Element', 'Node', 'Event',
                     'MouseEvent', 'KeyboardEvent', 'CustomEvent', 'PointerEvent', 'DOMRect',
                     'getComputedStyle', 'Image', 'Blob', 'FileReader', 'File',
                     'requestAnimationFrame', 'cancelAnimationFrame']) {
    if (window[key]) globalThis[key] = window[key]
  }

  // --- jsdom gaps the app relies on -----------------------------------------------------
  const NoopObserver = class {
    observe() {} unobserve() {} disconnect() {} takeRecords() { return [] }
  }
  for (const name of ['ResizeObserver', 'IntersectionObserver', 'MutationObserver']) {
    if (!window[name]) window[name] = NoopObserver
    globalThis[name] = window[name]
  }
  if (!window.matchMedia) {
    window.matchMedia = (q) => ({
      matches: false, media: q, onchange: null,
      addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
      dispatchEvent() { return false },
    })
  }
  globalThis.matchMedia = window.matchMedia

  // jsdom ships no canvas backend, so getContext returns null and any draw call throws —
  // which would look like an app crash when it is purely a jsdom limitation. A permissive
  // fake context absorbs the draw calls instead. The probe checks that a page SURVIVES, not
  // that pixels are right (the imaging renderer's correctness is pinned server-side).
  const fakeCtx = new Proxy({ canvas: null }, {
    get(target, prop) {
      if (prop in target) return target[prop]
      if (prop === 'getImageData') return () => ({ data: new Uint8ClampedArray(4) })
      if (prop === 'measureText') return () => ({ width: 0 })
      return () => undefined
    },
    set(target, prop, value) { target[prop] = value; return true },
  })
  window.HTMLCanvasElement.prototype.getContext = function getContext() {
    fakeCtx.canvas = this
    return fakeCtx
  }
  globalThis.createImageBitmap = async () => ({ width: 1, height: 1, close() {} })
  if (!window.URL.createObjectURL) {
    window.URL.createObjectURL = () => 'blob:probe'
    window.URL.revokeObjectURL = () => {}
  }

  // --- the GET-only fetch gate ----------------------------------------------------------
  const realFetch = globalThis.fetch          // Node's own fetch, not jsdom's
  globalThis.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : (input?.url ?? String(input))
    const method = String(init.method || input?.method || 'GET').toUpperCase()
    if (method !== 'GET') {
      blockedWrites.push(`${method} ${url}`)
      return new Response(JSON.stringify({ detail: 'blocked: the smoke probe is GET-only' }),
                          { status: 405, headers: { 'content-type': 'application/json' } })
    }
    return realFetch(url, init)
  }
  window.fetch = globalThis.fetch

  return dom
}
