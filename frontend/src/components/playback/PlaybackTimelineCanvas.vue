<script setup lang="ts">
import {
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch
} from "vue"

import type { RecordingProtection } from "../../api/recordings"
import type { PlaybackTimeline } from "../../api/playback"

type ZoomHours = 1 | 6 | 24
type ZoomDirection = "in" | "out"

type HitTarget =
  | {
      kind: "gap" | "recording"
      x1: number
      x2: number
      y1: number
      y2: number
      tooltip: string
    }
  | {
      kind: "event"
      x1: number
      x2: number
      y1: number
      y2: number
      tooltip: string
      at: number | null
    }
  | {
      kind: "protection"
      x1: number
      x2: number
      y1: number
      y2: number
      tooltip: string
      item: RecordingProtection
    }

const props = defineProps<{
  timeline: PlaybackTimeline | null
  protections: RecordingProtection[]
  currentAt: Date
  zoomHours: ZoomHours
  canProtect: boolean
}>()

const emit = defineEmits<{
  seek: [at: Date]
  pan: [deltaMs: number]
  zoom: [
    payload: {
      direction: ZoomDirection
      anchor: Date
    }
  ]
  protect: [item: RecordingProtection]
}>()

const root = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const hoverText = ref<string | null>(null)
const hoverLeft = ref(0)
const hoverTop = ref(0)

const HEIGHT = 86
const LANE_TOP = 30
const LANE_BOTTOM = 78
const LANE_HEIGHT = LANE_BOTTOM - LANE_TOP

let resizeObserver: ResizeObserver | null = null
let drawFrame: number | null = null
let hitTargets: HitTarget[] = []
let activePointerId: number | null = null
let pointerStartX = 0
let pointerLastX = 0
let pointerDragged = false
let dragOffsetPx = 0
let wheelPanMs = 0
let wheelPanTimer: number | null = null
let zoomLockedUntil = 0

function bounds(): [number, number] {
  if (!props.timeline) {
    const now = props.currentAt.getTime()
    return [now - 30 * 60_000, now + 30 * 60_000]
  }
  return [
    new Date(props.timeline.range.start_at).getTime(),
    new Date(props.timeline.range.end_at).getTime()
  ]
}

function durationMs(): number {
  const [start, end] = bounds()
  return Math.max(1, end - start)
}

function xForTime(
  timeMs: number,
  width: number,
  offset = dragOffsetPx
): number {
  const [start] = bounds()
  return (
    ((timeMs - start) / durationMs()) * width +
    offset
  )
}

function timeForX(x: number, width: number): number {
  const [start] = bounds()
  return (
    start +
    (Math.max(0, Math.min(width, x)) / Math.max(1, width)) *
      durationMs()
  )
}

function formatClock(timeMs: number): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(timeMs))
}

function formatTimestamp(timeMs: number): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(new Date(timeMs))
}

function gapColor(reason: string): string {
  if (
    ["source_lost", "storage_failure", "missing_media"].includes(
      reason
    )
  ) {
    return "rgba(195, 74, 87, 0.14)"
  }
  if (reason === "purged") {
    return "rgba(111, 118, 128, 0.18)"
  }
  return "rgba(93, 99, 108, 0.13)"
}

function recordingColor(availability: string): string {
  switch (availability) {
    case "local":
      return "#4a83ff"
    case "cached_remote":
      return "#4fbf91"
    case "remote":
      return "#7468c9"
    case "corrupted":
      return "#a55a65"
    case "missing":
    case "purged":
    default:
      return "#5c626b"
  }
}

function clippedRange(
  startMs: number,
  endMs: number,
  width: number
): [number, number] | null {
  const left = xForTime(startMs, width)
  const right = xForTime(endMs, width)
  if (right < 0 || left > width) return null
  return [
    Math.max(0, left),
    Math.min(width, Math.max(left + 1, right))
  ]
}

function drawHatchedRange(
  context: CanvasRenderingContext2D,
  x1: number,
  x2: number,
  color: string
): void {
  const width = Math.max(1, x2 - x1)
  context.save()
  context.beginPath()
  context.rect(x1, LANE_TOP, width, LANE_HEIGHT)
  context.clip()
  context.fillStyle = color
  context.fillRect(x1, LANE_TOP, width, LANE_HEIGHT)

  context.strokeStyle = color.replace(
    /0\.\d+\)$/,
    "0.42)"
  )
  context.lineWidth = 1
  for (
    let x = x1 - LANE_HEIGHT;
    x < x2 + LANE_HEIGHT;
    x += 8
  ) {
    context.beginPath()
    context.moveTo(x, LANE_BOTTOM)
    context.lineTo(x + LANE_HEIGHT, LANE_TOP)
    context.stroke()
  }
  context.restore()
}

function draw(): void {
  drawFrame = null
  const element = canvas.value
  const host = root.value
  if (!element || !host) return

  const width = Math.max(1, host.clientWidth)
  const dpr = Math.max(1, window.devicePixelRatio || 1)
  const pixelWidth = Math.round(width * dpr)
  const pixelHeight = Math.round(HEIGHT * dpr)

  if (
    element.width !== pixelWidth ||
    element.height !== pixelHeight
  ) {
    element.width = pixelWidth
    element.height = pixelHeight
    element.style.width = `${width}px`
    element.style.height = `${HEIGHT}px`
  }

  const context = element.getContext("2d")
  if (!context) return

  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  context.clearRect(0, 0, width, HEIGHT)
  hitTargets = []

  context.fillStyle = "#111317"
  context.fillRect(0, LANE_TOP, width, LANE_HEIGHT)
  context.strokeStyle = "#22262b"
  context.lineWidth = 1
  context.strokeRect(
    0.5,
    LANE_TOP + 0.5,
    Math.max(0, width - 1),
    LANE_HEIGHT - 1
  )

  const tickCount = props.zoomHours === 24 ? 8 : 6
  const [start, end] = bounds()
  context.font =
    "8px ui-sans-serif, system-ui, -apple-system, sans-serif"
  context.textAlign = "center"
  context.textBaseline = "top"

  for (let index = 0; index <= tickCount; index += 1) {
    const ratio = index / tickCount
    const time = start + (end - start) * ratio
    const x = ratio * width + dragOffsetPx
    if (x < -40 || x > width + 40) continue

    context.fillStyle = "#2b2f34"
    context.fillRect(Math.round(x), 0, 1, 8)
    context.fillStyle = "#6f7680"
    context.fillText(formatClock(time), x, 11)
  }

  for (const gap of props.timeline?.gaps ?? []) {
    const range = clippedRange(
      new Date(gap.start_at).getTime(),
      new Date(gap.end_at).getTime(),
      width
    )
    if (!range) continue
    const [x1, x2] = range
    drawHatchedRange(
      context,
      x1,
      x2,
      gapColor(gap.reason)
    )
    hitTargets.push({
      kind: "gap",
      x1,
      x2,
      y1: LANE_TOP,
      y2: LANE_BOTTOM,
      tooltip: gap.reason.replaceAll("_", " ")
    })
  }

  for (const rangeItem of props.timeline?.recording_ranges ?? []) {
    const startMs = new Date(rangeItem.start_at).getTime()
    const endMs = new Date(rangeItem.end_at).getTime()
    const range = clippedRange(startMs, endMs, width)
    if (!range) continue
    const [x1, x2] = range
    const y = LANE_TOP + 17
    const height = 11
    context.fillStyle = recordingColor(
      rangeItem.availability
    )
    context.fillRect(
      x1,
      y,
      Math.max(2, x2 - x1),
      height
    )
    hitTargets.push({
      kind: "recording",
      x1,
      x2,
      y1: y - 4,
      y2: y + height + 4,
      tooltip: `${rangeItem.availability.replaceAll(
        "_",
        " "
      )} · ${formatTimestamp(startMs)}`
    })
  }

  for (const item of props.protections) {
    const range = clippedRange(
      new Date(item.started_at).getTime(),
      new Date(item.ended_at).getTime(),
      width
    )
    if (!range) continue
    const [x1, x2] = range
    const y = LANE_BOTTOM - 7
    context.fillStyle = "rgba(215, 179, 79, 0.9)"
    context.fillRect(
      x1,
      y,
      Math.max(2, x2 - x1),
      5
    )
    const expiry = item.expires_at
      ? ` · expires ${formatTimestamp(
          new Date(item.expires_at).getTime()
        )}`
      : ""
    hitTargets.push({
      kind: "protection",
      x1,
      x2,
      y1: y - 4,
      y2: LANE_BOTTOM,
      item,
      tooltip: `${item.reason}${expiry}`
    })
  }

  for (const event of props.timeline?.events ?? []) {
    const startMs = new Date(event.start_at).getTime()
    const label = event.label
      ? ` · ${event.label}`
      : ""

    if (event.marker_type === "aggregate") {
      const endMs = event.end_at
        ? new Date(event.end_at).getTime()
        : startMs
      const range = clippedRange(
        startMs,
        Math.max(startMs + 1, endMs),
        width
      )
      if (!range) continue
      const [x1, x2] = range
      const y = LANE_TOP + 3
      const height = 10
      context.fillStyle = "rgba(212, 154, 69, 0.42)"
      context.fillRect(
        x1,
        y,
        Math.max(2, x2 - x1),
        height
      )

      const categoryBreakdown = Object.entries(
        event.category_counts
      )
        .map(([name, count]) => `${name} ${count}`)
        .join(" · ")
      if (x2 - x1 >= 24) {
        context.fillStyle = "#f5d39e"
        context.font =
          "7px ui-sans-serif, system-ui, -apple-system, sans-serif"
        context.textAlign = "center"
        context.textBaseline = "middle"
        context.fillText(
          String(event.count),
          (x1 + x2) / 2,
          y + height / 2
        )
      }

      hitTargets.push({
        kind: "event",
        x1,
        x2,
        y1: LANE_TOP,
        y2: LANE_TOP + 18,
        at: startMs + (endMs - startMs) / 2,
        tooltip: `${event.count} events${categoryBreakdown ? ` · ${categoryBreakdown}` : ""}`
      })
      continue
    }

    if (event.marker_type === "range") {
      const [, timelineEnd] = bounds()
      const endMs = event.end_at
        ? new Date(event.end_at).getTime()
        : timelineEnd
      const range = clippedRange(
        startMs,
        Math.max(startMs + 1, endMs),
        width
      )
      if (!range) continue
      const [x1, x2] = range
      const y = LANE_TOP + 4
      const height = 8

      context.fillStyle = "rgba(212, 154, 69, 0.5)"
      context.fillRect(
        x1,
        y,
        Math.max(2, x2 - x1),
        height
      )
      context.strokeStyle = "rgba(212, 154, 69, 0.9)"
      context.lineWidth = 1
      context.strokeRect(
        x1 + 0.5,
        y + 0.5,
        Math.max(1, x2 - x1 - 1),
        Math.max(1, height - 1)
      )

      hitTargets.push({
        kind: "event",
        x1,
        x2,
        y1: LANE_TOP,
        y2: LANE_TOP + 18,
        at: null,
        tooltip: `${event.category}${label} · ${formatTimestamp(
          startMs
        )} → ${event.end_at ? formatTimestamp(endMs) : "ongoing"}`
      })
      continue
    }

    const x = xForTime(startMs, width)
    if (x < -6 || x > width + 6) continue

    context.strokeStyle = "rgba(212, 154, 69, 0.72)"
    context.lineWidth = 1
    context.beginPath()
    context.moveTo(x, LANE_TOP + 11)
    context.lineTo(x, LANE_BOTTOM - 2)
    context.stroke()

    context.fillStyle = "#d49a45"
    context.strokeStyle = "#241c11"
    context.beginPath()
    context.arc(x, LANE_TOP + 7, 3.5, 0, Math.PI * 2)
    context.fill()
    context.stroke()

    hitTargets.push({
      kind: "event",
      x1: x - 6,
      x2: x + 6,
      y1: LANE_TOP,
      y2: LANE_BOTTOM,
      at: startMs,
      tooltip: `${event.category}${label} · ${formatTimestamp(
        startMs
      )}`
    })
  }

  const playheadX = xForTime(
    props.currentAt.getTime(),
    width,
    0
  )
  if (playheadX >= 0 && playheadX <= width) {
    context.strokeStyle = "#f4f6f8"
    context.lineWidth = 1
    context.beginPath()
    context.moveTo(playheadX, LANE_TOP)
    context.lineTo(playheadX, LANE_BOTTOM)
    context.stroke()

    context.fillStyle = "#f4f6f8"
    context.beginPath()
    context.arc(
      playheadX,
      LANE_TOP,
      3.5,
      0,
      Math.PI * 2
    )
    context.fill()
  }
}

function scheduleDraw(): void {
  if (drawFrame !== null) return
  drawFrame = window.requestAnimationFrame(draw)
}

function localX(event: PointerEvent | WheelEvent): number {
  const host = root.value
  if (!host) return 0
  const rect = host.getBoundingClientRect()
  return event.clientX - rect.left
}

function targetAt(
  x: number,
  y: number
): HitTarget | null {
  for (let index = hitTargets.length - 1; index >= 0; index -= 1) {
    const target = hitTargets[index]
    if (
      x >= target.x1 &&
      x <= target.x2 &&
      y >= target.y1 &&
      y <= target.y2
    ) {
      return target
    }
  }
  return null
}

function updateHover(event: PointerEvent): void {
  const host = root.value
  if (!host) return
  const rect = host.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  const target = targetAt(x, y)

  hoverText.value = target?.tooltip ?? null
  hoverLeft.value = Math.max(
    4,
    Math.min(rect.width - 180, x + 10)
  )
  hoverTop.value = Math.max(
    4,
    Math.min(HEIGHT - 26, y - 24)
  )
}

function handlePointerDown(event: PointerEvent): void {
  if (event.button !== 0) return
  const host = root.value
  if (!host) return

  activePointerId = event.pointerId
  pointerStartX = localX(event)
  pointerLastX = pointerStartX
  pointerDragged = false
  dragOffsetPx = 0
  hoverText.value = null
  host.setPointerCapture(event.pointerId)
}

function handlePointerMove(event: PointerEvent): void {
  if (activePointerId !== event.pointerId) {
    updateHover(event)
    return
  }

  pointerLastX = localX(event)
  dragOffsetPx = pointerLastX - pointerStartX
  if (Math.abs(dragOffsetPx) > 4) {
    pointerDragged = true
  }

  if (pointerDragged) {
    scheduleDraw()
  } else {
    updateHover(event)
  }
}

function finishPointer(event: PointerEvent): void {
  if (activePointerId !== event.pointerId) return
  const host = root.value
  if (!host) return

  try {
    host.releasePointerCapture(event.pointerId)
  } catch {
    // Pointer capture can already be released by the browser.
  }

  const x = localX(event)
  const rect = host.getBoundingClientRect()
  const y = event.clientY - rect.top

  if (pointerDragged) {
    const deltaMs =
      -(dragOffsetPx / Math.max(1, rect.width)) *
      durationMs()
    dragOffsetPx = 0
    scheduleDraw()
    if (Math.abs(deltaMs) >= 1) {
      emit("pan", deltaMs)
    }
  } else {
    const target = targetAt(x, y)
    if (target?.kind === "protection") {
      if (props.canProtect) {
        emit("protect", target.item)
      }
    } else if (
      target?.kind === "event" &&
      target.at !== null
    ) {
      emit("seek", new Date(target.at))
    } else {
      emit(
        "seek",
        new Date(timeForX(x, rect.width))
      )
    }
  }

  activePointerId = null
  pointerDragged = false
  pointerStartX = 0
  pointerLastX = 0
}

function cancelPointer(event: PointerEvent): void {
  if (activePointerId !== event.pointerId) return
  const host = root.value
  if (host) {
    try {
      host.releasePointerCapture(event.pointerId)
    } catch {
      // Pointer capture can already be released by the browser.
    }
  }
  activePointerId = null
  pointerDragged = false
  pointerStartX = 0
  pointerLastX = 0
  dragOffsetPx = 0
  hoverText.value = null
  scheduleDraw()
}

function handlePointerLeave(): void {
  if (activePointerId === null) {
    hoverText.value = null
  }
}

function flushWheelPan(): void {
  wheelPanTimer = null
  if (Math.abs(wheelPanMs) < 1) {
    wheelPanMs = 0
    return
  }
  const delta = wheelPanMs
  wheelPanMs = 0
  emit("pan", delta)
}

function handleWheel(event: WheelEvent): void {
  const host = root.value
  if (!host) return

  const width = Math.max(1, host.clientWidth)
  if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
    wheelPanMs +=
      (event.deltaX / width) * durationMs()
    if (wheelPanTimer !== null) {
      window.clearTimeout(wheelPanTimer)
    }
    wheelPanTimer = window.setTimeout(
      flushWheelPan,
      90
    )
    return
  }

  const now = performance.now()
  if (
    Math.abs(event.deltaY) < 1 ||
    now < zoomLockedUntil
  ) {
    return
  }

  zoomLockedUntil = now + 180
  emit("zoom", {
    direction: event.deltaY < 0 ? "in" : "out",
    anchor: new Date(
      timeForX(localX(event), width)
    )
  })
}

function handleKeydown(event: KeyboardEvent): void {
  const step = Math.max(
    1_000,
    Math.round(durationMs() / 100)
  )
  if (event.key === "ArrowLeft") {
    event.preventDefault()
    emit(
      "seek",
      new Date(props.currentAt.getTime() - step)
    )
    return
  }
  if (event.key === "ArrowRight") {
    event.preventDefault()
    emit(
      "seek",
      new Date(props.currentAt.getTime() + step)
    )
    return
  }
  if (event.key === "PageUp") {
    event.preventDefault()
    emit("pan", -durationMs() / 2)
    return
  }
  if (event.key === "PageDown") {
    event.preventDefault()
    emit("pan", durationMs() / 2)
    return
  }
  if (event.key === "+" || event.key === "=") {
    event.preventDefault()
    emit("zoom", {
      direction: "in",
      anchor: props.currentAt
    })
    return
  }
  if (event.key === "-" || event.key === "_") {
    event.preventDefault()
    emit("zoom", {
      direction: "out",
      anchor: props.currentAt
    })
  }
}

watch(
  () => props.timeline,
  scheduleDraw,
  { deep: true }
)
watch(
  () => props.protections,
  scheduleDraw,
  { deep: true }
)
watch(
  () => props.currentAt.getTime(),
  scheduleDraw
)
watch(
  () => props.zoomHours,
  scheduleDraw
)

onMounted(async () => {
  await nextTick()
  resizeObserver = new ResizeObserver(
    scheduleDraw
  )
  if (root.value) {
    resizeObserver.observe(root.value)
  }
  scheduleDraw()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (drawFrame !== null) {
    window.cancelAnimationFrame(drawFrame)
    drawFrame = null
  }
  if (wheelPanTimer !== null) {
    window.clearTimeout(wheelPanTimer)
    wheelPanTimer = null
  }
})
</script>

<template>
  <div
    ref="root"
    class="playback-canvas-timeline"
    role="slider"
    tabindex="0"
    aria-label="Recording timeline"
    :aria-valuemin="bounds()[0]"
    :aria-valuemax="bounds()[1]"
    :aria-valuenow="currentAt.getTime()"
    :aria-valuetext="formatTimestamp(currentAt.getTime())"
    @pointerdown="handlePointerDown"
    @pointermove="handlePointerMove"
    @pointerup="finishPointer"
    @pointercancel="cancelPointer"
    @pointerleave="handlePointerLeave"
    @wheel.prevent="handleWheel"
    @keydown="handleKeydown"
  >
    <canvas
      ref="canvas"
      class="playback-canvas-timeline__surface"
      aria-hidden="true"
    />
    <span
      v-if="hoverText"
      class="playback-canvas-timeline__tooltip"
      :style="{
        left: `${hoverLeft}px`,
        top: `${hoverTop}px`
      }"
    >
      {{ hoverText }}
    </span>
  </div>
</template>

<style scoped>
.playback-canvas-timeline {
  position: relative;
  width: 100%;
  height: 86px;
  cursor: crosshair;
  outline: none;
  touch-action: none;
  user-select: none;
}

.playback-canvas-timeline:focus-visible {
  border-radius: 5px;
  box-shadow: 0 0 0 2px var(--focus-ring);
}

.playback-canvas-timeline__surface {
  display: block;
  width: 100%;
  height: 86px;
}

.playback-canvas-timeline__tooltip {
  position: absolute;
  z-index: 4;
  max-width: 180px;
  padding: 4px 6px;
  border: 1px solid #2d3238;
  border-radius: 4px;
  background: rgba(17, 19, 23, 0.96);
  color: #dfe3e8;
  font-size: 8px;
  line-height: 1.3;
  pointer-events: none;
  white-space: nowrap;
}
</style>
