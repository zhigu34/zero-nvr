import { useEffect, useState } from "react"
import { RouterProvider } from "@tanstack/react-router"
import { createAppRouter, type AppRouter } from "../routes/router"
import { useAuthStore } from "../stores/auth"

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-4">
      {children}
    </div>
  )
}

/**
 * Resolves the session before the router mounts.
 *
 * Without this, every guarded route's `beforeLoad` would run once while the
 * status was still "bootstrapping", and the app would either bounce a signed
 * -in user to /login or render an empty shell before the cookie was read.
 */
export function AuthGate({ router: injected }: { router?: AppRouter } = {}) {
  const status = useAuthStore((s) => s.status)
  const bootstrap = useAuthStore((s) => s.bootstrap)
  const bootstrapError = useAuthStore((s) => s.bootstrapError)
  const [fallback] = useState(() => createAppRouter())
  const router = injected ?? fallback

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  if (status === "bootstrapping") {
    return (
      <Centered>
        <div className="flex flex-col items-center gap-3">
          <div className="size-8 animate-spin rounded-full border-2 border-muted border-t-primary" />
          <p className="text-xs text-muted-foreground">正在检查登录状态…</p>
        </div>
      </Centered>
    )
  }

  // A backend that is unreachable must be reported as such. Falling through
  // to the router would show a login form that cannot possibly succeed.
  if (bootstrapError) {
    return (
      <Centered>
        <div className="max-w-sm rounded-xl border border-destructive/30 bg-destructive/8 p-4 text-center">
          <p className="text-sm font-medium">无法连接后端</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{bootstrapError}</p>
          <button
            type="button"
            onClick={() => void bootstrap()}
            className="mt-3 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent"
          >
            重试
          </button>
        </div>
      </Centered>
    )
  }

  return <RouterProvider router={router} />
}
