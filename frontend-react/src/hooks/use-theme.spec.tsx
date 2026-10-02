import { act, render, renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router"
import { routeTree } from "../routes/router"
import { useTheme } from "./use-theme"

/**
 * Regression guard.
 *
 * theme.css declares `--sidebar: var(--background)` inside `:root`. A CSS
 * custom property alias is substituted on the element that declares it, so
 * if `.dark` were toggled on a nested wrapper the sidebar would keep
 * inheriting the already-resolved light `--background` while the rest of the
 * app went dark — the sidebar silently ignoring the theme toggle.
 *
 * The class therefore has to land on <html> (the same element as :root),
 * where the later `.dark` block wins on source order at equal specificity.
 */
describe("useTheme", () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove("dark")
  })

  it("toggles the class on the document root, not a wrapper element", () => {
    const { result } = renderHook(() => useTheme())

    act(() => result.current.toggle())
    expect(document.documentElement.classList.contains("dark")).toBe(true)

    act(() => result.current.toggle())
    expect(document.documentElement.classList.contains("dark")).toBe(false)
  })

  it("persists the choice and restores it on mount", () => {
    const first = renderHook(() => useTheme())
    act(() => first.result.current.toggle())
    expect(localStorage.getItem("zero-nvr-theme")).toBe("dark")
    first.unmount()

    const second = renderHook(() => useTheme())
    expect(second.result.current.isDark).toBe(true)
    expect(document.documentElement.classList.contains("dark")).toBe(true)
  })

  it("keeps the dark class off any descendant of the app", () => {
    // The real shell, not just the hook: the bug was a wrapper div in the
    // component tree, so asserting on the hook alone would not catch it.
    const { container } = render(
      <RouterProvider
        router={createRouter({
          routeTree,
          history: createMemoryHistory({ initialEntries: ["/live"] }),
        })}
      />,
    )
    expect(container.querySelector(".dark")).toBeNull()
    expect(document.documentElement.classList.contains("dark")).toBe(false)
  })
})
