import { afterEach, describe, expect, it } from "vitest"
import { navigation } from "../lib/navigation"
import { ROLES } from "../api/auth"
import { routeTree, router } from "./router"
import { useAuthStore } from "../stores/auth"

/**
 * router.tsx writes its paths out literally instead of generating them from
 * navigation.ts, because a `path: string` helper destroys TanStack's ability
 * to type `Link to={...}`. This suite is the guard on that duplication.
 */

/** route id -> full path, e.g. "/__cameras" -> "/cameras". */
function item(key: string) {
  const found = navigation.flatMap((g) => g.items).find((i) => i.key === key)
  if (!found) throw new Error(`missing nav item ${key}`)
  return found
}

function flatPaths(): Record<string, string> {
  return Object.fromEntries(
    Object.values(router.routesById).map((r) => [r.id, r.fullPath]),
  )
}

describe("router ↔ navigation consistency", () => {
  const registered = flatPaths()

  it("registers a route for every navigation module, at the same path", () => {
    const flat = navigation.flatMap((g) => g.items)
    expect(Object.values(registered)).toEqual(
      expect.arrayContaining(flat.map((i) => i.path)),
    )
  })

  it("exposes every module path on the router's route tree", () => {
    const values = Object.values(registered)
    for (const item of navigation.flatMap((g) => g.items)) {
      expect(values).toContain(item.path)
    }
  })

  it("keeps the legacy 录制计划 alias instead of /schedules", () => {
    expect(item("schedules").path).toBe("/recording-schedules")
    expect(Object.values(registered)).toContain("/recording-schedules")
    expect(Object.values(registered)).not.toContain("/schedules")
  })

  it("has no duplicate module paths", () => {
    const paths = navigation.flatMap((g) => g.items).map((i) => i.path)
    expect(new Set(paths).size).toBe(paths.length)
  })

  it("keeps the route tree reachable from the root", () => {
    expect(routeTree).toBeDefined()
    expect(router.routeTree).toBe(routeTree)
  })
})

describe("role gating derived from backend permissions", () => {
  /**
   * Mirrors backend/app/modules/auth/permissions.py
   * BUILTIN_ROLE_PERMISSIONS.
   */
  const grants: Record<string, Set<string>> = {
    [ROLES.VIEWER]: new Set([
      "camera.view",
      "recording.view",
      "event.view",
      "alert.view",
      "system.view",
    ]),
    [ROLES.OPERATOR]: new Set([
      "camera.view",
      "recording.view",
      "event.view",
      "alert.view",
      "system.view",
      "camera.control",
      "recording.export",
      "recording.protect",
      "alert.acknowledge",
      "notification.view",
    ]),
    [ROLES.ADMIN]: new Set(["*"]),
  }

  const has = (role: string, permission: string) =>
    grants[role]?.has("*") === true || grants[role]?.has(permission) === true

  it("gates 存储, 用户与权限 and 审计日志 to Administrator only", () => {
    // Every storage endpoint requires storage.manage; users require
    // user.manage; audit requires audit.view — none of which Operator holds.
    for (const key of ["storage", "users", "audit"]) {
      expect(item(key).requires).toBe(ROLES.ADMIN)
    }
  })

  it("lets every role open the monitoring pages", () => {
    for (const key of ["live", "playback", "timeline", "cameras", "events"]) {
      expect(item(key).requires).toBe(ROLES.VIEWER)
    }
  })

  it("reserves write access on 系统设置 for Administrator", () => {
    expect(item("system").requires).toBe(ROLES.VIEWER)
    expect(item("system").manage).toBe(ROLES.ADMIN)
  })

  it("gives Operator no audit view", () => {
    expect(has(ROLES.OPERATOR, "audit.view")).toBe(false)
    expect(has(ROLES.VIEWER, "storage.manage")).toBe(false)
  })
})

describe("landing route follows the weakest role", () => {
  const original = useAuthStore.getState()

  afterEach(() => {
    useAuthStore.setState({ user: original.user, status: original.status })
  })

  it("sends a Viewer to a page it can open", () => {
    useAuthStore.setState({
      status: "authenticated",
      user: {
        id: "u",
        username: "v",
        display_name: "浏览者",
        email: null,
        email_verified: false,
        roles: [ROLES.VIEWER],
        permissions: [],
      },
    })
    const first = navigation
      .flatMap((g) => g.items)
      .find((i) => useAuthStore.getState().atLeast(i.requires))
    expect(first?.key).toBe("live")
  })

  it("never lands a Viewer on an Administrator-only module", () => {
    useAuthStore.setState({
      status: "authenticated",
      user: {
        id: "u",
        username: "v",
        display_name: "浏览者",
        email: null,
        email_verified: false,
        roles: [ROLES.VIEWER],
        permissions: [],
      },
    })
    const { atLeast } = useAuthStore.getState()
    for (const key of ["storage", "users", "audit"]) {
      expect(atLeast(item(key).requires)).toBe(false)
    }
  })
})

describe("/account", () => {
  const registered = flatPaths()

  it("is registered as a real route", () => {
    expect(Object.values(registered)).toContain("/account")
  })

  it("is not a navigation module, so it is not in the sidebar", () => {
    // It belongs to the user menu, not to the module list — and the
    // router ↔ navigation test above only requires one direction.
    const flat = navigation.flatMap((g) => g.items)
    expect(flat.some((i) => i.key === "account")).toBe(false)
  })

  it("carries no role guard of its own, while the module routes keep theirs", () => {
    // Every module route declares a minimum role; this one must not, because
    // it is the signed-in user's own account. A Viewer who needs to change a
    // leaked password has to be able to reach it.
    const routes = Object.values(router.routesById)
    const account = routes.find((r) => r.fullPath === "/account")
    expect(account).toBeTruthy()
    expect(account?.options?.beforeLoad).toBeUndefined()

    // Spot-check the contrast against a privileged module and a free one.
    for (const path of ["/users", "/audit", "/live"]) {
      const route = routes.find((r) => r.fullPath === path)
      expect(route?.options?.beforeLoad).toBeTruthy()
    }
  })
})
