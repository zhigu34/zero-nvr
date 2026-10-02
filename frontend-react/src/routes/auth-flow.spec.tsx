import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { AuthGate } from "../components/AuthGate"
import { createMemoryHistory } from "@tanstack/react-router"
import { createAppRouter, type AppRouter } from "./router"
import { ROLES } from "../api/auth"
import { useAuthStore } from "../stores/auth"

/**
 * End-to-end shape of the auth flow against a stubbed backend: bootstrap →
 * guard redirect → login → landing page. Deliberately drives the real store
 * and the real route tree rather than mocking them, because the parts most
 * likely to break are the hand-offs between them.
 */

type Route = { method: string; path: string; body?: unknown; status?: number }

function stubFetch(routes: Route[]) {
  const calls: string[] = []
  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? "GET"
    calls.push(`${method} ${url}`)
    const match = routes.find(
      (r) => r.method === method && url.endsWith(r.path),
    )
    if (!match) {
      return new Response(
        JSON.stringify({
          error: { code: "not_stubbed", message: `no stub for ${url}`, details: {} },
        }),
        { status: 501, headers: { "Content-Type": "application/json" } },
      )
    }
    return new Response(
      match.body === undefined ? null : JSON.stringify(match.body),
      {
        status: match.status ?? 200,
        headers: { "Content-Type": "application/json" },
      },
    )
  })
  vi.stubGlobal("fetch", impl)
  return calls
}

const admin = {
  id: "11111111-1111-1111-1111-111111111111",
  username: "admin",
  display_name: "系统管理员",
  email: null,
  email_verified: false,
  roles: [ROLES.ADMIN],
  permissions: ["*"],
}

const viewer = { ...admin, id: "2222", username: "guest", roles: [ROLES.VIEWER] }

/**
 * Renders the real composition from main.tsx: the auth gate owns the session
 * bootstrap and only then hands off to the router, so testing the gate is
 * the only way to cover the ordering that production depends on.
 */
/** Per-test router, so no navigation state leaks between cases. */
let current: AppRouter

function mountApp(path = "/") {
  current = createAppRouter(
    createMemoryHistory({ initialEntries: [path] }),
  )
  return render(<AuthGate router={current} />)
}

function currentPath() {
  return current.state.location.pathname
}

beforeEach(() => {
  useAuthStore.setState({
    status: "bootstrapping",
    user: null,
    error: null,
    bootstrapError: null,
    busy: false,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("bootstrap", () => {
  it("routes an anonymous visitor to /login", async () => {
    stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: false } },
      {
        method: "GET",
        path: "/auth/me",
        status: 401,
        body: { error: { code: "unauthenticated", message: "no session", details: {} } },
      },
    ])
    mountApp()
    await waitFor(() => expect(currentPath()).toBe("/login"))
  })

  it("sends a deployment with no admin to /setup, not /login", async () => {
    stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: true } },
    ])
    mountApp("/live")
    await waitFor(() => expect(currentPath()).toBe("/setup"))
  })

  it("never calls /auth/me when setup is still required", async () => {
    const calls = stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: true } },
    ])
    mountApp()
    await waitFor(() => expect(calls.length).toBeGreaterThan(0))
    expect(calls.some((c) => c.includes("/auth/me"))).toBe(false)
  })

  it("accepts an existing session without a login round-trip", async () => {
    stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: false } },
      { method: "GET", path: "/auth/me", body: admin },
    ])
    mountApp()
    await waitFor(() => expect(currentPath()).toBe("/live"))
  })
})

describe("login", () => {
  it("surfaces the backend error message on bad credentials", async () => {
    stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: false } },
      {
        method: "GET",
        path: "/auth/me",
        status: 401,
        body: { error: { code: "unauthenticated", message: "no session", details: {} } },
      },
      {
        method: "POST",
        path: "/auth/login",
        status: 401,
        body: {
          error: {
            code: "invalid_credentials",
            message: "Invalid username or password.",
            details: {},
          },
        },
      },
    ])
    mountApp("/")
    await screen.findByLabelText("用户名")

    await act(async () => {
      fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } })
      fireEvent.change(screen.getByLabelText("密码"), { target: { value: "wrong-password" } })
    })
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /登录/ }))
    })

    await screen.findByRole("alert")
    expect(screen.getByText("Invalid username or password.")).toBeTruthy()
  })

  it("lands an Administrator on the first module they can open", async () => {
    stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: false } },
      {
        method: "GET",
        path: "/auth/me",
        status: 401,
        body: { error: { code: "unauthenticated", message: "no session", details: {} } },
      },
      { method: "POST", path: "/auth/login", body: admin },
    ])
    mountApp()
    await screen.findByLabelText("用户名")

    await act(async () => {
      fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } })
      fireEvent.change(screen.getByLabelText("密码"), { target: { value: "correct-password" } })
    })
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /登录/ }))
    })

    await waitFor(() => expect(currentPath()).toBe("/live"))
    expect(useAuthStore.getState().user?.username).toBe("admin")
  })
})

describe("role gate on a shared shell", () => {
  it("bounces a Viewer away from an Administrator-only module", async () => {
    stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: false } },
      { method: "GET", path: "/auth/me", body: viewer },
    ])
    mountApp("/users")
    await waitFor(() => expect(currentPath()).toBe("/forbidden"))
  })

  it("keeps Administrator-only modules out of a Viewer's sidebar", async () => {
    stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: false } },
      { method: "GET", path: "/auth/me", body: viewer },
    ])
    mountApp()
    await screen.findByRole("link", { name: /实时监控/ })

    expect(screen.queryByRole("link", { name: /用户与权限/ })).toBeNull()
    expect(screen.queryByRole("link", { name: /审计日志/ })).toBeNull()
    expect(screen.queryByRole("link", { name: /^存储/ })).toBeNull()
    // ...but the pages a Viewer can read are present.
    expect(screen.getByRole("link", { name: /实时监控/ })).toBeTruthy()
    expect(screen.getByRole("link", { name: /录像回放/ })).toBeTruthy()
  })

  it("shows an Administrator every module", async () => {
    stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: false } },
      { method: "GET", path: "/auth/me", body: admin },
    ])
    mountApp()
    await screen.findByRole("link", { name: /实时监控/ })
    expect(screen.getByRole("link", { name: /用户与权限/ })).toBeTruthy()
    expect(screen.getByRole("link", { name: /审计日志/ })).toBeTruthy()
  })
})

describe("layout modes", () => {
  it("marks a media page immersive and a settings page standard", async () => {
    stubFetch([
      { method: "GET", path: "/setup/status", body: { requires_initial_admin: false } },
      { method: "GET", path: "/auth/me", body: admin },
    ])
    mountApp()
    await waitFor(() => expect(currentPath()).toBe("/live"))
    await waitFor(() =>
      expect(document.querySelector("main")?.getAttribute("data-layout")).toBe("immersive"),
    )

    const systemLink = screen.getByRole("link", { name: /系统设置/ })
    await act(async () => {
      fireEvent.click(systemLink)
    })
    await waitFor(() =>
      expect(document.querySelector("main")?.getAttribute("data-layout")).toBe("standard"),
    )
  })
})
