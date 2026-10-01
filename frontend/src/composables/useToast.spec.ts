import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { dismissToast, showToast, useToast } from "./useToast"

describe("useToast", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    dismissToast()
  })

  afterEach(() => {
    dismissToast()
    vi.useRealTimers()
  })

  it("shows a message and clears it after the given dwell time", () => {
    showToast("saved", 1000)
    expect(useToast().message.value).toBe("saved")

    vi.advanceTimersByTime(999)
    expect(useToast().message.value).toBe("saved")

    vi.advanceTimersByTime(1)
    expect(useToast().message.value).toBeNull()
  })

  it("uses the per-surface default duration", () => {
    // Each view kept its own dwell time when the logic was consolidated.
    const shortLived = useToast(2500)
    shortLived.showToast("files")
    vi.advanceTimersByTime(2499)
    expect(shortLived.message.value).toBe("files")
    vi.advanceTimersByTime(1)
    expect(shortLived.message.value).toBeNull()
  })

  it("replaces the pending timer when a second message is shown", () => {
    // The original per-view copies leaked their timer; the shared one must
    // cancel it so an old timeout cannot blank a message that replaced it.
    showToast("first", 1000)
    vi.advanceTimersByTime(500)
    showToast("second", 1000)

    // The first message's deadline passes without clearing the second message.
    vi.advanceTimersByTime(500)
    expect(useToast().message.value).toBe("second")

    vi.advanceTimersByTime(500)
    expect(useToast().message.value).toBeNull()
  })

  it("clears the message and cancels the timer on dismiss", () => {
    showToast("still visible", 1000)
    dismissToast()
    expect(useToast().message.value).toBeNull()

    // A dismissed timer must not fire late and disturb a later message.
    showToast("later", 5000)
    vi.advanceTimersByTime(1000)
    expect(useToast().message.value).toBe("later")
  })
})
