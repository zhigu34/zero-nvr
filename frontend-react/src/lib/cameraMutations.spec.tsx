import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "../api/client"
import { ToastProvider } from "../components/ui/Toast"
import {
  wasPersisted,
  useSetCameraEnabled,
} from "./cameraMutations"

/**
 * The distinction these tests protect: a 503 from an enable/disable may mean
 * "nothing happened" or "the database already has the change and only the
 * media runtime missed it". Telling the operator the first when the second
 * happened sends them into a retry loop against a state that is already
 * correct.
 */

afterEach(cleanup)

describe("wasPersisted", () => {
  it("is true when the error details carry a persisted flag", () => {
    const error = new ApiError(503, "camera_runtime_queue_unavailable", "…", {
      camera_persisted: true,
    })
    expect(wasPersisted(error)).toBe(true)
  })

  it("is true for the other entities' flag names", () => {
    for (const flag of [
      "configuration_persisted",
      "policy_persisted",
      "settings_persisted",
      "export_persisted",
    ]) {
      expect(wasPersisted(new ApiError(503, "x", "…", { [flag]: true }))).toBe(
        true,
      )
    }
  })

  it("is false for an ordinary validation failure", () => {
    const error = new ApiError(400, "invalid_rtsp_url", "bad url", {
      field: "rtsp_url",
    })
    expect(wasPersisted(error)).toBe(false)
  })

  it("is false when there are no details at all", () => {
    expect(wasPersisted(new ApiError(500, "x", "…"))).toBe(false)
    expect(wasPersisted(new ApiError(503, "x", "…", null))).toBe(false)
  })

  it("is false for a flag that is present but not true", () => {
    // A `false` means the change was rolled back; saying "saved" would be
    // the more dangerous mistake.
    expect(
      wasPersisted(new ApiError(503, "x", "…", { camera_persisted: false })),
    ).toBe(false)
  })

  it("is false for a non-error value", () => {
    expect(wasPersisted(new Error("network"))).toBe(false)
    expect(wasPersisted("nope")).toBe(false)
  })
})

function EnableButton({ status }: { status: number }) {
  // The id is passed at the call site now, not bound at mount — a row action
  // must act on the row it was clicked on, not on the open one.
  const { enable } = useSetCameraEnabled()
  return <button onClick={() => enable("cam-1")}>启用</button>
}

function renderWithStubbedFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  )
  const client = new QueryClient()
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <EnableButton status={status} />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe("enabling a camera", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("reports a partial failure as saved-but-not-yet-effective", async () => {
    renderWithStubbedFetch(503, {
      error: {
        code: "camera_runtime_queue_unavailable",
        message: "媒体运行时繁忙",
        details: { camera_persisted: true },
      },
    })

    act(() => {
      screen.getByRole("button", { name: "启用" }).click()
    })

    await waitFor(() => {
      expect(screen.getByText("启用已保存，但尚未生效")).toBeTruthy()
    })
    // The detail has to say what happened, or the operator retries a save
    // that already landed.
    expect(screen.getByText(/已经写入/)).toBeTruthy()
  })

  it("reports a plain failure as a failure", async () => {
    renderWithStubbedFetch(409, {
      error: { code: "camera_retired", message: "机位已退役" },
    })

    act(() => {
      screen.getByRole("button", { name: "启用" }).click()
    })

    await waitFor(() => {
      expect(screen.getByText("启用保存失败")).toBeTruthy()
    })
    expect(screen.getByText("机位已退役")).toBeTruthy()
  })
})
