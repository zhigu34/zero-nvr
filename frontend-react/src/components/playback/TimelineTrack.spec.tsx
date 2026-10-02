import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"

import type { PlaybackTimelineView, TimelineGapReason } from "../../api/playback"
import { instantMs } from "../../playback/session"
import { TimelineTrack } from "./TimelineTrack"

afterEach(cleanup)

const START = "2026-10-01T00:00:00Z"
const END = "2026-10-01T01:00:00Z"

function timeline(
  gaps: Array<{
    start_at: string
    end_at: string
    reason: TimelineGapReason
  }>,
): PlaybackTimelineView {
  return {
    camera_id: "cam-1",
    detail: "minute",
    range: { start_at: START, end_at: END },
    segments: [
      {
        id: "s1",
        playback_ref: "s1",
        start_at: START,
        end_at: "2026-10-01T00:20:00Z",
        availability: "local",
      },
    ],
    recording_ranges: [],
    gaps,
    events: [],
  }
}

function renderTrack(
  props: Partial<React.ComponentProps<typeof TimelineTrack>> = {},
) {
  return render(
    <TimelineTrack
      timeline={timeline([])}
      rangeStartMs={instantMs(START)}
      rangeEndMs={instantMs(END)}
      currentMs={instantMs(START)}
      {...props}
    />,
  )
}

describe("TimelineTrack", () => {
  it("labels each gap with its actual reason", () => {
    renderTrack({
      timeline: timeline([
        {
          start_at: "2026-10-01T00:20:00Z",
          end_at: "2026-10-01T00:30:00Z",
          reason: "purged",
        },
        {
          start_at: "2026-10-01T00:30:00Z",
          end_at: "2026-10-01T00:40:00Z",
          reason: "source_lost",
        },
      ]),
    })

    const purged = document.querySelector('[data-gap-reason="purged"]')
    const lost = document.querySelector('[data-gap-reason="source_lost"]')

    // Different reasons must be distinguishable, both visually and on hover.
    expect(purged).toBeTruthy()
    expect(lost).toBeTruthy()
    expect(purged!.getAttribute("title")).toContain("已按保留策略清理")
    expect(lost!.getAttribute("title")).toContain("信号丢失")
  })

  it("does not paint a gap as an ordinary recorded segment", () => {
    renderTrack({
      timeline: timeline([
        {
          start_at: "2026-10-01T00:20:00Z",
          end_at: "2026-10-01T00:40:00Z",
          reason: "storage_failure",
        },
      ]),
    })

    const gap = document.querySelector(
      '[data-gap-reason="storage_failure"]',
    ) as HTMLElement
    // The hatching is what stops a gap reading as a dimmer recording.
    expect(gap.style.backgroundImage).toContain("repeating-linear-gradient")
  })

  it("keeps every gap reason the backend can emit renderable", () => {
    const reasons: TimelineGapReason[] = [
      "not_scheduled",
      "no_event",
      "source_lost",
      "runtime_restart",
      "storage_failure",
      "missing_media",
      "purged",
      "unknown",
    ]
    let minute = 0
    const gaps = reasons.map((reason) => {
      const start = new Date(instantMs(START) + minute * 60_000)
      minute += 2
      const end = new Date(start.getTime() + 60_000)
      return {
        start_at: start.toISOString(),
        end_at: end.toISOString(),
        reason,
      }
    })

    renderTrack({ timeline: timeline(gaps) })

    for (const reason of reasons) {
      const el = document.querySelector(`[data-gap-reason="${reason}"]`)
      expect(el, `gap reason ${reason} should render`).toBeTruthy()
      expect(el!.getAttribute("title")).toBeTruthy()
    }
  })

  it("positions the playhead by time, clamped to the range", () => {
    const { rerender } = renderTrack({
      currentMs: instantMs("2026-10-01T00:30:00Z"),
    })
    const mid = document.querySelector('[data-testid="playhead"]') as HTMLElement
    expect(mid.style.left).toBe("50%")

    rerender(
      <TimelineTrack
        timeline={timeline([])}
        rangeStartMs={instantMs(START)}
        rangeEndMs={instantMs(END)}
        currentMs={instantMs("2026-10-02T00:00:00Z")}
      />,
    )
    const clamped = document.querySelector(
      '[data-testid="playhead"]',
    ) as HTMLElement
    expect(clamped.style.left).toBe("100%")
  })

  it("reports the clicked instant to the caller", () => {
    const onSeek = vi.fn()
    renderTrack({ onSeek })

    const track = screen.getByRole("slider")
    track.getBoundingClientRect = () =>
      ({ left: 0, width: 1000, top: 0, height: 44 }) as DOMRect
    fireEvent.click(track, { clientX: 250 })

    expect(onSeek).toHaveBeenCalledTimes(1)
    const [atMs] = onSeek.mock.calls[0]
    // A quarter of the way across an hour is fifteen minutes in.
    expect(atMs - instantMs(START)).toBe(900_000)
  })

  it("does not expose a seek affordance when seeking is disabled", () => {
    renderTrack()
    // No slider role at all when onSeek is absent: a track that looks
    // draggable but is not is worse than one that plainly is not.
    expect(screen.queryByRole("slider")).toBeNull()
  })

  it("survives a null timeline", () => {
    expect(() => renderTrack({ timeline: null })).not.toThrow()
  })

  it("keeps a zero-length span from producing NaN widths", () => {
    renderTrack({
      rangeStartMs: instantMs(START),
      rangeEndMs: instantMs(START),
    })
    const segment = document.querySelector("[title='local']") as HTMLElement
    expect(segment.style.width).not.toContain("NaN")
  })
})
