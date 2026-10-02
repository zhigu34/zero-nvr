/**
 * The right-hand detail drawer.
 *
 * Ported from the Vue `DrawerDialog.vue` / `CameraDetailPanel.vue` pair, with the
 * accessibility that hand-rolled overlay panels usually skip. Four things a
 * drawer has to get right or it is a keyboard trap rather than a panel:
 *
 * 1. **Focus moves in on open and comes back on close.** Without the restore, a
 *    drawer closed with Escape drops focus onto `<body>` and the operator has to
 *    Tab from the top of the page to find where they were.
 * 2. **Tab is trapped.** The rest of the page stays mounted underneath, so Tab
 *    would walk into controls that are visually covered and cannot be seen.
 * 3. **Escape closes**, and so does a backdrop click — but only a click on the
 *    backdrop itself (`event.target === event.currentTarget`), so dragging a
 *    text selection out of the panel does not dismiss it.
 * 4. **The background does not scroll.** A long page behind a half-height drawer
 *    that scrolls under the operator's cursor is disorienting.
 *
 * It is `role="dialog"` with `aria-modal`, not `alertdialog`: nothing here
 * interrupts a destructive flow. Destructive prompts belong to `Confirm`.
 */
import * as React from "react"
import { X } from "lucide-react"

import { Button } from "./primitives"
import { cn } from "../../lib/utils"

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",")

/**
 * Focusable stops inside the panel, in DOM order.
 *
 * Visibility is judged from attributes, never from layout. `offsetParent` is
 * `null` for everything in jsdom, so a layout-based filter silently empties the
 * list and turns the focus trap into "Tab does nothing" — the exact failure
 * this list exists to prevent. The attribute checks cover the cases that
 * actually occur: a collapsed (`hidden`) or screen-reader-hidden subtree.
 */
function focusableWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) =>
      !element.closest("[hidden]") &&
      element.closest("[aria-hidden='true']") === null,
  )
}

export interface DrawerProps {
  open: boolean
  onClose: () => void
  /** Names the drawer for assistive tech. */
  title: string
  /** Optional line under the title. */
  description?: React.ReactNode
  children: React.ReactNode
  footer?: React.ReactNode
  /** Extra chrome inside the header, before the close button. */
  headerExtra?: React.ReactNode
  className?: string
}

export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  headerExtra,
  className,
}: DrawerProps) {
  const panelRef = React.useRef<HTMLDivElement>(null)
  const restoreFocusTo = React.useRef<HTMLElement | null>(null)
  const titleId = React.useId()

  // Remember where focus came from *before* the panel exists, so closing can put
  // it back. Captured in an effect rather than during render: a render may be
  // thrown away, and the remembered node must be the one that was really
  // focused when the drawer appeared.
  React.useEffect(() => {
    if (!open) return
    restoreFocusTo.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null

    const panel = panelRef.current
    // Focus the panel itself, not its first control: the panel is
    // `tabIndex={-1}`, so a screen reader announces the dialog *and its title*
    // before the operator starts tabbing through a long panel. Focusing the
    // close button first would open every drawer on the same control.
    panel?.focus()

    return () => {
      restoreFocusTo.current?.focus?.()
      restoreFocusTo.current = null
    }
  }, [open])

  // Body scroll lock. Restored by effect cleanup, and only if still locked —
  // two drawers (drawer + confirm) must not each restore the other's state.
  React.useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previous
    }
  }, [open])

  React.useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== "Tab") return
      const panel = panelRef.current
      if (!panel) return
      const stops = focusableWithin(panel)
      // Nothing focusable: swallow Tab rather than letting it escape behind
      // the overlay.
      if (stops.length === 0) {
        event.preventDefault()
        return
      }
      const first = stops[0]
      const last = stops[stops.length - 1]
      const active = document.activeElement
      // Focus still on the panel (just opened) enters the content from the
      // top going forward and from the bottom going backward.
      if (active === panel) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
        return
      }
      if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="absolute inset-0 bg-foreground/40" aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn(
          "relative flex h-full w-full max-w-2xl flex-col border-l border-border bg-background shadow-lg",
          className,
        )}
      >
        <header className="flex items-start gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="truncate text-sm font-semibold">
              {title}
            </h2>
            {description ? (
              <div className="mt-0.5 text-xs text-muted-foreground">
                {description}
              </div>
            ) : null}
          </div>
          {headerExtra}
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="关闭"
            onClick={onClose}
          >
            <X />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>

        {footer ? (
          <footer className="border-t border-border px-4 py-3">{footer}</footer>
        ) : null}
      </div>
    </div>
  )
}
