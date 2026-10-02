import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ConfirmProvider, useConfirm } from "./Confirm"
import { render, screen as rscreen } from "@testing-library/react"

import { renderWithProviders } from "../../test-utils"

/**
 * A confirmation prompt has exactly one job, and it fails in one way that
 * matters: if "no" is treated as "yes", an unanswered question becomes a
 * destructive action. These pin the three ways that can go wrong — a dismissed
 * prompt resolving true, a backdrop click counting as consent, and the
 * provider being absent — plus the ordinary paths.
 */

function Harness({ onResult }: { onResult: (v: boolean) => void }) {
  const confirm = useConfirm()
  return (
    <button
      type="button"
      onClick={async () => {
        onResult(
          await confirm({
            title: "删除告警规则",
            message: "确定删除？",
            confirmLabel: "删除",
            danger: true,
          }),
        )
      }}
    >
      触发
    </button>
  )
}

function renderHarness(onResult: (v: boolean) => void) {
  return render(
    <ConfirmProvider>
      <Harness onResult={onResult} />
    </ConfirmProvider>,
  )
}

describe("ConfirmProvider", () => {
  it("resolves true only when the operator confirms", async () => {
    const results: boolean[] = []
    renderHarness((v) => results.push(v))
    fireEvent.click(rscreen.getByRole("button", { name: "触发" }))

    const dialog = await rscreen.findByRole("alertdialog")
    expect(dialog.getAttribute("aria-label")).toBe("删除告警规则")
    fireEvent.click(rscreen.getByRole("button", { name: "删除" }))

    await waitFor(() => expect(results).toEqual([true]))
  })

  it("resolves false when cancelled", async () => {
    const results: boolean[] = []
    renderHarness((v) => results.push(v))
    fireEvent.click(rscreen.getByRole("button", { name: "触发" }))
    await rscreen.findByRole("alertdialog")
    fireEvent.click(rscreen.getByRole("button", { name: "取消" }))

    // The load-bearing assertion: a dismissed prompt must never read as
    // consent.
    await waitFor(() => expect(results).toEqual([false]))
  })

  it("treats a backdrop click as cancel, not as confirm", async () => {
    const results: boolean[] = []
    renderHarness((v) => results.push(v))
    fireEvent.click(rscreen.getByRole("button", { name: "触发" }))
    const backdrop = (await rscreen.findByRole("alertdialog")).parentElement!
    fireEvent.click(backdrop)

    await waitFor(() => expect(results).toEqual([false]))
  })

  it("treats Escape as cancel", async () => {
    const results: boolean[] = []
    renderHarness((v) => results.push(v))
    fireEvent.click(rscreen.getByRole("button", { name: "触发" }))
    await rscreen.findByRole("alertdialog")
    fireEvent.keyDown(window, { key: "Escape" })

    await waitFor(() => expect(results).toEqual([false]))
  })

  it("shows nothing until something asks", () => {
    renderHarness(() => {})
    expect(rscreen.queryByRole("alertdialog")).toBeNull()
  })

  it("uses the supplied labels and marks a destructive action", async () => {
    renderHarness(() => {})
    fireEvent.click(rscreen.getByRole("button", { name: "触发" }))
    const confirmButton = await rscreen.findByRole("button", { name: "删除" })
    expect(confirmButton.className).toContain("destructive")
  })

  it("throws rather than assuming consent when no provider is mounted", () => {
    // Silence here would mean every destructive action in the app silently
    // proceeds. The error is the safety mechanism.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {})
    expect(() => render(<Harness onResult={() => {}} />)).toThrow(
      /outside <ConfirmProvider>/,
    )
    spy.mockRestore()
  })

  it("serves two prompts in sequence without cross-resolving", async () => {
    const results: boolean[] = []
    renderHarness((v) => results.push(v))
    const trigger = rscreen.getByRole("button", { name: "触发" })

    fireEvent.click(trigger)
    await rscreen.findByRole("alertdialog")
    fireEvent.click(rscreen.getByRole("button", { name: "删除" }))
    await waitFor(() => expect(results).toEqual([true]))

    fireEvent.click(trigger)
    await rscreen.findByRole("alertdialog")
    fireEvent.click(rscreen.getByRole("button", { name: "取消" }))
    await waitFor(() => expect(results).toEqual([true, false]))
  })
})

describe("test harness", () => {
  it("mounts the provider, so a page's destructive path is testable", () => {
    // If this ever stops being true, every page test that clicks a delete
    // button would start throwing.
    const client = new QueryClient()
    renderWithProviders(<Harness onResult={() => {}} />, { client })
    fireEvent.click(rscreen.getByRole("button", { name: "触发" }))
    expect(rscreen.getByRole("alertdialog")).toBeTruthy()
    expect(screen).toBeTruthy()
  })
})
