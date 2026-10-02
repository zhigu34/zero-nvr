/**
 * The drawer is the one overlay in the app that stays open while the operator
 * works, so its keyboard contract is the whole test: focus in, focus trapped,
 * focus restored. A drawer that renders correctly but leaks focus to the page
 * underneath is worse than no drawer.
 */
import { render, screen, waitFor } from "@testing-library/react"
import { fireEvent } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { Drawer } from "./Drawer"

function Host({ open = true }: { open?: boolean }) {
  return (
    <div>
      <button type="button">背景按钮</button>
      <Drawer open={open} onClose={() => {}} title="前门">
        <button type="button">面板内按钮</button>
      </Drawer>
    </div>
  )
}

afterEach(() => {
  document.body.style.overflow = ""
})

describe("Drawer", () => {
  it("is a modal dialog named by its title", () => {
    render(<Host />)
    const dialog = screen.getByRole("dialog")
    expect(dialog.getAttribute("aria-modal")).toBe("true")
    // The accessible name comes from the visible title, not a duplicated label.
    expect(dialog.getAttribute("aria-labelledby")).toBe(
      screen.getByText("前门").id,
    )
  })

  it("renders nothing when closed", () => {
    render(<Host open={false} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("focuses the panel itself on open, so the title is announced first", async () => {
    render(<Host />)
    // Not the close button: every drawer would then open on the same control.
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("dialog")),
    )
  })

  it("returns focus to where it came from on close", async () => {
    const opener = document.createElement("button")
    opener.textContent = "打开"
    document.body.appendChild(opener)
    opener.focus()
    expect(document.activeElement).toBe(opener)

    const { rerender } = render(<Host open />)
    await waitFor(() => expect(document.activeElement).not.toBe(opener))

    rerender(<Host open={false} />)
    await waitFor(() => expect(document.activeElement).toBe(opener))
    opener.remove()
  })

  it("traps Tab so focus cannot walk behind the overlay", async () => {
    render(<Host />)
    const panel = await screen.findByRole("dialog")
    const close = screen.getByRole("button", { name: "关闭" })
    const inside = screen.getByRole("button", { name: "面板内按钮" })

    // Just opened: Tab enters the content from the top…
    expect(document.activeElement).toBe(panel)
    fireEvent.keyDown(window, { key: "Tab" })
    expect(document.activeElement).toBe(close)

    // …forward from the last stop wraps back to the first…
    inside.focus()
    fireEvent.keyDown(window, { key: "Tab" })
    expect(document.activeElement).toBe(close)

    // …and backward from the first wraps to the last.
    close.focus()
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true })
    expect(document.activeElement).toBe(inside)
  })

  it("closes on Escape", () => {
    const onClose = vi.fn()
    render(
      <Drawer open onClose={onClose} title="前门">
        <button type="button">面板内按钮</button>
      </Drawer>,
    )
    fireEvent.keyDown(window, { key: "Escape" })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("closes on a backdrop click but not on a click inside the panel", () => {
    const onClose = vi.fn()
    render(
      <Drawer open onClose={onClose} title="前门">
        <button type="button">面板内按钮</button>
      </Drawer>,
    )
    // A click that starts inside must not read as "clicked away", which is how
    // selecting text and releasing outside the panel would close it.
    fireEvent.click(screen.getByRole("button", { name: "面板内按钮" }))
    expect(onClose).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole("dialog").parentElement as HTMLElement)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("locks background scroll while open and restores it after", () => {
    document.body.style.overflow = "auto"
    const { rerender } = render(<Host open />)
    expect(document.body.style.overflow).toBe("hidden")
    rerender(<Host open={false} />)
    expect(document.body.style.overflow).toBe("auto")
  })
})
