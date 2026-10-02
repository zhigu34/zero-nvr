import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuditView } from "./AuditView"
import { renderWithProviders } from "../test-utils"
import type { AuditEventView } from "../api/audit"
import type { UserAdminView } from "../api/users"

/**
 * The audit log's one real design constraint: it identifies people and
 * cameras by UUID, and the names live in other, separately-permissioned
 * endpoints. Everything below is about not over-claiming what the payload
 * does or does not contain.
 */

const USER: UserAdminView = {
  id: "u1",
  username: "admin",
  display_name: "管理员",
  email: null,
  email_verified: false,
  enabled: true,
  roles: [],
}

function entry(over: Partial<AuditEventView> = {}): AuditEventView {
  return {
    id: "a1",
    occurred_at: new Date(Date.now() - 60_000).toISOString(),
    actor_type: "user",
    actor_id: "u1",
    action: "export.create",
    resource_type: "export",
    resource_id: "e1",
    camera_id: "c1",
    request_id: null,
    correlation_id: null,
    source_ip: "10.0.0.1",
    client_info: null,
    result: "SUCCESS",
    reason: null,
    before: null,
    after: null,
    metadata: null,
    ...over,
  }
}

type Call = { url: string }

function stubApi(
  overrides: {
    items?: AuditEventView[]
    usersOk?: boolean
    nextCursor?: string | null
  } = {},
) {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push({ url })
      if (url.includes("/api/v1/audit")) {
        return json({
          items: overrides.items ?? [entry()],
          next_cursor: overrides.nextCursor ?? null,
        })
      }
      if (url.includes("/api/v1/users")) {
        return overrides.usersOk === false
          ? new Response(
              JSON.stringify({
                error: { code: "forbidden", message: "nope" },
              }),
              { status: 403, headers: { "Content-Type": "application/json" } },
            )
          : json([USER])
      }
      if (url.includes("/api/v1/cameras")) return json([])
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
  return renderWithProviders(<AuditView />, { client })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("列表", () => {
  it("joins the actor name in memory rather than showing a blank", async () => {
    stubApi()
    renderView()
    expect(await screen.findByText("export.create")).toBeTruthy()
    // `actor_id` is a UUID; the name comes from the separately-permissioned
    // `/users`. An empty cell would read as "this action had no actor".
    expect(screen.getAllByText(/管理员/).length).toBeGreaterThan(0)
  })

  it("falls back to the raw id when the user list is unavailable", async () => {
    stubApi({ usersOk: false })
    renderView()
    expect(await screen.findByText("export.create")).toBeTruthy()
    // Showing the id beats showing nothing: "no name" and "no actor" are
    // different claims.
    expect(screen.getByText(/u1/)).toBeTruthy()
    expect(screen.getByText(/无法读取用户列表/)).toBeTruthy()
  })

  it("groups actions without hiding the full string", async () => {
    stubApi({ items: [entry(), entry({ id: "a2", action: "user.create" })] })
    renderView()
    await screen.findByText("export.create")
    expect(screen.getByText("导出")).toBeTruthy()
    expect(screen.getByText("用户与角色")).toBeTruthy()
  })

  it("surfaces a denied result as such", async () => {
    stubApi({
      items: [entry({ result: "DENIED", reason: "camera scope" })],
    })
    renderView()
    await screen.findByText("export.create")
    // "拒绝" also labels an <option> in the result filter, so wait for the
    // row before asserting on its own contents.
    expect(screen.getAllByText("拒绝").length).toBeGreaterThan(0)
    expect(screen.getByText("camera scope")).toBeTruthy()
  })

  it("says so when the filters match nothing", async () => {
    stubApi({ items: [] })
    renderView()
    expect(await screen.findByText("该条件下没有记录")).toBeTruthy()
  })
})

describe("筛选", () => {
  it("filters on the server, not by hiding rows in the page", async () => {
    const calls = stubApi()
    renderView()
    await screen.findByText("export.create")

    fireEvent.change(screen.getByLabelText("按操作筛选"), {
      target: { value: "export.share" },
    })
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("action=export.share"))).toBe(true),
    )
    // Everything is already narrowed by `action=`; no client-side pass exists.
    expect(calls.at(-1)?.url).toContain("limit=100")
  })

  it("sends the time window as a from bound", async () => {
    const calls = stubApi()
    renderView()
    await screen.findByText("export.create")

    await waitFor(() => expect(calls.some((c) => c.url.includes("from="))).toBe(true))
    expect(calls.find((c) => c.url.includes("/api/v1/audit?"))?.url).toContain("from=")
  })

  it("drops the time bound when 全部 is chosen", async () => {
    const calls = stubApi()
    renderView()
    await screen.findByText("export.create")
    fireEvent.change(screen.getByLabelText("时间范围"), { target: { value: "all" } })
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/api/v1/audit?") && !c.url.includes("from="))).toBe(
        true,
      ),
    )
  })
})

describe("分页", () => {
  it("follows the cursor rather than offering a page number", async () => {
    const calls = stubApi({ nextCursor: "cur-2" })
    renderView()
    await screen.findByText("export.create")
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }))
    await waitFor(() => expect(calls.some((c) => c.url.includes("cursor=cur-2"))).toBe(true))
    expect(screen.queryByText(/第 \d+ 页/)).toBeNull()
  })
})

describe("详情", () => {
  it("diffs only the fields that actually changed", async () => {
    stubApi({
      items: [
        entry({
          before: { name: "旧", enabled: true },
          after: { name: "新", enabled: true },
        }),
      ],
    })
    renderView()
    fireEvent.click(await screen.findByText("export.create"))

    expect(await screen.findByText("name")).toBeTruthy()
    // `enabled` is identical on both sides; listing it would be noise.
    expect(screen.queryByText("enabled")).toBeNull()
    expect(screen.getByText("变更前")).toBeTruthy()
    expect(screen.getByText("变更后")).toBeTruthy()
  })

  it("says when the backend recorded no snapshot at all", async () => {
    stubApi({ items: [entry({ before: null, after: null })] })
    renderView()
    fireEvent.click(await screen.findByText("export.create"))
    // The payload cannot tell this apart from an empty diff, so the panel
    // says which one it is rather than rendering nothing.
    expect(await screen.findByText(/后端未记录该操作的字段快照/)).toBeTruthy()
  })

  it("says when the snapshot exists but nothing in it changed", async () => {
    stubApi({ items: [entry({ before: { a: 1 }, after: { a: 1 } })] })
    renderView()
    fireEvent.click(await screen.findByText("export.create"))
    expect(await screen.findByText(/前后快照内容相同/)).toBeTruthy()
  })

  it("shows the identifiers an incident report needs", async () => {
    stubApi({
      items: [
        entry({
          request_id: "req-77",
          correlation_id: "corr-88",
          source_ip: "10.0.0.9",
        }),
      ],
    })
    renderView()
    fireEvent.click(await screen.findByText("export.create"))
    expect(await screen.findByText("req-77")).toBeTruthy()
    expect(screen.getByText("corr-88")).toBeTruthy()
    expect(screen.getByText("10.0.0.9")).toBeTruthy()
  })
})
