import * as React from "react"

import { StatusDot, type HealthTone } from "./display"
import { cn } from "../../lib/utils"

/**
 * Transient feedback for write operations.
 *
 * Every screen in this app performs writes — saving a camera, toggling a
 * camera on, releasing a session — and a write with no visible result is
 * indistinguishable from a write that silently failed. This is deliberately
 * dependency-free: the requirement is "say what happened", and a provider
 * plus a stack is the whole of it.
 *
 * Errors stay until dismissed. Success messages expire on their own, because
 * a confirmation that outstays its welcome becomes the thing you stop
 * reading — including the failures.
 */

export type ToastTone = "online" | "degraded" | "offline"

export interface Toast {
  id: number
  tone: ToastTone
  title: string
  detail?: string
  /** Milliseconds; `null` keeps the toast until it is dismissed. */
  duration: number | null
}

interface ToastApi {
  push: (toast: Omit<Toast, "id">) => number
  dismiss: (id: number) => void
}

const ToastContext = React.createContext<ToastApi | null>(null)

export function useToast(): ToastApi {
  const context = React.useContext(ToastContext)
  if (!context) {
    throw new Error("useToast must be used inside <ToastProvider>")
  }
  return context
}

/** Convenience wrappers so call sites read as intent, not as styling. */
export function useNotify() {
  const { push } = useToast()
  return React.useMemo(
    () => ({
      success: (title: string, detail?: string) =>
        push({ tone: "online", title, detail, duration: 3_000 }),
      error: (title: string, detail?: string) =>
        push({ tone: "offline", title, detail, duration: null }),
      warning: (title: string, detail?: string) =>
        push({ tone: "degraded", title, detail, duration: 6_000 }),
    }),
    [push],
  )
}

const DEFAULT_LIMIT = 4

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([])
  const nextId = React.useRef(1)
  const timers = React.useRef(new Map<number, ReturnType<typeof setTimeout>>())

  const dismiss = React.useCallback((id: number) => {
    const timer = timers.current.get(id)
    if (timer !== undefined) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const push = React.useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = nextId.current++
      setToasts((current) => {
        const next = [...current, { ...toast, id }]
        // Older success notices give way first; a failure never does.
        return next.length > DEFAULT_LIMIT
          ? next.slice(next.length - DEFAULT_LIMIT)
          : next
      })
      if (toast.duration !== null) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), toast.duration),
        )
      }
      return id
    },
    [dismiss],
  )

  React.useEffect(() => {
    const pending = timers.current
    return () => {
      for (const timer of pending.values()) clearTimeout(timer)
      pending.clear()
    }
  }, [])

  const api = React.useMemo(() => ({ push, dismiss }), [push, dismiss])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2"
        role="region"
        aria-label="通知"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            aria-live={toast.tone === "offline" ? "assertive" : "polite"}
            className={cn(
              "pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-card px-3 py-2.5 shadow-lg",
              toast.tone === "online" && "border-status-online/30",
              toast.tone === "degraded" && "border-status-degraded/30",
              toast.tone === "offline" && "border-status-offline/40",
            )}
          >
            <StatusDot tone={toast.tone as HealthTone} className="mt-1.5" />
            <div className="min-w-0 flex-1 text-xs">
              <p className="font-medium">{toast.title}</p>
              {toast.detail ? (
                <p className="mt-0.5 break-words text-muted-foreground">
                  {toast.detail}
                </p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="关闭通知"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
