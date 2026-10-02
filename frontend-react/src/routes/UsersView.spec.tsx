import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { UsersView } from "./UsersView"
import { renderWithProviders } from "../test-utils"
import { ADMIN } from "../lib/queries"
import type { UserAdminView } from "../api/users"

/**
 * The user screen is where a form can quietly lie: a username that cannot be
 * changed, an "enabled" flag that is not a field, and a reset token that
 * exists once. Each of those gets an assertion here.
 */

const ADMIN_USER: UserAdminView = {
  id: "u-admin",
  username: "admin",
  display_name: "管理员",
  email: "admin@example.com",
  email_verified: true,
  enabled: true,
  roles: [{ id: "r1", name: "Administrator", description: null, built_in: true }],
}

const OPERATOR: UserAdminView = {
  id: "u-op",
  username: "operator",
  display_name: "值班员",
  email: null,
  email_verified: false,
  enabled: false,
  roles: [{ id: "r2", name: "Operator", description: null, built_in: true }],
}

type Call = { url: string; method: string; body: unknown }

function stubApi(overrides: { users?: UserAdminView[]; resetToken?: string } = {}) {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })

      if (url.includes("/password-reset")) {
        return json({
          token: overrides.resetToken ?? "reset-tok",
          expires_at: "2026-10-09T00:00:00.000Z",
        })
      }
      if (url.includes("/camera-groups")) {
        return json([
          { id: "g1", name: "门口", description: null, parent_id: null, camera_ids: ["c1"] },
        ])
      }
      if (url.includes("/camera-scope")) {
        return json({ mode: "inherit", camera_ids: [], camera_group_ids: [] })
      }
      if (method !== "GET" && url.includes("/api/v1/users/")) return json(ADMIN_USER)
      if (url.includes("/api/v1/users")) {
        return json(overrides.users ?? [ADMIN_USER, OPERATOR])
      }
      if (url.includes("/api/v1/roles")) {
        return json([
          { id: "r1", name: "Administrator", description: null, built_in: true, permissions: ["user.manage"] },
          { id: "r2", name: "Operator", description: null, built_in: true, permissions: ["recording.view"] },
        ])
      }
      if (url.includes("/api/v1/cameras")) {
        return json([
          { id: "c1", name: "前门", enabled: true, maintenance: false, retired_at: null, location: null, storage_label: null, adapter_type: null, time_sync_mode: "monitor", ptz_capable: false, manufacturer: null, model: null, form_factor: "dome", ip: null, port: null, rtsp_path: null, sub_rtsp_path: null, video_codec: "H.264", width: null, height: null, fps: null, audio_codec: null, connectivity_status: "online", last_probe_at: null, last_online_at: null },
        ])
      }
      return json({})
    }),
  )
  return calls
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })
}

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return renderWithProviders(<UsersView />, { client })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("用户列表", () => {
  it("shows the real records, including a disabled one", async () => {
    stubApi()
    renderView()
    expect(await screen.findByText("值班员")).toBeTruthy()
    expect(screen.getByText("已禁用")).toBeTruthy()
    expect(screen.getAllByText("Operator").length).toBeGreaterThan(0)
  })

  it("does not reproduce the prototype's API-token and session tables", async () => {
    stubApi()
    renderView()
    await screen.findByText("值班员")
    // `/api-tokens` and `/sessions` are the signed-in user's own resources,
    // not an admin's view of somebody else. Offering them here would imply an
    // endpoint that does not exist.
    expect(screen.getByText(/API 令牌与会话不在本页/)).toBeTruthy()
  })
})

describe("编辑用户", () => {
  it("shows the username as read-only, because UserUpdate has no such field", async () => {
    stubApi()
    renderView()
    await screen.findByText("值班员")
    fireEvent.click(screen.getAllByTitle("编辑资料与角色")[1])
    expect((await screen.findAllByText(/创建后不可更改/)).length).toBeGreaterThan(0)
    // No input, so there is nothing to type a new username into.
    expect(screen.queryByLabelText("用户名")).toBeNull()
  })

  it("sends only the fields the PATCH accepts", async () => {
    const calls = stubApi()
    renderView()
    await screen.findByText("值班员")
    fireEvent.click(screen.getAllByTitle("编辑资料与角色")[1])
    fireEvent.change(await screen.findByLabelText("显示名"), {
      target: { value: "值班员二号" },
    })
    fireEvent.click(await screen.findByRole("button", { name: "保存" }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH")
      expect(patch).toBeTruthy()
      expect(Object.keys(patch!.body as object).sort()).toEqual([
        "display_name",
        "email",
        "role_ids",
      ])
    })
  })
})

describe("启停", () => {
  it("calls the dedicated endpoint rather than sending a field", async () => {
    const calls = stubApi()
    renderView()
    await screen.findByText("值班员")
    // The enabled user is first in the list; the disabled one is second.
    fireEvent.click(screen.getAllByTitle("禁用该用户")[0])
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/users/u-admin/disable"))).toBe(true),
    )
    // A PATCH carrying `enabled` would return 200 and change nothing.
    expect(calls.find((c) => c.method === "PATCH")).toBeUndefined()
  })
})

describe("密码重置", () => {
  it("shows the token once and says it cannot be fetched back", async () => {
    stubApi({ resetToken: "one-shot-token" })
    renderView()
    await screen.findByText("值班员")
    fireEvent.click(screen.getAllByTitle("签发密码重置令牌")[0])

    expect(await screen.findByText(/只显示这一次，无法再取回/)).toBeTruthy()
    expect(screen.getByText("one-shot-token")).toBeTruthy()
  })
})

describe("新建用户", () => {
  it("blocks a short password before the request", async () => {
    const calls = stubApi()
    renderView()
    await screen.findByText("值班员")
    fireEvent.click(screen.getByRole("button", { name: /新建用户/ }))

    fireEvent.change(await screen.findByLabelText("用户名"), {
      target: { value: "newuser" },
    })
    fireEvent.change(screen.getByLabelText("显示名"), {
      target: { value: "新人" },
    })
    fireEvent.change(screen.getByLabelText("初始密码"), {
      target: { value: "short" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建" }))

    expect(await screen.findByText(/密码至少 12 位/)).toBeTruthy()
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0)
  })

  it("rejects a username the backend's pattern would refuse", async () => {
    stubApi()
    renderView()
    await screen.findByText("值班员")
    fireEvent.click(screen.getByRole("button", { name: /新建用户/ }))

    fireEvent.change(await screen.findByLabelText("用户名"), {
      target: { value: "有中文" },
    })
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "新人" } })
    fireEvent.change(screen.getByLabelText("初始密码"), {
      target: { value: "a".repeat(12) },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建" }))

    expect(await screen.findByText(/只能包含字母、数字/)).toBeTruthy()
  })

  it("creates a user with no roles and says what that means", async () => {
    const calls = stubApi()
    renderView()
    await screen.findByText("值班员")
    fireEvent.click(screen.getByRole("button", { name: /新建用户/ }))

    fireEvent.change(await screen.findByLabelText("用户名"), {
      target: { value: "newuser" },
    })
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "新人" } })
    fireEvent.change(screen.getByLabelText("初始密码"), {
      target: { value: "a".repeat(12) },
    })
    // The consequence is stated up front: an empty role list is a valid
    // submission, not a mistake to be blocked.
    expect(screen.getByText(/不选任何角色时/)).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "创建" }))

    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/api/v1/users"))
      expect(post?.body).toMatchObject({ username: "newuser", role_ids: [] })
    })
  })
})

describe("机位范围", () => {
  it("is edited and saved separately from the profile", async () => {
    const calls = stubApi()
    renderView()
    await screen.findByText("值班员")
    fireEvent.click(screen.getAllByTitle("编辑资料与角色")[1])

    // The profile button and the scope button are distinct; a single merged
    // "Save" would make a partial failure ambiguous.
    const scopeSave = await screen.findByRole("button", { name: "保存范围" })
    expect(scopeSave).toHaveProperty("disabled", true)
    fireEvent.click(screen.getByRole("button", { name: "全部机位" }))
    fireEvent.click(await screen.findByRole("button", { name: "保存范围" }))

    await waitFor(() => {
      const put = calls.find((c) => c.method === "PUT")
      expect(put?.url).toContain("/camera-scope")
      // `all` carries no list; sending a stale selection would store ids the
      // scope never reads.
      expect(put?.body).toEqual({
        mode: "all",
        camera_ids: [],
        camera_group_ids: [],
      })
    })
  })

  it("offers camera groups, because they are a real part of the scope", async () => {
    // `CameraScopeUpdate.camera_group_ids` is first-class and `/camera-groups`
    // is a full CRUD resource. Writing `camera_group_ids: []` because "groups
    // are not implemented" would silently strip every group-scoped assignment.
    const calls = stubApi()
    renderView()
    await screen.findByText("值班员")
    fireEvent.click(screen.getAllByTitle("编辑资料与角色")[1])

    fireEvent.click(await screen.findByRole("button", { name: "指定机位" }))
    fireEvent.click(await screen.findByLabelText("机位组 门口"))
    fireEvent.click(await screen.findByRole("button", { name: "保存范围" }))

    await waitFor(() => {
      const put = calls.find((c) => c.method === "PUT")
      expect(put?.body).toMatchObject({
        mode: "selected",
        camera_group_ids: ["g1"],
      })
    })
  })

  it("warns that an empty selection grants no cameras", async () => {
    stubApi()
    renderView()
    await screen.findByText("值班员")
    fireEvent.click(screen.getAllByTitle("编辑资料与角色")[1])
    fireEvent.click(await screen.findByRole("button", { name: "指定机位" }))
    expect(await screen.findByText(/看不到任何机位/)).toBeTruthy()
  })
})
