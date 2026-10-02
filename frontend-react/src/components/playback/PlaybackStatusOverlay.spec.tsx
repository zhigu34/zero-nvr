import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"

import { PlaybackStatusOverlay } from "./PlaybackStatusOverlay"

afterEach(cleanup)

function overlay(props: Partial<React.ComponentProps<typeof PlaybackStatusOverlay>> = {}) {
  return render(
    <PlaybackStatusOverlay state="unavailable" {...props} />,
  )
}

describe("PlaybackStatusOverlay", () => {
  it("renders nothing when the tile is ready", () => {
    const { container } = overlay({ state: "ready" })
    expect(container.firstChild).toBeNull()
  })

  /**
   * The project rule: a failure must state a reason and offer a retry. The
   * Vue playback page rendered bare error text with no way out, which is what
   * this test exists to prevent coming back.
   */
  it("always offers a retry when the caller can recover", () => {
    const onRetry = vi.fn()
    overlay({ state: "unavailable", onRetry })

    const button = screen.getByRole("button", { name: "重试" })
    fireEvent.click(button)
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it("names the reason for a failure", () => {
    overlay({ state: "unavailable", message: "无法连接媒体服务" })
    expect(screen.getByText("无法连接媒体服务")).toBeTruthy()
  })

  it("falls back to a default reason rather than an empty tile", () => {
    overlay({ state: "unavailable" })
    expect(screen.getByText("播放失败")).toBeTruthy()
  })

  it("reflects an in-flight retry on the button", () => {
    overlay({ state: "unavailable", onRetry: vi.fn(), retrying: true })

    const button = screen.getByRole("button", { name: "正在重试…" })
    expect((button as HTMLButtonElement).disabled).toBe(true)
  })

  it("offers gap navigation instead of a retry", () => {
    const onJumpPrevious = vi.fn()
    const onJumpNext = vi.fn()
    overlay({
      state: "gap",
      message: "已按保留策略清理",
      onJumpPrevious,
      onJumpNext,
    })

    fireEvent.click(screen.getByRole("button", { name: "上一段" }))
    fireEvent.click(screen.getByRole("button", { name: "下一段" }))

    expect(onJumpPrevious).toHaveBeenCalledTimes(1)
    expect(onJumpNext).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull()
  })

  it("disables a gap jump that has nowhere to go", () => {
    overlay({
      state: "gap",
      onJumpPrevious: undefined,
      onJumpNext: vi.fn(),
    })

    const prev = screen.getByRole("button", { name: "上一段" })
    expect((prev as HTMLButtonElement).disabled).toBe(true)
  })

  it("shows the backend's own retry cadence while restoring", () => {
    // The server exposes no progress, only a hint; surfacing it stops the
    // wall looking wedged.
    overlay({ state: "pending", retryAfterMs: 2_000 })
    expect(screen.getByText("约 2 秒后重试")).toBeTruthy()
  })

  it("prefers the supplied reason over the default one", () => {
    overlay({ state: "pending", message: "正在恢复归档片段" })
    expect(screen.getByText("正在恢复归档片段")).toBeTruthy()
  })

  it("exposes the state for styling and assertions", () => {
    const { container } = overlay({ state: "buffering" })
    const root = container.querySelector("[data-tile-state]")!
    expect(root.getAttribute("data-tile-state")).toBe("buffering")
  })

  it("still says something when no recovery is possible", () => {
    // Rather than a bare black rectangle, the operator gets a next step.
    overlay({ state: "unavailable" })
    expect(screen.getByText(/切换机位或时间/)).toBeTruthy()
  })
})
