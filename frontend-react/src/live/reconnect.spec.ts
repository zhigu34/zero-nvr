import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ReconnectScheduler } from "./reconnect"

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

const DELAYS = [100, 200, 400]

describe("ReconnectScheduler", () => {
  it("backs off through the ladder", async () => {
    const attempt = vi.fn()
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(100)
    expect(attempt).toHaveBeenCalledTimes(1)

    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(200)
    expect(attempt).toHaveBeenCalledTimes(2)

    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(400)
    expect(attempt).toHaveBeenCalledTimes(3)
  })

  it("keeps trying at the cap rather than giving up", async () => {
    const attempt = vi.fn()
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    for (let i = 0; i < 8; i += 1) {
      scheduler.schedule()
      await vi.advanceTimersByTimeAsync(400)
    }

    // A camera that comes back must recover without the operator touching
    // anything; stopping is what leaves tiles black indefinitely.
    expect(attempt).toHaveBeenCalledTimes(8)
    expect(scheduler.attemptNumber).toBe(8)
  })

  it("reschedules itself after a rejected attempt", async () => {
    const attempt = vi.fn(() => Promise.reject(new Error("still down")))
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(100)
    expect(attempt).toHaveBeenCalledTimes(1)

    // No one called schedule() this time — the rejection has to do it.
    await vi.advanceTimersByTimeAsync(200)
    expect(attempt).toHaveBeenCalledTimes(2)
  })

  it("reschedules after a synchronous throw", async () => {
    const attempt = vi.fn(() => {
      throw new Error("boom")
    })
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(100)
    await vi.advanceTimersByTimeAsync(200)

    expect(attempt).toHaveBeenCalledTimes(2)
  })

  it("stops rescheduling after a successful attempt", async () => {
    const attempt = vi.fn(() => Promise.resolve())
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(100)

    await vi.advanceTimersByTimeAsync(10_000)
    expect(attempt).toHaveBeenCalledTimes(1)
  })

  it("resets the ladder when the stream recovers", async () => {
    const attempt = vi.fn()
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(100)
    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(200)
    expect(scheduler.attemptNumber).toBe(2)

    scheduler.succeed()
    expect(scheduler.attemptNumber).toBe(0)

    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(100)
    expect(attempt).toHaveBeenCalledTimes(3)
  })

  it("runs immediately on a manual retry", () => {
    const attempt = vi.fn()
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    scheduler.retryNow()

    // An operator who just fixed the camera should not wait out the backoff.
    expect(attempt).toHaveBeenCalledTimes(1)
    expect(scheduler.attemptNumber).toBe(1)
  })

  it("cancels a pending retry on a manual retry", async () => {
    const attempt = vi.fn()
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    scheduler.schedule()
    scheduler.retryNow()

    // The queued attempt must not also fire.
    await vi.advanceTimersByTimeAsync(1_000)
    expect(attempt).toHaveBeenCalledTimes(1)
  })

  it("stops permanently when told to", async () => {
    const attempt = vi.fn()
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    scheduler.schedule()
    scheduler.stop()
    await vi.advanceTimersByTimeAsync(10_000)

    // Unmounting must not leave a timer writing into a dead component.
    expect(attempt).not.toHaveBeenCalled()
    expect(scheduler.isPending).toBe(false)
  })

  it("does not stack timers when scheduled repeatedly", async () => {
    const attempt = vi.fn()
    const scheduler = new ReconnectScheduler({ attempt, delaysMs: DELAYS })

    scheduler.schedule()
    scheduler.schedule()
    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(1_000)

    expect(attempt).toHaveBeenCalledTimes(1)
  })

  it("reports each attempt to the caller", async () => {
    const onAttemptStart = vi.fn()
    const scheduler = new ReconnectScheduler({
      attempt: vi.fn(),
      delaysMs: DELAYS,
      onAttemptStart,
    })

    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(100)
    scheduler.schedule()
    await vi.advanceTimersByTimeAsync(200)

    expect(onAttemptStart.mock.calls).toEqual([[1], [2]])
  })
})
