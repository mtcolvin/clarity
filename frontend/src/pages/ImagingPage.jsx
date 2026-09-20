import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getImagingStudies, getImagingRoi, imagingSliceUrl, imagingFrameUrl } from '../api'
import { parseFrame, renderFrame } from '../dicom/frame'
import {
  PlayIcon, PauseIcon, DistanceIcon, AngleIcon, RegionIcon, InfoCircleIcon, MenuIcon,
  ExpandIcon, ContractIcon,
} from '../components/icons'
import Loading from '../components/shell/Loading'

// Local DICOM viewer. Everything here is on-machine: the backend reads a local imaging
// folder, surfaces ONLY allowlisted metadata (no patient/physician/facility PII), and
// renders each slice to PNG on the server. Nothing is uploaded and nothing reaches the
// gateway — see dicom_store.py's header for the privacy posture.

// Slice prefetch. Both imaging routes send Cache-Control: no-store on purpose (a medical
// image — rendered or raw — must not linger in the browser's disk cache), so smooth
// scrubbing CANNOT rely on HTTP caching; frames live in an in-memory Map that dies with the
// page.
//
// What is cached is now the PIXEL VALUES, not a windowed picture, and that one change
// deleted a whole apparatus. Before: every cached blob was specific to one window, so each
// window/level step threw the entire series away and refetched it (measured 9.4 s for a
// 984-slice series), which is why the preload had to be GATED behind the drag, why the drag
// was throttled to ~22 updates/s, and why the cache was cleared on `winKey`. None of that
// exists now — a window change is a redraw of bytes already here.
// A frame's PIXEL VALUES, not a picture: ~544 KB for a 512² slice (measured on this
// record's thin-slice bone series) against ~70 KB as PNG. So the cache is bounded by BYTES
// rather than by a frame count, which would mean 50 MB for one series and 8 MB for another.
//
// 320 MB is chosen so the LARGEST series here fits WHOLE — 406 slices × 544 KB = 226 MB —
// which is what makes a cine loop play entirely from memory after one pass instead of
// evicting the frames it is about to come back to.
const FRAME_BUDGET_BYTES = 320 * 1024 * 1024
const PREFETCH_AHEAD = 24     // each side of the cursor while scrubbing
// Forward-only, and deeper: at 20 slices/s a 24-frame buffer is 1.2 s, which one slow fetch
// can eat. 64 is ~3 s of playback ahead of the cursor.
const PREFETCH_PLAYING = 64
// The prefetch re-arms per CHUNK of the stack rather than per slice — see the effect.
const PREFETCH_CHUNK = 8
const PRELOAD_CONCURRENCY = 6 // parallel fetches; the backend reads these one-ish at a time
const PRELOAD_DEBOUNCE_MS = 120 // let a fast scrub settle before fetching its neighbours
const DECODE_HINT = 'This slice could not be decoded. Compressed DICOM needs an optional '
  + 'decoder: pip install pylibjpeg pylibjpeg-openjpeg'
const WL_SENSITIVITY = 4      // HU per pixel dragged
// A W/L step is now a LOCAL redraw — rebuild a 65 536-entry lookup table, map 262 144
// pixels — so the throttle exists only to stay off the compositor's toes rather than to
// ration server renders. One frame at 60 Hz. It used to be 45 ms (~22/s) because each step
// cost a server round-trip of 18–20 ms, and before that 70 ms; the number kept shrinking as
// the real cost was found, and this is the end of that road — there is no round-trip left.
const WL_THROTTLE_MS = 16
// Playback rate (slices/second), user-adjustable. Once a series is preloaded these all
// run off local frames; the practical ceiling is the browser's repaint rate, and Chrome
// throttles the timer anyway when the tab isn't focused.
const CINE_FPS_DEFAULT = 20
const CINE_SPEEDS = [5, 10, 20, 30, 60]
const ZOOM_MIN = 1
const ZOOM_MAX = 8
const ZOOM_STEP = 1.25

// Each study is a native <details>, COLLAPSED by default: six studies carrying 94 series
// between them turned the picker into a long scroll where finding a date meant hunting past
// dozens of series buttons. Collapsed, the sidebar is a six-line index of the whole library.
// Native disclosure (not a custom button) inherits the site-wide chevron and keyboard
// behaviour for free.
function StudyList({ studies, selectedSeriesId, onPick }) {
  // Only studies the user has TOGGLED are recorded; anything absent falls back to the
  // default below. So a user's explicit collapse always wins over the auto-open.
  const [toggled, setToggled] = useState({})
  const navigate = useNavigate()

  return (
    <div className="dcm__studies">
      {studies.map((st) => {
        // The study holding the current selection opens itself, so the sidebar always shows
        // what the stage is displaying — a timeline deep link (/imaging?study=<id>) selects
        // a series before the user has opened anything, and a hidden selection reads as a
        // picker showing nothing while an image is up.
        const holdsSelection = st.series.some((s) => s.id === selectedSeriesId)
        const slices = st.series.reduce((n, s) => n + s.n_slices, 0)
        return (
          <details
            key={st.id}
            className="dcm__study"
            open={toggled[st.id] ?? holdsSelection}
            // Read `open` SYNCHRONOUSLY: React nulls the event's currentTarget once the
            // handler returns, and a state UPDATER function runs later (StrictMode always
            // defers it), so touching e.currentTarget inside the updater throws and takes
            // the whole page down. Capture the value first, close over the value.
            onToggle={(e) => {
              const isOpen = e.currentTarget.open
              setToggled((t) => ({ ...t, [st.id]: isOpen }))
            }}
          >
            <summary className="dcm__study-head">
              <span className="dcm__study-date">{st.StudyDate || 'Undated'}</span>
              {st.StudyDescription && <span className="dcm__study-desc">{st.StudyDescription}</span>}
              {/* Collapsed, this line is all the user has to judge a study by — worth the
                  row it costs. */}
              <span className="dcm__study-count">
                {st.series.length} series · {slices.toLocaleString()} images
              </span>
            </summary>
            {/* The radiologist's written report for this exam, if the disc carried one. It
                interprets these exact images and exists nowhere in the DICOM, so the link
                belongs next to them rather than only on the Documents page. */}
            {st.report_ids?.length > 0 && (
              <button type="button" className="dcm__report-link"
                      onClick={() => navigate(`/documents?report=${st.report_ids[0]}`)}>
                Read the radiology report
              </button>
            )}
            <ul className="dcm__series-list">
              {st.series.map((s) => (
                <li key={s.id}>
                  {/* Picking a series pins its study open, so a study the user has actually
                      worked in doesn't collapse itself later when the selection moves
                      elsewhere — which is what the auto-open above would otherwise do. */}
                  <button
                    type="button"
                    className={`dcm__series${s.id === selectedSeriesId ? ' dcm__series--on' : ''}`}
                    onClick={() => { setToggled((t) => ({ ...t, [st.id]: true })); onPick(s) }}
                  >
                    <span className="dcm__series-modality">{s.Modality || '—'}</span>
                    <span className="dcm__series-desc">
                      {s.SeriesDescription || s.BodyPartExamined || `Series ${s.SeriesNumber ?? ''}`}
                    </span>
                    <span className="dcm__series-count muted small">{s.n_slices} img</span>
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )
      })}
    </div>
  )
}

// --- measurement geometry (plain arithmetic on the file's own calibration) -------------
// PixelSpacing is [row_mm, col_mm]: row spacing scales Y, column spacing scales X. Points
// are converted to millimetre space FIRST so both distance and angle are correct even for
// non-square pixels (rare, but silently wrong if ignored).
function toMm(p, pixelSpacing) {
  if (!pixelSpacing) return p
  return { x: p.x * pixelSpacing[1], y: p.y * pixelSpacing[0] }
}

function distanceLabel(a, b, pixelSpacing) {
  const A = toMm(a, pixelSpacing)
  const B = toMm(b, pixelSpacing)
  const d = Math.hypot(B.x - A.x, B.y - A.y)
  if (!pixelSpacing) return `${d.toFixed(0)} px (uncalibrated)`
  return d >= 100 ? `${(d / 10).toFixed(1)} cm` : `${d.toFixed(1)} mm`
}

// Angle at the MIDDLE point (the vertex), between the rays to the other two.
function angleLabel(a, vertex, c, pixelSpacing) {
  const A = toMm(a, pixelSpacing)
  const V = toMm(vertex, pixelSpacing)
  const C = toMm(c, pixelSpacing)
  const v1 = { x: A.x - V.x, y: A.y - V.y }
  const v2 = { x: C.x - V.x, y: C.y - V.y }
  const m1 = Math.hypot(v1.x, v1.y)
  const m2 = Math.hypot(v2.x, v2.y)
  if (!m1 || !m2) return null
  const cos = Math.max(-1, Math.min(1, (v1.x * v2.x + v1.y * v2.y) / (m1 * m2)))
  return `${((Math.acos(cos) * 180) / Math.PI).toFixed(1)}°`
}

const POINTS_NEEDED = { distance: 2, angle: 3 }
const IDENTITY_VIEW = { zoom: 1, tx: 0, ty: 0 }
// Tools are icon-only (name in the tooltip + aria-label) and window presets get short
// labels, so the whole control set fits ONE row — a wrapping toolbar would change the
// column height and resize the image, which is the thing we just fixed.
const TOOL_ICONS = { distance: DistanceIcon, angle: AngleIcon, roi: RegionIcon }
const TOOL_NAMES = { distance: 'Distance', angle: 'Angle', roi: 'Region' }
// Short labels + a plain-language tooltip: a preset is a window/level pair tuned to make
// one tissue type readable, and the names alone don't say that.
const PRESET_LABELS = { 'soft-tissue': 'Soft', brain: 'Brain', bone: 'Bone', lung: 'Lung' }
const PRESET_HINTS = {
  brain: 'Brain — narrow window; separates grey and white matter',
  'soft-tissue': 'Soft tissue — organs, muscle, fat, fluid',
  bone: 'Bone — wide window; cortical detail and fractures',
  lung: 'Lung — air-filled tissue and lung markings',
}

function Viewer({ series, presets, presetsUnits }) {
  const [index, setIndex] = useState(0)
  const [win, setWin] = useState(null)      // { wc, ww } | null = the file's own default
  const [mode, setMode] = useState('off')   // 'off' | 'distance' | 'angle' | 'roi'
  const [points, setPoints] = useState([])
  const [rect, setRect] = useState(null)    // ROI rectangle in image-pixel coords
  const [roi, setRoi] = useState(null)      // fetched statistics for `rect`
  const [view, setView] = useState(IDENTITY_VIEW)   // zoom + pan
  const [playing, setPlaying] = useState(false)
  const [fps, setFps] = useState(CINE_FPS_DEFAULT)
  const [decodeError, setDecodeError] = useState(null)
  const [preload, setPreload] = useState(null)   // { done, total } while filling the cache
  const stageRef = useRef(null)
  const frameRef = useRef(null)
  const canvasRef = useRef(null)
  // FULLSCREEN, on the INSTRUMENT rather than the page: every control you need while
  // reading — slider, tools, presets, W/L — lives inside that unit, so it is the whole
  // viewer. The studies drawer is deliberately outside it; changing series is a different
  // act from looking at one, and it is one keystroke away.
  //
  // `document.fullscreenElement` is the source of truth, not our own boolean: the user can
  // leave with Escape or the browser's own chrome without going through this button, and a
  // state that only WE update would then say "fullscreen" over a windowed viewer.
  const [isFullscreen, setIsFullscreen] = useState(false)
  const instrumentRef = useRef(null)
  const [frameDefault, setFrameDefault] = useState(null)  // the window the frame declares
  const framesRef = useRef(new Map())       // index -> { ready, frame | img, bytes }
  const dragRef = useRef(null)              // in-flight window/level drag
  const panRef = useRef(null)               // in-flight pan drag
  const roiDragRef = useRef(null)           // in-flight ROI rectangle drag
  const lastWlRef = useRef(0)

  const last = Math.max(series.n_slices - 1, 0)
  // Which BLOCK of the stack the cursor is in. The prefetch keys off this, not off `index`,
  // so a running cine can't re-arm it out of existence (see that effect).
  const chunk = Math.floor(index / PREFETCH_CHUNK)
  // The presets are Hounsfield-unit windows, so they only mean anything on a series whose
  // values ARE Hounsfield (i.e. CT). On MR — whose signal is arbitrary and sequence-
  // dependent — a "bone 500/2000" window renders a near-black frame while implying a
  // calibration that doesn't exist, so they're hidden rather than shown-and-broken.
  const presetsApply = !presetsUnits || series.value_units === presetsUnits
  const usablePresets = presetsApply ? presets : {}
  // What the window controls actually resolve to right now — the explicit choice, else
  // the file's own calibration, else a mid-grey CT default so dragging has a sane origin.
  // What the window controls actually resolve to right now. `frameDefault` is the window
  // the FRAME declares — the file's own, or one derived from its data when it declares
  // none — and it outranks the series-level tag because it is what the server itself would
  // have rendered with. That mattered immediately: the fallback below is a mid-grey CT
  // guess, and on a series with no declared window the viewer used to SHOW "W 400 · L 40"
  // while the server rendered the data-derived window instead. The readout was describing a
  // window nothing had been drawn at. Now one number governs both.
  const effWin = win || frameDefault || series.default_window || { wc: 40, ww: 400 }

  // Reset per series.
  useEffect(() => {
    setIndex(0); setWin(null); setFrameDefault(null); setMode('off'); setPoints([])
    setRect(null); setRoi(null); setView(IDENTITY_VIEW); setPlaying(false)
  }, [series.id])
  // A measurement belongs to ONE slice — a line or ROI left hovering over different anatomy
  // would misrepresent it — so annotations clear on any slice change, and on mode change.
  // Written as no-op-when-already-empty updaters ON PURPOSE. `setPoints([])` with a fresh
  // array always changes the reference, so this effect used to force a SECOND render pass
  // on every slice change — during cine, two renders per frame at 20/s for nothing, since
  // there is almost never an annotation to clear.
  useEffect(() => {
    setPoints((p) => (p.length ? [] : p))
    setRect((r) => (r ? null : r))
    setRoi((r) => (r ? null : r))
  }, [index, mode])

  const toggleFullscreen = useCallback(() => {
    const el = instrumentRef.current
    if (!el?.requestFullscreen) return
    if (document.fullscreenElement) document.exitFullscreen()
    else el.requestFullscreen().catch(() => { /* denied — leave the viewer as it was */ })
  }, [])

  useEffect(() => {
    const sync = () => setIsFullscreen(document.fullscreenElement === instrumentRef.current)
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])

  // Cine playback: auto-advance, looping, driven by requestAnimationFrame against a clock
  // rather than by setInterval.
  //
  // setInterval was the wrong instrument for this. Its callbacks are COALESCED under load
  // and it accumulates drift, so at 20/s the gaps came out uneven — which reads as stutter
  // even when every frame is present and the draw costs ~1 ms (measured). rAF is already
  // synchronised to the compositor, so advancing on it means each frame is painted in a
  // frame the browser was going to draw anyway.
  //
  // `next` is carried FORWARD rather than reset each tick, so a display that can't keep up
  // drops a slice instead of slowing the whole loop down; and it is clamped to one interval
  // behind, so returning to a backgrounded tab doesn't fast-forward through the stack to
  // catch up on time nobody was watching.
  useEffect(() => {
    if (!playing || last === 0) return undefined
    const step = 1000 / fps
    let raf = 0
    let next = performance.now() + step
    const tick = (now) => {
      raf = requestAnimationFrame(tick)
      if (now < next) return
      next = Math.max(next + step, now - step)
      setIndex((i) => (i >= last ? 0 : i + 1))
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, last, fps])

  // ROI statistics come from the SERVER: the client only has a windowed PNG, which has lost
  // the real pixel values — a mean computed from display grey would be a fiction. Fetched
  // once per completed rectangle.
  useEffect(() => {
    if (!rect || rect.w < 2 || rect.h < 2) { setRoi(null); return undefined }
    let cancelled = false
    getImagingRoi(series.id, index, rect)
      .then((r) => !cancelled && setRoi(r))
      .catch(() => !cancelled && setRoi(null))
    return () => { cancelled = true }
  }, [rect, series.id, index])

  // Load (or reuse) one slice's PIXEL VALUES. A cached frame is window-INDEPENDENT, which
  // is the whole point of the change: dragging window/level re-renders from memory instead
  // of refetching a differently-windowed picture. Colour slices (and any pixel width the
  // frame route declines) answer 404, and fall back to the server-rendered PNG — window/
  // level is a grayscale concept, so there is nothing to window there anyway.
  const loadFrame = useCallback((i) => {
    if (i < 0 || i > last) return null
    const cache = framesRef.current
    const hit = cache.get(i)
    if (hit) return hit
    const entry = { bytes: 0, frame: null, img: null, failed: false }
    entry.ready = (async () => {
      const res = await fetch(imagingFrameUrl(series.id, i))
      if (res.status === 404) {
        // Not a grayscale frame — let the PNG route draw it.
        const img = new Image()
        img.decoding = 'async'
        // No window params: the fallback exists for COLOUR slices, where window/level
        // does not apply and the server ignores them anyway.
        img.src = imagingSliceUrl(series.id, i)
        entry.img = img
        // AWAIT THE DECODE. `ready` is what the prefetch waits on, and resolving here the
        // moment src was assigned made a prefetched fallback frame complete instantly
        // without having fetched anything — so playback over a fallback series fetched
        // every frame on demand and stuttered, while the progress bar said it was warm.
        await img.decode().catch(() => { /* the draw path reports the failure */ })
        return entry
      }
      if (!res.ok) throw new Error(String(res.status))
      const buf = await res.arrayBuffer()
      entry.frame = parseFrame(buf)
      entry.bytes = buf.byteLength
      return entry
    })().catch((e) => { entry.failed = e; return entry })
    cache.set(i, entry)
    return entry
  }, [series.id, last])

  // Zoom about a fixed screen point (the cursor), so the anatomy under the pointer stays
  // put. With transform-origin at the element centre, a point p in local coords sits at
  // t + z·p; holding it fixed while z→z' means t' = t + p·(z − z').
  function zoomAt(clientX, clientY, factor) {
    setView((v) => {
      const z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v.zoom * factor))
      if (z === v.zoom) return v
      const el = frameRef.current
      if (!el) return { ...v, zoom: z }
      const r = el.getBoundingClientRect()
      const px = (clientX - (r.left + r.width / 2)) / v.zoom
      const py = (clientY - (r.top + r.height / 2)) / v.zoom
      const next = { zoom: z, tx: v.tx + px * (v.zoom - z), ty: v.ty + py * (v.zoom - z) }
      return z === ZOOM_MIN ? IDENTITY_VIEW : next   // fully zoomed out re-centres
    })
  }

  // Evict by DISTANCE from the cursor, under a BYTE budget rather than a frame count: raw
  // values are ~512 KB for a 512² slice against ~70 KB as PNG, so "96 frames" would mean
  // 50 MB for one series and 8 MB for another. The budget is what keeps a 984-slice study
  // from holding half a gigabyte of pixels.
  const evictFarFrom = useCallback((center) => {
    const cache = framesRef.current
    let total = 0
    for (const e of cache.values()) total += e.bytes
    if (total <= FRAME_BUDGET_BYTES) return
    const byDistance = [...cache.keys()].sort((a, b) => Math.abs(b - center) - Math.abs(a - center))
    for (const k of byDistance) {
      if (total <= FRAME_BUDGET_BYTES) break
      const e = cache.get(k)
      if (k === center) continue
      total -= e.bytes
      cache.delete(k)
    }
  }, [])

  // Drop the cache when the SERIES changes — and only then. It used to clear on every
  // window change too, which is exactly the cost this rewrite removes.
  useEffect(() => {
    const cache = framesRef.current
    return () => cache.clear()
  }, [series.id])

  // Prefetch, bounded by the same byte budget. The whole-series preload this replaces
  // existed because each frame cost a server render; now a frame is fetched once and
  // re-windowed for free, so what matters is having the frames you are ABOUT TO NEED, not
  // the whole stack. It also no longer has to be gated behind the window/level drag — the
  // drag doesn't invalidate anything now.
  //
  // Two things this has to get right, both learned from a stuttering cine on a thin-slice
  // bone series:
  //
  // 1. IT MUST NOT BE RE-DEBOUNCED BY THE CURSOR. Keyed on `index` with a debounce, a
  //    running cine (a new index every 50 ms at 20/s) cleared the timer before it ever
  //    fired, so playback prefetched NOTHING and every frame was fetched on demand. It is
  //    keyed on a CHUNK of the stack instead, so it re-arms a few times a second at most
  //    however fast the cursor moves.
  // 2. IT MUST FOLLOW THE DIRECTION OF TRAVEL. Scrubbing wants both neighbours; playback
  //    only ever goes forward, and spending half the workers behind the cursor halves the
  //    depth of the buffer that actually matters. Cine also WRAPS, so the last frames
  //    prefetch the first.
  useEffect(() => {
    let cancelled = false
    const total = series.n_slices
    const start = chunk * PREFETCH_CHUNK
    const run = () => {
      const order = []
      if (playing) {
        for (let d = 1; d <= PREFETCH_PLAYING; d += 1) order.push((start + d) % total)
      } else {
        for (let d = 1; d <= PREFETCH_AHEAD; d += 1) {
          if (start + d < total) order.push(start + d)
          if (start - d >= 0) order.push(start - d)
        }
      }
      let cursor = 0
      let done = 0
      // No progress bar during playback: it would repaint several times a second and say
      // nothing — the viewer is running, which is the only status that matters.
      if (order.length && !playing) setPreload({ done: 0, total: order.length })
      const worker = async () => {
        while (!cancelled) {
          const i = order[cursor++]
          if (i === undefined) return
          const entry = loadFrame(i)
          if (entry) { try { await entry.ready } catch { /* leave it missing */ } }
          done += 1
          if (!cancelled && !playing && (done % 4 === 0 || done === order.length)) {
            setPreload({ done, total: order.length })
          }
        }
      }
      Promise.all(Array.from({ length: PRELOAD_CONCURRENCY }, worker))
        .then(() => { if (!cancelled) { setPreload(null); evictFarFrom(start) } })
    }
    // Playback can't afford to wait out a debounce; a scrub can, and should.
    if (playing) { run(); return () => { cancelled = true; setPreload(null) } }
    const timer = setTimeout(run, PRELOAD_DEBOUNCE_MS)
    return () => { cancelled = true; clearTimeout(timer); setPreload(null) }
  }, [series.id, chunk, playing, series.n_slices, loadFrame, evictFarFrom])

  // Draw. A canvas keeps the previous frame on screen until the next one is ready, so
  // scrubbing never flashes blank — and because the window is applied HERE rather than by
  // the server, changing it is a re-render of pixels already in memory.
  useEffect(() => {
    const entry = loadFrame(index)
    if (!entry) return undefined
    let cancelled = false

    const paint = () => {
      const canvas = canvasRef.current
      if (cancelled || !canvas) return
      if (entry.frame) {
        // Paint with the frame's OWN default until the user picks a window, rather than
        // waiting a render for `frameDefault` to arrive — otherwise the first paint of a
        // series flashes at the fallback guess.
        const wc = win ? win.wc : entry.frame.default_wc
        const ww = win ? win.ww : entry.frame.default_ww
        renderFrame(canvas, entry.frame, wc, ww)
        setDecodeError(null)
        return
      }
      const img = entry.img
      if (!img) return
      const draw = () => {
        if (cancelled || !img.naturalWidth) return
        if (canvas.width !== img.naturalWidth || canvas.height !== img.naturalHeight) {
          canvas.width = img.naturalWidth
          canvas.height = img.naturalHeight
        }
        canvas.getContext('2d').drawImage(img, 0, 0)
        setDecodeError(null)
      }
      if (img.complete && img.naturalWidth) draw()
      else {
        img.addEventListener('load', draw, { once: true })
        img.addEventListener('error', () => {
          if (!cancelled) setDecodeError(DECODE_HINT)
        }, { once: true })
      }
    }

    entry.ready.then(() => {
      if (cancelled) return
      // A failed load is almost always a compressed transfer syntax the backend can't
      // decode (it answers 415 with an actionable message) — surface it, not a blank stage.
      if (entry.failed) { setDecodeError(DECODE_HINT); return }
      // Adopt the frame's declared window so the readout states what is on screen. In the
      // `.then`, not the effect body, so it isn't a synchronous setState in an effect.
      if (entry.frame) {
        setFrameDefault((cur) => (
          cur && cur.wc === entry.frame.default_wc && cur.ww === entry.frame.default_ww
            ? cur
            : { wc: entry.frame.default_wc, ww: entry.frame.default_ww }))
      }
      paint()
    })
    return () => { cancelled = true }
  }, [index, series.id, win, effWin.wc, effWin.ww, loadFrame])

  // Keyboard, following PACS/DICOM-viewer conventions (RadiAnt/Sectra/MicroDicom): arrows
  // step one slice, PageUp/PageDown jump 10, Home/End first/last, digits pick window
  // presets. Typing contexts are skipped, which also lets the range slider keep its own
  // native arrow handling (no double-stepping).
  useEffect(() => {
    const step = (d) => setIndex((i) => Math.min(Math.max(i + d, 0), last))
    const names = Object.keys(usablePresets)
    // Keyboard zoom has no cursor to anchor on, so it zooms about the frame's centre.
    const cx = () => {
      const r = frameRef.current?.getBoundingClientRect()
      return r ? r.left + r.width / 2 : 0
    }
    const cy = () => {
      const r = frameRef.current?.getBoundingClientRect()
      return r ? r.top + r.height / 2 : 0
    }
    const onKey = (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const t = e.target
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return
      switch (e.key) {
        case 'ArrowDown': case 'ArrowRight': step(1); e.preventDefault(); break
        case 'ArrowUp': case 'ArrowLeft': step(-1); e.preventDefault(); break
        case 'PageDown': step(10); e.preventDefault(); break
        case 'PageUp': step(-10); e.preventDefault(); break
        case 'Home': setIndex(0); e.preventDefault(); break
        case 'End': setIndex(last); e.preventDefault(); break
        case ' ': setPlaying((p) => !p); e.preventDefault(); break
        case '+': case '=': zoomAt(cx(), cy(), ZOOM_STEP); e.preventDefault(); break
        case '-': case '_': zoomAt(cx(), cy(), 1 / ZOOM_STEP); e.preventDefault(); break
        case 'r': case 'R': setView(IDENTITY_VIEW); break
        case 'f': case 'F': toggleFullscreen(); break
        case '0': setWin(null); break
        default: {
          const n = Number(e.key)
          if (Number.isInteger(n) && n >= 1 && n <= names.length) setWin({ ...usablePresets[names[n - 1]] })
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [last, usablePresets, toggleFullscreen])

  // FIT THE IMAGE TO THE STAGE, IN JS, PRESERVING ASPECT. CSS cannot do this here: the
  // obvious rules each fail one way — `max-width/max-height: 100%` on a canvas inside a
  // shrink-wrapping flex frame let the frame's default `align-items: stretch` squash the
  // image (a 512×1024 coronal rendered 512×748, 27% short); `align-items: flex-start`
  // fixes the aspect but the clamp stops working and the image overflows; and
  // `aspect-ratio` does not back-propagate a max-HEIGHT into the width. `object-fit:
  // contain` would work visually and break everything else, because every pointer
  // mapping on this page (clicks, the zoom anchor, the crisp test) reads the canvas's
  // BOX and would then be reading a letterbox rather than the image.
  //
  // So the frame is sized to the fitted box directly. `Math.min(…, 1)` keeps today's rule
  // that an image is never blown up past its own resolution — the viewer downscales to
  // fit and otherwise shows native pixels.
  const [fit, setFit] = useState(null)
  useEffect(() => {
    const stage = stageRef.current
    const cols = series.Columns
    const rows = series.Rows
    if (!stage || !cols || !rows) return undefined
    const measure = () => {
      const r = stage.getBoundingClientRect()
      if (!r.width || !r.height) return
      const scale = Math.min(r.width / cols, r.height / rows, 1)
      setFit({ w: cols * scale, h: rows * scale })
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(stage)
    return () => ro.disconnect()
  }, [series.Columns, series.Rows])

  // The SCALING FILTER follows from the same measurement, because the display scale is
  // exactly what decides whether pixels get dropped. Minifying (the normal case here — a
  // 512² axial in a ~300px stage, or a 1248×1969 reformat at 20%) must AVERAGE, or a 1–2px
  // fracture line can be skipped and never drawn; magnifying must NOT interpolate, or the
  // viewer invents detail that was never acquired. Deriving it from `fit` — rather than
  // from a second ResizeObserver on the canvas, as before — is what keeps the two in step:
  // that observer measured a box the fit was about to change, so it ran a render behind
  // and set the filter from the PREVIOUS size (observed: a 512-wide image displayed at 374
  // was being drawn with the magnifying filter).
  const crisp = fit != null && fit.w * view.zoom >= (series.Columns || Infinity)

  // Mouse wheel over the image scrubs the stack — the most universal DICOM interaction.
  // Attached manually (not React onWheel) because preventDefault needs a NON-passive
  // listener to stop the page scrolling behind the scrub.
  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const onWheel = (e) => {
      e.preventDefault()
      // Ctrl+wheel zooms (the browser's own pinch-zoom gesture maps here too); plain wheel
      // scrubs the stack, which is the convention every DICOM viewer shares.
      if (e.ctrlKey) zoomAt(e.clientX, e.clientY, e.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP)
      else setIndex((i) => Math.min(Math.max(i + (e.deltaY > 0 ? 1 : -1), 0), last))
    }
    stage.addEventListener('wheel', onWheel, { passive: false })
    return () => stage.removeEventListener('wheel', onWheel)
  }, [last]) // eslint-disable-line react-hooks/exhaustive-deps

  // Map a click to IMAGE-pixel coordinates. The SVG overlay shares that coordinate system
  // via its viewBox, so drawing needs no scaling at any display size.
  function pointFromEvent(e) {
    const canvas = canvasRef.current
    if (!canvas || !canvas.width) return null
    const r = canvas.getBoundingClientRect()
    const x = ((e.clientX - r.left) / r.width) * canvas.width
    const y = ((e.clientY - r.top) / r.height) * canvas.height
    if (x < 0 || y < 0 || x > canvas.width || y > canvas.height) return null
    return { x, y }
  }

  function handleStageClick(e) {
    if (mode === 'off') return
    const p = pointFromEvent(e)
    if (!p) return
    const need = POINTS_NEEDED[mode]
    setPoints((prev) => (prev.length >= need ? [p] : [...prev, p]))
  }

  // One pointer, three drag behaviours, disambiguated so no gesture is ever guessed at:
  //   shift/middle drag → PAN        (works in any mode; the escape hatch when zoomed in)
  //   ROI mode          → rubber-band the measurement rectangle
  //   no measure mode   → WINDOW/LEVEL, the standard radiologist gesture (horizontal =
  //                       width/contrast, vertical = centre/brightness, up = brighter),
  //                       and the only practical way to work a non-Hounsfield modality.
  function onPointerDown(e) {
    if (e.button === 1 || e.shiftKey) {
      panRef.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty }
    } else if (e.button !== 0) {
      return
    } else if (mode === 'roi') {
      const p = pointFromEvent(e)
      if (!p) return
      roiDragRef.current = p
      setRect({ x: p.x, y: p.y, w: 0, h: 0 })
      setRoi(null)
    } else if (mode === 'off') {
      dragRef.current = { x: e.clientX, y: e.clientY, wc: effWin.wc, ww: effWin.ww }
    } else {
      return
    }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function onPointerMove(e) {
    const pan = panRef.current
    if (pan) {
      setView((v) => ({ ...v, tx: pan.tx + (e.clientX - pan.x), ty: pan.ty + (e.clientY - pan.y) }))
      return
    }
    const start = roiDragRef.current
    if (start) {
      const p = pointFromEvent(e)
      if (!p) return
      setRect({
        x: Math.min(start.x, p.x), y: Math.min(start.y, p.y),
        w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y),
      })
      return
    }
    const d = dragRef.current
    if (!d) return
    const now = performance.now()
    if (now - lastWlRef.current < WL_THROTTLE_MS) return
    lastWlRef.current = now
    setWin({
      ww: Math.max(1, Math.round(d.ww + (e.clientX - d.x) * WL_SENSITIVITY)),
      wc: Math.round(d.wc + (e.clientY - d.y) * WL_SENSITIVITY),
    })
  }

  function endDrag(e) {
    if (!dragRef.current && !panRef.current && !roiDragRef.current) return
    dragRef.current = null
    panRef.current = null
    roiDragRef.current = null
    if (e.pointerId != null && e.currentTarget.hasPointerCapture?.(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }

  const need = POINTS_NEEDED[mode]
  const complete = mode !== 'off' && points.length === need
  const readout = !complete ? null
    : mode === 'distance'
      ? distanceLabel(points[0], points[1], series.pixel_spacing)
      : angleLabel(points[0], points[1], points[2], series.pixel_spacing)
  const dotR = Math.max((series.Columns || 512) / 170, 1.5)

  const seriesName = series.SeriesDescription || series.BodyPartExamined
    || `Series ${series.SeriesNumber ?? ''}`

  return (
    <div className="dcm__viewer">
      {/* THE INSTRUMENT: the stage and its controls are one bordered unit, not a picture
          with widgets loose on the page beneath it. The strip carries its own dark palette
          in BOTH themes, for the same reason the stage is black in both — it is not the
          app's chrome, it is the instrument's own surface, and a radiologist's console
          does not change colour because the page around it did. */}
      <div className="dcm__instrument" ref={instrumentRef}>
      <div
        className={`dcm__stage${mode !== 'off' ? ' dcm__stage--measuring' : ' dcm__stage--wl'}`}
        ref={stageRef}
        onClick={handleStageClick}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        {/* The transform lives on the frame so the overlay scales WITH the image and
            annotations stay glued to the anatomy under them. */}
        <div
          className="dcm__frame"
          ref={frameRef}
          style={{
            transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.zoom})`,
            ...(fit ? { width: `${fit.w}px`, height: `${fit.h}px` } : null),
          }}
        >
          <canvas
            className={`dcm__image${crisp ? ' dcm__image--crisp' : ''}`}
            ref={canvasRef}
            role="img"
            aria-label={`Slice ${index + 1} of ${series.n_slices}`}
          />
          {(points.length > 0 || rect) && (
            <svg
              className="dcm__overlay"
              viewBox={`0 0 ${series.Columns || 1} ${series.Rows || 1}`}
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              {points.length > 1 && (
                <polyline
                  points={points.map((p) => `${p.x},${p.y}`).join(' ')}
                  className="dcm__measure-line"
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {points.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r={dotR} className="dcm__measure-dot" />
              ))}
              {rect && rect.w > 0 && (
                <rect
                  x={rect.x} y={rect.y} width={rect.w} height={rect.h}
                  className="dcm__measure-rect" vectorEffect="non-scaling-stroke"
                />
              )}
            </svg>
          )}
        </div>
        {decodeError && <p className="dcm__decode-error">{decodeError}</p>}
      </div>

      <div className="dcm__strip">
        {/* Row 1: where you are in the stack, and WHICH stack. The series has to name
            itself here now that the picker is a drawer rather than a permanent rail. */}
        <div className="dcm__strip-row">
          {series.n_slices > 1 && (
            <input
              className="dcm__slice-range"
              type="range"
              min={0}
              max={last}
              value={index}
              onChange={(e) => setIndex(Number(e.target.value))}
              aria-label="Slice"
            />
          )}
          <span className="dcm__read">
            {[series.Modality, seriesName].filter(Boolean).join(' · ')}
            {series.n_slices > 1 && <> · Slice <b>{index + 1}</b> / {series.n_slices}</>}
          </span>
        </div>

      {/* Tools. A distance/angle/ROI is a plain geometric FACT computed from the file's own
          calibration — no interpretation. */}
      <div className="dcm__strip-row dcm__tools">
        {series.n_slices > 1 && (
          <button
            type="button"
            className={`dcm__win dcm__win--icon${playing ? ' dcm__win--on' : ''}`}
            onClick={() => setPlaying((p) => !p)}
            title={`${playing ? 'Pause' : 'Play'} through the stack (space) — ${fps}/s`}
            aria-label={playing ? 'Pause' : 'Play'}
          >
            {playing ? <PauseIcon /> : <PlayIcon />}
          </button>
        )}
        {series.n_slices > 1 && (
          <select
            className="dcm__speed"
            value={fps}
            onChange={(e) => setFps(Number(e.target.value))}
            aria-label="Playback speed"
            title="Playback speed (slices per second)"
          >
            {CINE_SPEEDS.map((n) => <option key={n} value={n}>{n}/s</option>)}
          </select>
        )}
        <button
          type="button"
          className={`dcm__win dcm__win--icon${isFullscreen ? ' dcm__win--on' : ''}`}
          onClick={toggleFullscreen}
          title={`${isFullscreen ? 'Leave' : 'Fill the screen'} (F)`}
          aria-label={isFullscreen ? 'Leave fullscreen' : 'Fullscreen'}
          aria-pressed={isFullscreen}
        >
          {isFullscreen ? <ContractIcon /> : <ExpandIcon />}
        </button>
        {['distance', 'angle', 'roi'].map((m) => {
          const Icon = TOOL_ICONS[m]
          return (
            <button
              key={m}
              type="button"
              className={`dcm__win dcm__win--icon${mode === m ? ' dcm__win--on' : ''}`}
              onClick={() => setMode((cur) => (cur === m ? 'off' : m))}
              title={TOOL_NAMES[m]}
              aria-label={TOOL_NAMES[m]}
              aria-pressed={mode === m}
            >
              <Icon />
            </button>
          )
        })}
        {/* The status sits BETWEEN fixed flanks (tools left, window controls right) and
            takes the slack, so a measurement appearing or a tool changing can no longer
            reflow the row — which is what the old fixed-height status line was working
            around. It still always renders, so the row's height is constant. */}
        <span className="dcm__status">
        {mode === 'roi' && !roi && <span className="muted small">Drag a box on the image.</span>}
        {mode !== 'off' && mode !== 'roi' && !complete && (
          <span className="muted small">
            Click point {points.length + 1} of {need}
            {mode === 'angle' && points.length === 1 ? ' (the vertex)' : ''}.
          </span>
        )}
        {complete && (
          <>
            <span className="dcm__measure-value">{readout}</span>
            <button type="button" className="dcm__link" onClick={() => setPoints([])}>Clear</button>
          </>
        )}
        {roi && (
          <>
            {/* Descriptive statistics only — what the pixels ARE, never what they mean. */}
            <span className="dcm__measure-value">{roi.mean} ± {roi.sd} {roi.units}</span>
            <span className="muted small">
              {roi.min}–{roi.max}
              {roi.area_mm2 != null && ` · ${Math.round(roi.area_mm2)} mm²`}
            </span>
            <button type="button" className="dcm__link"
                    onClick={() => { setRect(null); setRoi(null) }}>Clear</button>
          </>
        )}
        {preload && preload.done < preload.total && (
          <span className="muted small dcm__preload">
            <span className="dcm__preload-bar">
              <span style={{ width: `${(preload.done / preload.total) * 100}%` }} />
            </span>
            caching {preload.done}/{preload.total}
          </span>
        )}
          {view.zoom !== 1 && (
            <>
              {view.zoom.toFixed(1)}×
              <button type="button" className="dcm__link"
                      onClick={() => setView(IDENTITY_VIEW)}>reset</button>
            </>
          )}
        </span>
        <span className="dcm__windows">
          <button
            type="button"
            className={`dcm__win${win === null ? ' dcm__win--on' : ''}`}
            onClick={() => setWin(null)}
            title="The file's own window"
          >
            Default
          </button>
          {/* Say WHY the presets are gone, so their absence reads as deliberate rather
              than missing. Drag still works — it's relative, so it needs no calibration. */}
          {!presetsApply && (
            <span
              className="muted small dcm__nopresets"
              title={`Window presets are defined in ${presetsUnits} (a CT scale). This series' `
                     + `values are "${series.value_units || 'raw'}", so they would not mean `
                     + `anything here. Drag the image to adjust window/level instead.`}
            >
              drag to window
            </span>
          )}
          {Object.entries(usablePresets).map(([name, { wc, ww }]) => {
            const on = win && win.wc === wc && win.ww === ww
            return (
              <button
                key={name}
                type="button"
                className={`dcm__win${on ? ' dcm__win--on' : ''}`}
                onClick={() => setWin({ wc, ww })}
                title={`${PRESET_HINTS[name] || name} (centre ${wc}, width ${ww} HU)`}
              >
                {PRESET_LABELS[name] || name}
              </button>
            )
          })}
        </span>
        <span className="dcm__read dcm__read--wl">
          W <b>{Math.round(effWin.ww)}</b> · L <b>{Math.round(effWin.wc)}</b>
        </span>
      </div>
      </div>
      </div>

      {/* Below the instrument, on the page's own ground: the allowlisted metadata (no PII
          is ever sent from the backend) and the shortcut list, which folds away so it
          doesn't cost image height. */}
      <div className="dcm__footer">
        <span className="muted small">
          {[series.BodyPartExamined,
            series.Rows && series.Columns && `${series.Columns}×${series.Rows}`,
            `${series.n_slices} slice${series.n_slices === 1 ? '' : 's'}`]
            .filter(Boolean).join(' · ')}
        </span>
        <details className="dcm__keyhelp">
          <summary>Shortcuts</summary>
          <p className="muted small">
            Scroll or ↑↓ step · PgUp/PgDn ±10 · Home/End first/last · space play/pause ·
            drag = window/level · shift-drag = pan · ctrl-scroll or +/− zoom · R reset ·
            F fullscreen ·
            {Object.keys(usablePresets).length > 0
              ? `1–${Object.keys(usablePresets).length} presets · 0 default`
              : '0 default window'}
          </p>
        </details>
      </div>
    </div>
  )
}

export default function ImagingPage() {
  const [data, setData] = useState(null) // { available, reason, presets, studies }
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null) // the chosen series object
  const [searchParams] = useSearchParams()
  // The picker is a DRAWER, not a permanent rail: choosing a series is a navigation act,
  // and this record is six studies carrying up to 94 series each — a long index to keep on
  // screen while you read an image. Closed, the instrument gets the full page width.
  //
  // It opens itself when there is nothing to look at yet, which is the one moment the
  // picker IS the page. A deep link (/imaging?study=…) arrives with a series already
  // chosen, so it opens straight onto the images with the drawer shut.
  const [drawerOpen, setDrawerOpen] = useState(() => !searchParams.get('study'))

  // Escape closes it, like every other overlay in the app.
  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e) => { if (e.key === 'Escape') setDrawerOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  useEffect(() => {
    getImagingStudies().then(setData).catch((e) => setError(e.message))
  }, [])

  // Timeline → viewer deep link: /imaging?study=<id> preselects that study's first
  // series, so a timeline imaging entry lands on its images, not a blank picker.
  useEffect(() => {
    if (!data || selected) return
    const wanted = searchParams.get('study')
    if (!wanted) return
    const study = data.studies.find((st) => st.id === wanted)
    if (study && study.series.length > 0) setSelected(study.series[0])
  }, [data, searchParams, selected])

  if (error) return <p className="error">Couldn’t reach the API: {error}</p>
  if (!data) return <Loading what="imaging" />

  if (!data.available) {
    return (
      <section className="dcm">
        <h2>Imaging</h2>
        <p className="muted">{data.reason}</p>
        <p className="muted small">
          Install the optional imaging packages (<code>pip install pydicom Pillow</code>) and
          restart the backend.
        </p>
      </section>
    )
  }

  if (data.studies.length === 0) {
    return (
      <section className="dcm">
        <h2>Imaging</h2>
        <p className="muted">No DICOM studies found.</p>
        <p className="muted small">
          Copy your DICOM files (a hospital CD/USB’s <code>DICOM</code> folder — the image
          files, not the bundled viewer) into the <code>imaging_store/</code> folder in the
          project, then reload. Everything stays on this machine.
        </p>
      </section>
    )
  }

  return (
    <section className="dcm">
      {/* The privacy note is folded into an info tooltip: it's important context but it's
          the same every visit, and as running text it cost a line the images could use.
          Focusable (not hover-only) so it's reachable by keyboard, and the text stays in
          the DOM for screen readers rather than being hidden behind a title attribute. */}
      <div className="dcm__head">
        <button
          type="button"
          className="dcm__drawer-toggle"
          onClick={() => setDrawerOpen((o) => !o)}
          aria-expanded={drawerOpen}
          aria-controls="dcm-drawer"
        >
          <MenuIcon /> Studies
        </button>
        <h2 className="dcm__title">Imaging</h2>
        <span className="dcm__info" tabIndex={0} role="note" aria-label="Privacy note">
          <InfoCircleIcon size={16} />
          <span className="dcm__info-bubble">
            Local only — rendered on this machine; nothing is uploaded. Patient, physician
            and facility details in the files are never shown.
          </span>
        </span>
      </div>
      <div className="dcm__layout">
        {selected
          ? <Viewer key={selected.id} series={selected} presets={data.presets}
                    presetsUnits={data.presets_units} />
          : <p className="muted dcm__hint">Choose a study to view.</p>}

        {/* The drawer sits OVER the instrument rather than beside it, so opening and
            closing it never resizes the image — the same reason every control below the
            stage is pinned. Picking a series closes it: you came here to look at the
            image, and it is one click to bring the index back. */}
        {drawerOpen && (
          <>
            <div className="dcm__scrim" onClick={() => setDrawerOpen(false)} />
            <div id="dcm-drawer" className="dcm__drawer" role="dialog" aria-label="Studies">
              <div className="dcm__drawer-head">
                <span>Studies</span>
                <button type="button" className="dcm__drawer-close"
                        onClick={() => setDrawerOpen(false)} aria-label="Close studies">×</button>
              </div>
              <StudyList
                studies={data.studies}
                selectedSeriesId={selected?.id}
                onPick={(sel) => { setSelected(sel); setDrawerOpen(false) }}
              />
            </div>
          </>
        )}
      </div>
    </section>
  )
}
