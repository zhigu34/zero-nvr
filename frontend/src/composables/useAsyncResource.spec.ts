import { describe, expect, it, vi } from "vitest"

import { ApiClientError } from "../api/client"
import { useAsyncResource } from "./useAsyncResource"

describe("useAsyncResource", () => {
  it("exposes loading while the loader runs and clears it afterwards", async () => {
    const { loading, error, run } = useAsyncResource()
    expect(loading.value).toBe(false)

    let release: () => void = () => {}
    const pending = run(
      () =>
        new Promise<void>((resolve) => {
          release = resolve
        })
    )

    expect(loading.value).toBe(true)
    expect(error.value).toBeNull()

    release()
    await pending
    expect(loading.value).toBe(false)
  })

  it("maps a failure through errorMessage by default", async () => {
    const { error, run } = useAsyncResource()

    await run(() => {
      throw new ApiClientError(409, "conflict", "Name is already in use.")
    })

    expect(error.value).toBe("Name is already in use.")
  })

  it("resets loading after a failure so a spinner cannot be stranded", async () => {
    // The copies this replaces could leave `loading` true when a site forgot
    // its `finally`; the composable always resets it.
    const { loading, error, run } = useAsyncResource()

    await run(() => {
      throw new Error("boom")
    })

    expect(loading.value).toBe(false)
    expect(error.value).not.toBeNull()
  })

  it("clears a previous error before loading again", async () => {
    const { error, run } = useAsyncResource()

    await run(() => {
      throw new Error("first failure")
    })
    expect(error.value).not.toBeNull()

    await run(() => undefined)
    expect(error.value).toBeNull()
  })

  it("accepts a custom error mapping", async () => {
    // The schedule editor prefixes its failures so a failed load is
    // distinguishable from a failed save.
    const { error, run } = useAsyncResource()

    await run(
      () => {
        throw new Error("nope")
      },
      { onError: (caught) => `加载计划失败: ${(caught as Error).message}` }
    )

    expect(error.value).toBe("加载计划失败: nope")
  })

  it("supports a loader that closes over caller state", async () => {
    // Sites derive values (a time window, a target id) before the guarded
    // section; passing the loader per call keeps that scope available.
    const { run } = useAsyncResource()
    const assigned: string[] = []
    const target = "camera-1"

    await run(async () => {
      assigned.push(await Promise.resolve(target))
    })

    expect(assigned).toEqual(["camera-1"])
  })

  it("reports a synchronous throw too", async () => {
    const { loading, error, run } = useAsyncResource()

    await run(() => {
      throw new Error("sync boom")
    })

    expect(error.value).toBe("sync boom")
    expect(loading.value).toBe(false)
  })

  it("does not swallow the loader's own work when it resolves", async () => {
    const { run } = useAsyncResource()
    const done = vi.fn()

    await run(() => {
      done()
    })

    expect(done).toHaveBeenCalledTimes(1)
  })
})
