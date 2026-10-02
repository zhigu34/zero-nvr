import { QueryClient } from "@tanstack/react-query"
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ApiTokensPanel } from "./ApiTokensPanel"
import { renderWithProviders } from "../../test-utils"
import { TOKENS } from "../../lib/queries"
import { useAuthStore } from "../../stores/auth"
import type { ApiTokenView } from "../../api/apiTokens"
import type { AuthUser } from "../../api/auth"

/**
 * Every test below is a statement about something the panel must *not* do.
 *
 * The panel's whole reason to exist is a value the server keeps for exactly one
 * response, plus three body keys whose wrong value is accepted by the API and
 * only noticed weeks later:
 *
 * 1. **The plaintext is shown once and then it is gone.** A test that asserted
 *    "the token appears" would pass on an implementation that also cached it in
 *    the query and re-rendered it on every visit — which is the one thing that
 *    must not happen, because the value no longer exists anywhere.
 * 2. **`permissions: null` and `permissions: []` are different requests**, and
 *    JSON cannot tell them apart at the call site: inherit is the *absent* key.
 * 3. **`expires_at` must carry an offset.** The bare `datetime-local` value the
 *    operator typed is a 400 (`api_token_expiry_invalid`), and "never expires"
 *    is the *absent* key rather than a null.
 *
 * The date constants are deliberately decades away from any plausible clock: an
 * expiry assertion written against a date near "now" starts failing on a
 * machine whose clock differs by a day, and this repo's dates are not 2026-10.
 */

const FUTURE = "2099-01-01T00:00:00Z"
const PAST = "2000-01-01T00:00:00Z"
/** What a `<input type="datetime-local">` can actually hold: no zone at all. */
const FUTURE_LOCAL = "2099-01-01T00:00"
const PAST_LOCAL = "2000-01-01T00:00"

const CREATED_AT = "2026-10-01T00:00:00Z"
const PLAINTEXT = "znr_pat_plaintext_that_exists_once"

/** A live token with a real expiry and one recorded use. */
const ACTIVE: ApiTokenView = {
  id: "tok-1",
  name: "grafana",
  permissions: ["camera.view", "recording.view"],
  created_at: CREATED_AT,
  expires_at: FUTURE,
  last_used_at: CREATED_AT,
  revoked_at: null,
}

/**
 * Legal and useless: `permissions: []` is a valid token that can do nothing,
 * which is why the row has to say so rather than render an empty scope.
 */
const USELESS: ApiTokenView = {
  id: "tok-2",
  name: "备份脚本",
  permissions: [],
  created_at: CREATED_AT,
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
}

const REVOKED: ApiTokenView = {
  id: "tok-3",
  name: "旧插件",
  permissions: ["camera.view"],
  created_at: CREATED_AT,
  expires_at: null,
  last_used_at: CREATED_AT,
  revoked_at: PAST,
}

const EXPIRED: ApiTokenView = {
  id: "tok-4",
  name: "临时排查",
  permissions: ["camera.view"],
  created_at: CREATED_AT,
  expires_at: PAST,
  last_used_at: null,
  revoked_at: null,
}

const USER: AuthUser = {
  id: "u1",
  username: "zhi",
  display_name: "Zhi",
  email: null,
  email_verified: true,
  roles: ["Administrator"],
  permissions: ["camera.view", "recording.view"],
}

type Call = { method: string; url: string; body: unknown }

let calls: Call[] = []
/** What the (fake) server currently holds; DELETE mutates it. */
let server: ApiTokenView[] = []
/** Set by a test to make the next write fail with a specific backend code. */
let failure: { status: number; code: string; message: string } | null = null

beforeEach(() => {
  useAuthStore.setState({ user: USER, status: "authenticated" })
})

afterEach(() => {
  // Unmount first. Vitest runs afterEach hooks in reverse registration order,
  // so resetting the store while the panel is still mounted would update a live
  // component outside `act` — once per test, and it drowns the real output.
  cleanup()
  calls = []
  server = []
  failure = null
  useAuthStore.setState({ user: null, status: "anonymous" })
  Reflect.deleteProperty(navigator, "clipboard")
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function renderPanel(tokens: ApiTokenView[] = [ACTIVE, USELESS]) {
  server = tokens.map((t) => ({ ...t }))
  calls = []

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(TOKENS.list, server)

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })

      if (method === "POST") {
        if (failure) {
          return json(
            { error: { code: failure.code, message: failure.message } },
            failure.status,
          )
        }
        const sent = (body ?? {}) as {
          name: string
          permissions?: string[]
          expires_at?: string
        }
        // The one response in the whole contract that carries the plaintext.
        return json(
          {
            id: "tok-new",
            name: sent.name,
            permissions: sent.permissions ?? USER.permissions,
            created_at: CREATED_AT,
            expires_at: sent.expires_at ?? null,
            last_used_at: null,
            revoked_at: null,
            token: PLAINTEXT,
          },
          201,
        )
      }

      if (method === "DELETE") {
        if (failure) {
          return json(
            { error: { code: failure.code, message: failure.message } },
            failure.status,
          )
        }
        const id = url.slice(url.lastIndexOf("/") + 1)
        server = server.map((t) =>
          t.id === id && !t.revoked_at ? { ...t, revoked_at: CREATED_AT } : t,
        )
        return new Response(null, { status: 204 })
      }

      if (url.includes("/api-tokens")) return json(server)
      return json({})
    }),
  )

  return renderWithProviders(<ApiTokensPanel />, { client })
}

function callsTo(fragment: string, method?: string) {
  return calls.filter(
    (c) => c.url.includes(fragment) && (!method || c.method === method),
  )
}

function createdBodies(): Record<string, unknown>[] {
  return callsTo("/api-tokens", "POST").map((c) => c.body as Record<string, unknown>)
}

/** The `Segmented` pairs and the permission box all carry a group name. */
function group(name: string) {
  return screen.getByRole("group", { name })
}

function choose(name: string, label: string) {
  fireEvent.click(within(group(name)).getByRole("button", { name: label }))
}

/**
 * A row, scoped to the list.
 *
 * Token names repeat — the same name can be typed into a new token, and the
 * reveal block names the token just created — so an unscoped text query is
 * ambiguous by construction rather than by accident.
 */
function tokenRow(name: string) {
  const list = screen.getByRole("list", { name: "令牌列表" })
  return within(list).getByText(name).closest("li") as HTMLElement
}

function toasts() {
  return within(screen.getByRole("region", { name: "通知" }))
}

async function submitCreate(name: string) {
  fireEvent.change(screen.getByLabelText("令牌名称"), { target: { value: name } })
  fireEvent.click(screen.getByRole("button", { name: "创建令牌" }))
}

/* -------------------------------------------------------------------------- */

describe("API 令牌 · 明文只出现一次", () => {
  it("明文在创建后显示一次，离开再回来就没有了", async () => {
    const { unmount, client } = renderPanel([ACTIVE])
    await submitCreate("grafana-2")

    expect(await screen.findByText(PLAINTEXT)).toBeTruthy()
    // Once, in one place. A cached copy would make this count grow.
    expect(screen.getAllByText(PLAINTEXT)).toHaveLength(1)
    // And not in a toast, which outlives the thing it announces.
    expect(toasts().queryByText(PLAINTEXT)).toBeNull()

    // Switching away and back is a remount: the list is re-read from the server,
    // which has no token field at all, so the plaintext cannot come back.
    unmount()
    renderWithProviders(<ApiTokensPanel />, { client })
    await screen.findByRole("list", { name: "令牌列表" })
    expect(screen.queryByText(PLAINTEXT)).toBeNull()
  })

  it("关掉提示后没有任何入口能再看一次明文", async () => {
    renderPanel()
    await submitCreate("grafana-2")
    await screen.findByText(PLAINTEXT)

    fireEvent.click(screen.getByRole("button", { name: "我已保存，关闭" }))
    expect(screen.queryByText(PLAINTEXT)).toBeNull()
    expect(
      screen.queryByRole("button", { name: /明文|重新显示|查看令牌/ }),
    ).toBeNull()
  })

  it("复制前警告已经在屏幕上，且复制的是明文本身", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    })
    renderPanel()
    await submitCreate("grafana-2")

    const warning = await screen.findByText(/关闭之后无法再次查看/)
    const copy = screen.getByRole("button", { name: /复制令牌/ })
    // The consequence is stated *before* the copy button, not after the fact.
    expect(
      warning.compareDocumentPosition(copy) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()

    fireEvent.click(copy)
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(PLAINTEXT))
    expect(await screen.findByRole("button", { name: /已复制/ })).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */

describe("API 令牌 · 权限范围的三种含义", () => {
  it("「同我当前权限」不发送 permissions 这个键——不是 null，也不是 []", async () => {
    renderPanel()
    await submitCreate("grafana-2")

    await waitFor(() => expect(createdBodies()).toHaveLength(1))
    const sent = createdBodies()[0]
    // The inherited request is the *absent* key. `[]` would mint a token that
    // can do nothing; `null` is not even expressible after JSON.stringify.
    expect(Object.hasOwn(sent, "permissions")).toBe(false)
  })

  it("手动选择与继承送出的是两种不同的请求", async () => {
    renderPanel()
    await submitCreate("grafana-2")
    await waitFor(() => expect(createdBodies()).toHaveLength(1))

    choose("权限范围", "手动选择")
    fireEvent.click(screen.getByRole("checkbox", { name: "camera.view" }))
    await submitCreate("narrow")
    await waitFor(() => expect(createdBodies()).toHaveLength(2))

    const [inherited, explicit] = createdBodies()
    expect(Object.hasOwn(inherited, "permissions")).toBe(false)
    expect(explicit.permissions).toEqual(["camera.view"])
  })

  it("选择器只列出当前账号已有的权限：超出的选择只会换来 403", () => {
    useAuthStore.setState({
      user: { ...USER, permissions: ["camera.view"] },
    })
    renderPanel()

    choose("权限范围", "手动选择")
    const picker = group("可选权限")
    expect(within(picker).getAllByRole("checkbox")).toHaveLength(1)
    expect(within(picker).getByRole("checkbox", { name: "camera.view" })).toBeTruthy()
    expect(within(picker).queryByRole("checkbox", { name: "user.manage" })).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("API 令牌 · 有效期", () => {
  it("指定到期时间时发出带时区偏移的 ISO，而不是屏幕上那串裸时间", async () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("令牌名称"), {
      target: { value: "grafana-2" },
    })
    choose("有效期", "指定到期时间")
    fireEvent.change(screen.getByLabelText("到期时间"), {
      target: { value: FUTURE_LOCAL },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建令牌" }))

    await waitFor(() => expect(createdBodies()).toHaveLength(1))
    const sent = createdBodies()[0]
    expect(String(sent.expires_at)).toMatch(/Z$|[+-]\d{2}:\d{2}$/)
    // The naive value the operator typed is exactly what the server rejects.
    expect(sent.expires_at).not.toBe(FUTURE_LOCAL)
  })

  it("「永不过期」根本不发送 expires_at 键", async () => {
    renderPanel()
    await submitCreate("grafana-2")

    await waitFor(() => expect(createdBodies()).toHaveLength(1))
    expect(Object.hasOwn(createdBodies()[0], "expires_at")).toBe(false)
  })

  it("过去的到期时间被挡住，不发请求", () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("令牌名称"), {
      target: { value: "grafana-2" },
    })
    choose("有效期", "指定到期时间")
    fireEvent.change(screen.getByLabelText("到期时间"), {
      target: { value: PAST_LOCAL },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建令牌" }))

    expect(screen.getByText("有效期必须是将来的时间")).toBeTruthy()
    expect(callsTo("/api-tokens", "POST")).toHaveLength(0)
  })

  it("选了「指定到期时间」却不填时间，不会悄悄变成永不过期", () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("令牌名称"), {
      target: { value: "grafana-2" },
    })
    choose("有效期", "指定到期时间")
    fireEvent.click(screen.getByRole("button", { name: "创建令牌" }))

    expect(screen.getByText("请选择到期时间，或改回「永不过期」。")).toBeTruthy()
    expect(callsTo("/api-tokens", "POST")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */

describe("API 令牌 · 提交前的本地校验", () => {
  it("空名称被挡住，不发请求", () => {
    renderPanel()
    fireEvent.click(screen.getByRole("button", { name: "创建令牌" }))

    expect(screen.getByText("请填写令牌名称")).toBeTruthy()
    expect(callsTo("/api-tokens", "POST")).toHaveLength(0)
  })

  it("超过 128 个字符的名称被挡住", () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("令牌名称"), {
      target: { value: "x".repeat(129) },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建令牌" }))

    expect(screen.getByText("名称最长 128 个字符")).toBeTruthy()
    expect(callsTo("/api-tokens", "POST")).toHaveLength(0)
  })

  it("手动选择但一个都不勾会被挡住——空列表是「什么都做不了」而不是「同我」", () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("令牌名称"), {
      target: { value: "grafana-2" },
    })
    choose("权限范围", "手动选择")
    fireEvent.click(screen.getByRole("button", { name: "创建令牌" }))

    expect(
      screen.getByText("一个权限都不给的话，这个令牌无法完成任何操作"),
    ).toBeTruthy()
    expect(callsTo("/api-tokens", "POST")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */

describe("API 令牌 · 吊销", () => {
  it("吊销不可逆，先确认；取消不删", async () => {
    renderPanel()
    fireEvent.click(within(tokenRow("grafana")).getByTitle("吊销"))

    const dialog = await screen.findByRole("alertdialog")
    expect(within(dialog).getByText(/确定吊销「grafana」？/)).toBeTruthy()
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull()
    })
    expect(callsTo("/api-tokens/tok-1", "DELETE")).toHaveLength(0)
  })

  it("确认后吊销，该行状态变成已吊销且不再提供吊销入口", async () => {
    renderPanel()
    fireEvent.click(within(tokenRow("grafana")).getByTitle("吊销"))
    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "吊销" }))

    await waitFor(() => {
      expect(callsTo("/api-tokens/tok-1", "DELETE")).toHaveLength(1)
    })
    await waitFor(() => {
      expect(within(tokenRow("grafana")).getByText("已吊销")).toBeTruthy()
    })
    expect(within(tokenRow("grafana")).queryByTitle("吊销")).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("API 令牌 · 列表是一份记录", () => {
  it("已吊销的令牌留在列表里，并且和有效令牌区分得开", () => {
    renderPanel([ACTIVE, REVOKED])

    const live = tokenRow("grafana")
    const dead = tokenRow("旧插件")
    expect(live.dataset.status).toBe("active")
    expect(dead.dataset.status).toBe("revoked")
    expect(within(live).getByText("有效")).toBeTruthy()
    expect(within(dead).getByText("已吊销")).toBeTruthy()
    // Only a live token can be revoked; the dead row offers nothing.
    expect(within(dead).queryByTitle("吊销")).toBeNull()
    // The revoke time is a real timestamp, not an empty one.
    expect(within(dead).getByText(/吊销于 /)).toBeTruthy()
  })

  it("已过期的令牌同样保留，并显示到期时间", () => {
    renderPanel([ACTIVE, EXPIRED])
    const row = tokenRow("临时排查")
    expect(row.dataset.status).toBe("expired")
    expect(within(row).getByText("已过期")).toBeTruthy()
    expect(within(row).getByText(/到期于 /)).toBeTruthy()
  })

  it("从未使用过的令牌说「从未使用」，不是一串空的「—」", () => {
    renderPanel([ACTIVE, USELESS])
    const row = tokenRow("备份脚本")
    expect(within(row).getByText(/从未使用/)).toBeTruthy()
    // `last_used_at: null` must not fall through to formatClock's "—".
    expect(row.textContent).not.toContain("—")
  })

  it("一个权限都不给的令牌说清楚它什么都做不了", () => {
    renderPanel([USELESS])
    const row = tokenRow("备份脚本")
    expect(within(row).getByText("无任何权限")).toBeTruthy()
    expect(within(row).getByText(/该令牌无法完成任何操作/)).toBeTruthy()
    // No expiry is a real, named state rather than a missing timestamp.
    expect(within(row).getByText(/永不过期/)).toBeTruthy()
  })

  it("列表里没有令牌值——读模型根本没有这个字段", () => {
    renderPanel([ACTIVE])
    expect(screen.getByRole("list", { name: "令牌列表" }).textContent).not.toContain(
      "znr_pat_",
    )
  })

  it("一个令牌都没有时给出说明，而不是空白", async () => {
    renderPanel([])
    expect(await screen.findByText("还没有 API 令牌")).toBeTruthy()
  })

  it("挂载时不发送任何写请求", async () => {
    renderPanel()
    await screen.findByRole("list", { name: "令牌列表" })
    expect(callsTo("/api-tokens", "POST")).toHaveLength(0)
    expect(callsTo("/api-tokens", "DELETE")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */

describe("API 令牌 · 写失败", () => {
  it("403 api_token_scope_invalid 给出中文解释，而不是后端的英文原文", async () => {
    failure = {
      status: 403,
      code: "api_token_scope_invalid",
      message: "requested permissions exceed creator scope",
    }
    renderPanel()
    await submitCreate("grafana-2")

    await waitFor(() => {
      expect(toasts().getByText("创建令牌失败")).toBeTruthy()
    })
    expect(
      toasts().getByText("令牌权限不能超过你当前的权限。请先移除非管理员专属的权限。"),
    ).toBeTruthy()
    expect(screen.queryByText("requested permissions exceed creator scope")).toBeNull()
    // A failed create has no plaintext to show.
    expect(screen.queryByText(PLAINTEXT)).toBeNull()
  })

  it("创建失败会说出来，且表单还能继续用", async () => {
    failure = { status: 400, code: "api_token_name_invalid", message: "name is invalid" }
    renderPanel()
    await submitCreate("grafana-2")

    await waitFor(() => {
      expect(toasts().getByText("创建令牌失败")).toBeTruthy()
    })
    expect(toasts().getByText("名称不能为空（最长 128 个字符）。")).toBeTruthy()
    // The panel is not left in a dead state: the operator's input survives and
    // a corrected retry goes through.
    expect((screen.getByLabelText("令牌名称") as HTMLInputElement).value).toBe(
      "grafana-2",
    )

    failure = null
    fireEvent.click(screen.getByRole("button", { name: "创建令牌" }))
    await waitFor(() => expect(callsTo("/api-tokens", "POST")).toHaveLength(2))
    expect(await screen.findByText(PLAINTEXT)).toBeTruthy()
  })
})
