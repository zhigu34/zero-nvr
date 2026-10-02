/**
 * 密度条和热力图必须建立在**真实**数字上。
 *
 * Vue 的文件页因为时间线端点没有 `size_bytes`，自己编了一个 `dur * 450_000`
 * 来显示月占用空间（`FilesView.vue:262`）。本轮新增的按日端点聚合的是真实
 * 列，所以这些断言守的是「不再出现估算值」，以及两个最容易算错的地方：
 * 时区分桶与空态。
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import type { RecordingDayStat } from "../../api/playback"
import {
  DayDensityStrip,
  DayHeatmap,
  bucketByLocalHour,
  formatBytes,
  formatDuration,
  type DayCell,
} from "./RecordingDensity"

function stat(overrides: Partial<RecordingDayStat> = {}): RecordingDayStat {
  return {
    day: "2026-10-01",
    count: 10,
    duration_sec: 3600,
    size_bytes: 1024,
    ...overrides,
  }
}

function day(day: string, overrides: Partial<RecordingDayStat> = {}): DayCell {
  return { day, stat: stat({ day, ...overrides }), inRange: true }
}

/* -------------------------------------------------------------------------- */

describe("formatBytes", () => {
  it("keeps sub-kilobyte values exactly, because 0 is a real total", () => {
    expect(formatBytes(0)).toBe("0 B")
    expect(formatBytes(512)).toBe("512 B")
  })

  it("picks the unit by magnitude and drops precision where it is noise", () => {
    expect(formatBytes(1024)).toBe("1.0 KB")
    expect(formatBytes(10 * 1024)).toBe("10 KB")
    expect(formatBytes(1024 ** 3)).toBe("1.0 GB")
    // A month of 24/7 footage lives in the TB range; the unit ladder has to
    // reach it rather than saturating at GB.
    expect(formatBytes(2 * 1024 ** 4)).toBe("2.0 TB")
  })
})

describe("formatDuration", () => {
  it("rounds minutes down so a summary never claims more than was recorded", () => {
    // floor, not round: 90s is 1 minute of footage, and calling it 2 would
    // overstate the day by 100%.
    expect(formatDuration(90)).toBe("1 分钟")
  })

  it("does not print 60 minutes at the top of the hour range", () => {
    // 3599s is 59 minutes, not "60 分钟" — the ladder has to roll over before
    // the hour label, or the same length reads two different ways.
    expect(formatDuration(3599)).toBe("59 分钟")
    expect(formatDuration(3600)).toBe("1 小时")
  })

  it("drops a rounded-away remainder instead of inventing a minute", () => {
    expect(formatDuration(3659)).toBe("1 小时")
    expect(formatDuration(3900)).toBe("1 小时 5 分")
  })
})

/* -------------------------------------------------------------------------- */

describe("DayDensityStrip", () => {
  it("shades against the busiest day, not against an absolute threshold", () => {
    // A camera recording 4s/day and one recording 4h/day must both produce a
    // readable strip; a fixed scale would flatten the first to nothing.
    const light = render(
      <DayDensityStrip
        days={[day("2026-10-01", { duration_sec: 4 })]}
        selectedDay={null}
        onSelect={() => {}}
        isPending={false}
        error={null}
      />,
    )
    const lightPeak = screen.getByTitle(/2026-10-01：/).className
    expect(lightPeak).toContain("bg-status-online/75")
    light.unmount()

    render(
      <DayDensityStrip
        days={[
          day("2026-10-01", { duration_sec: 4 }),
          day("2026-10-02", { duration_sec: 14_400 }),
        ]}
        selectedDay={null}
        onSelect={() => {}}
        isPending={false}
        error={null}
      />,
    )
    expect(screen.getByTitle(/2026-10-01：/).className).toContain(
      "bg-status-online/15",
    )
    expect(screen.getByTitle(/2026-10-02：/).className).toContain(
      "bg-status-online/75",
    )
  })

  it("keeps a day with no material visible as an empty cell", () => {
    // A gap in the calendar is information — dropping it would make a camera
    // that stopped recording look like a camera nobody looked at.
    render(
      <DayDensityStrip
        days={[
          day("2026-10-01"),
          { day: "2026-10-02", stat: null, inRange: true },
        ]}
        selectedDay={null}
        onSelect={() => {}}
        isPending={false}
        error={null}
      />,
    )
    expect(screen.getByTitle("2026-10-02：没有录像")).toBeTruthy()
    expect(screen.getByText("1 / 2 天有录像")).toBeTruthy()
  })

  it("shows real bytes and seconds in the cell tooltip", () => {
    render(
      <DayDensityStrip
        days={[day("2026-10-01", { count: 12, duration_sec: 7200, size_bytes: 1024 ** 3 })]}
        selectedDay={null}
        onSelect={() => {}}
        isPending={false}
        error={null}
      />,
    )
    expect(screen.getByTitle("2026-10-01：12 段 · 2 小时 · 1.0 GB")).toBeTruthy()
  })

  it("marks the selected day and reports the click", () => {
    const onSelect = vi.fn()
    render(
      <DayDensityStrip
        days={[day("2026-10-01"), day("2026-10-02")]}
        selectedDay="2026-10-02"
        onSelect={onSelect}
        isPending={false}
        error={null}
      />,
    )
    const buttons = screen.getAllByRole("button")
    expect(buttons[0].getAttribute("aria-pressed")).toBe("false")
    expect(buttons[1].getAttribute("aria-pressed")).toBe("true")

    buttons[0].click()
    expect(onSelect).toHaveBeenCalledWith("2026-10-01")
  })

  it("reports an empty range as empty, and a failure as a failure", () => {
    const { unmount } = render(
      <DayDensityStrip
        days={[]}
        selectedDay={null}
        onSelect={() => {}}
        isPending={false}
        error={null}
      />,
    )
    expect(screen.getByText("没有可显示的日期。")).toBeTruthy()
    unmount()

    render(
      <DayDensityStrip
        days={[]}
        selectedDay={null}
        onSelect={() => {}}
        isPending={false}
        error={new Error("boom")}
      />,
    )
    expect(screen.getByText("无法读取按日统计")).toBeTruthy()
    expect(screen.getByText("boom")).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */

describe("bucketByLocalHour", () => {
  const seg = (start: string, end: string) => ({ start_at: start, end_at: end })

  it("always returns 24 buckets so the axis has no missing ticks", () => {
    const buckets = bucketByLocalHour([], "UTC", "2026-10-01")
    expect(buckets).toHaveLength(24)
    expect(buckets.every((b) => b.segments === 0)).toBe(true)
  })

  it("buckets by the display timezone, not by UTC", () => {
    // 16:00Z is 12:00 in New York (EDT in October) and 00:00 the *next* day in
    // Shanghai. Reading UTC would put this on the wrong hour and the wrong day.
    const rows = [seg("2026-10-01T16:00:00Z", "2026-10-01T16:30:00Z")]

    const ny = bucketByLocalHour(rows, "America/New_York", "2026-10-01")
    expect(ny[12].segments).toBe(1)
    expect(ny[12].durationSec).toBe(1800)

    const shanghai = bucketByLocalHour(rows, "Asia/Shanghai", "2026-10-02")
    expect(shanghai[0].segments).toBe(1)
    // The same instant is the previous day in Shanghai, so asking about the
    // 01st there must come back empty rather than silently borrowing a bucket.
    expect(
      bucketByLocalHour(rows, "Asia/Shanghai", "2026-10-01").every(
        (b) => b.segments === 0,
      ),
    ).toBe(true)
  })

  it("ignores segments from other days instead of clamping them to an edge", () => {
    // A wide timeline range must not bleed into hour 0 or 23 of the focused day.
    const buckets = bucketByLocalHour(
      [
        seg("2026-09-30T23:30:00Z", "2026-09-30T23:59:00Z"),
        seg("2026-10-02T00:10:00Z", "2026-10-02T00:20:00Z"),
      ],
      "UTC",
      "2026-10-01",
    )
    expect(buckets.every((b) => b.segments === 0)).toBe(true)
  })

  it("handles a spring-forward day, which has 23 local hours", () => {
    // 2026-03-08 in New York loses 02:00 local: 04:30Z is still the previous
    // evening, 05:30Z is 00:30 that morning. A fixed-offset assumption puts
    // both segments in the wrong bucket.
    const rows = [
      seg("2026-03-08T04:30:00Z", "2026-03-08T04:40:00Z"),
      seg("2026-03-08T05:30:00Z", "2026-03-08T05:30:15Z"),
    ]
    const buckets = bucketByLocalHour(rows, "America/New_York", "2026-03-08")
    expect(buckets[0].segments).toBe(1)
    expect(buckets[0].durationSec).toBe(15)
  })

  it("survives an unparseable bound rather than reporting NaN", () => {
    const buckets = bucketByLocalHour(
      [seg("not-a-date", "also-not-a-date")],
      "UTC",
      "2026-10-01",
    )
    expect(buckets.every((b) => b.segments === 0)).toBe(true)
  })

  it("never accumulates negative duration from a reversed range", () => {
    const buckets = bucketByLocalHour(
      [seg("2026-10-01T10:00:00Z", "2026-10-01T09:00:00Z")],
      "UTC",
      "2026-10-01",
    )
    expect(buckets[10].segments).toBe(1)
    expect(buckets[10].durationSec).toBe(0)
  })
})

describe("DayHeatmap", () => {
  it("names the empty case instead of drawing 24 blank bars", () => {
    render(
      <DayHeatmap
        buckets={bucketByLocalHour([], "Asia/Shanghai", "2026-10-01")}
        timeZone="Asia/Shanghai"
      />,
    )
    expect(screen.getByText("这一天没有录像")).toBeTruthy()
    expect(screen.getByText("按 Asia/Shanghai 计算，24 个小时里没有任何分段。")).toBeTruthy()
  })

  it("reports how much of the day actually has footage", () => {
    const buckets = bucketByLocalHour(
      [
        { start_at: "2026-10-01T01:00:00Z", end_at: "2026-10-01T01:00:30Z" },
        { start_at: "2026-10-01T02:00:00Z", end_at: "2026-10-01T02:00:20Z" },
      ],
      "UTC",
      "2026-10-01",
    )
    render(<DayHeatmap buckets={buckets} timeZone="UTC" />)
    expect(screen.getByText("UTC · 2 / 24 小时有录像")).toBeTruthy()
    expect(screen.getByTitle("01:00 · 1 段 · 30 秒")).toBeTruthy()
    expect(screen.getByTitle("03:00 · 无录像")).toBeTruthy()
  })
})
