import * as React from "react"
import { Button } from "./primitives"

/**
 * The single confirmation prompt for destructive actions.
 *
 * Ported from the Vue `useConfirm` + `ConfirmDialog` pair, and for the same
 * reasons that pair existed:
 *
 * 1. **`window.confirm` is not a confirmation.** It blocks the main thread,
 *    cannot be styled or translated, and in some embedding contexts it is
 *    suppressed entirely — in which case it returns `false` *or* is ignored,
 *    and the action proceeds anyway. The Vue codebase had 15 call sites on
 *    it; replacing them was the point.
 * 2. **Falling back to "yes" is the one unacceptable default.** If no dialog
 *    host is mounted, this throws rather than assuming consent — an unanswered
 *    question must never become a destructive action. Throwing matches how
 *    `useNotify` behaves outside its `ToastProvider` in this app, and
 *    `test-utils` mounts the provider for every test.
 *
 * `role="alertdialog"` rather than `role="dialog"`: the prompt interrupts a
 * destructive flow and requires an explicit response.
 *
 * The pending prompt lives in context, so one mounted dialog serves every
 * caller and a call site reads as `if (await confirm({...})) doThing()`.
 */

export interface ConfirmOptions {
  /** Question shown to the operator. Should name the object being acted on. */
  message: string
  title?: string
  confirmLabel?: string
  cancelLabel?: string
  /** Style the confirm action as destructive. */
  danger?: boolean
}

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void }

const ConfirmContext = React.createContext<
  ((options: ConfirmOptions) => Promise<boolean>) | null
>(null)

export function useConfirm(): (options: ConfirmOptions) => Promise<boolean> {
  const confirm = React.useContext(ConfirmContext)
  if (!confirm) {
    throw new Error(
      "useConfirm() was called outside <ConfirmProvider>. A destructive " +
        "action must not fall back to assuming consent — mount the provider.",
    )
  }
  return confirm
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = React.useState<Pending | null>(null)

  const confirm = React.useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      setPending({ ...options, resolve })
    })
  }, [])

  const settle = React.useCallback(
    (ok: boolean) => {
      // Read `pending` through the updater so a second call landing in the
      // same tick cannot resolve the newer prompt with the older answer.
      setPending((current) => {
        current?.resolve(ok)
        return null
      })
    },
    [],
  )

  React.useEffect(() => {
    if (!pending) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") settle(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [pending, settle])

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-foreground/40 p-4"
          onClick={(event) => {
            // Backdrop click dismisses: an accidental click outside must not
            // be read as consent.
            if (event.target === event.currentTarget) settle(false)
          }}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-label={pending.title ?? pending.message}
            className="w-full max-w-sm rounded-lg border border-border bg-background p-4 shadow-lg"
          >
            {pending.title && (
              <p className="text-sm font-semibold">{pending.title}</p>
            )}
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              {pending.message}
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => settle(false)}>
                {pending.cancelLabel ?? "取消"}
              </Button>
              <Button
                size="sm"
                variant={pending.danger ? "destructive" : "default"}
                autoFocus
                onClick={() => settle(true)}
              >
                {pending.confirmLabel ?? "确认"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  )
}
