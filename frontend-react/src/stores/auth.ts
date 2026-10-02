import { create } from "zustand"
import * as authApi from "../api/auth"
import type { AuthUser, RoleName } from "../api/auth"
import { ApiError } from "../api/client"
import { ROLES } from "../api/auth"

export type AuthStatus =
  | "bootstrapping"
  | "needs-setup"
  | "anonymous"
  | "authenticated"

/** Ordered so `atLeast` is a simple index comparison. */
const RANK: Record<RoleName, number> = {
  [ROLES.VIEWER]: 0,
  [ROLES.OPERATOR]: 1,
  [ROLES.ADMIN]: 2,
}

function messageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return fallback
}

type AuthState = {
  status: AuthStatus
  user: AuthUser | null
  /** Form-level error (bad credentials, weak password). Rendered inline. */
  error: string | null
  /**
   * Set only when the backend itself is unreachable during bootstrap. Kept
   * apart from `error` because a failed login must not replace the whole
   * app with a "cannot reach backend" screen.
   */
  bootstrapError: string | null
  busy: boolean

  bootstrap: () => Promise<void>
  login: (username: string, password: string) => Promise<boolean>
  logout: () => Promise<void>
  createInitialAdministrator: (
    input: authApi.InitialAdministratorCreate,
  ) => Promise<boolean>

  hasRole: (role: RoleName) => boolean
  atLeast: (role: RoleName) => boolean
  /** Used after endpoints that return the updated user (e.g. password change). */
  setUser: (user: AuthUser) => void
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  status: "bootstrapping",
  user: null,
  error: null,
  bootstrapError: null,
  busy: false,

  /**
   * Order matters and mirrors the Vue router guard: setup first, then
   * session. A deployment with no administrator must never render the app
   * shell, because every other endpoint would just 401.
   */
  async bootstrap() {
    set({ status: "bootstrapping", error: null, bootstrapError: null })
    try {
      const setup = await authApi.setupStatus()
      if (setup.requires_initial_admin) {
        set({ status: "needs-setup", user: null })
        return
      }
    } catch (err) {
      // A backend that is down must not be reported as "please set up an
      // admin" — that would send the user to a form that cannot work.
      set({
        status: "anonymous",
        bootstrapError: `无法连接后端：${messageOf(err, "服务不可用")}`,
      })
      return
    }

    try {
      const user = await authApi.me()
      set({ status: "authenticated", user, error: null })
    } catch {
      // A 401 here is the normal "no session yet" answer, not a failure.
      set({ status: "anonymous", user: null })
    }
  },

  async login(username, password) {
    set({ busy: true, error: null })
    try {
      const user = await authApi.login({ username, password })
      set({ status: "authenticated", user, busy: false, error: null })
      return true
    } catch (err) {
      set({ busy: false, error: messageOf(err, "登录失败") })
      return false
    }
  },

  async logout() {
    set({ busy: true })
    try {
      await authApi.logout()
    } catch {
      // Even if the revoke call fails the local session must be dropped;
      // leaving the UI "logged in" on a dead cookie is worse.
    }
    set({ status: "anonymous", user: null, busy: false })
  },

  async createInitialAdministrator(input) {
    set({ busy: true, error: null })
    try {
      const user = await authApi.createInitialAdministrator(input)
      set({ status: "authenticated", user, busy: false, error: null })
      return true
    } catch (err) {
      set({ busy: false, error: messageOf(err, "创建失败") })
      return false
    }
  },

  hasRole(role) {
    return get().user?.roles.includes(role) ?? false
  },

  atLeast(role) {
    const roles = get().user?.roles ?? []
    const floor = RANK[role]
    return roles.some((r) => (RANK[r as RoleName] ?? -1) >= floor)
  },

  setUser(user) {
    set({ user, status: "authenticated" })
  },
}))

/** Non-hook access for the router and guards. */
export const authState = () => useAuthStore.getState()
