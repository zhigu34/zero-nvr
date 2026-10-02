import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { BackupPanel } from "./BackupPanel"
import { renderWithProviders } from "../../test-utils"
import { BACKUPS, RECOVERY_KITS } from "../../lib/queries"
import type { BackupPolicyView, BackupSetView } from "../../api/backups"

/**
 * Every test here is a statement about a body.
 *
 * The backup API is full of places where "absent" and "present but empty" mean
 * different things, and the UI is the only place those are decided:
 * `schedule: {}` unschedules, a retention `0` is a real value, an empty
 * repository box must send no key at all, and a 503 that already committed a
 * row is not a failure. So the assertions are on the parsed request bodies and
 * on what the page says *before* the operator presses anything — never on
 * rendered values, which are cosmetic and would pass on a broken implementation.
 */

const POLICY: BackupPolicyView = {
  id: "p1",
  name: "每日全量",
  enabled: true,
  database_backend: "sqlite",
  schedule: { cron: "0 3 * * *", timezone: "Asia/Shanghai" },
  retention: { keep_daily: 7, keep_last: 5 },
  verify_after_backup: true,
  repository_check_schedule: {},
  include_deployment_config: false,
  repository_configured: true,
  credentials_configured: true,
}

const UNSCHEDULED: BackupPolicyView = {
  ...POLICY,
  id: "p2",
  name: "手动策略",
  schedule: {},
}

const SET_OK: BackupSetView = {
  id: "b1",
  backup_policy_id: "p1",
  state: "COMPLETED",
  reason: "scheduled",
  started_at: "2026-10-01T03:00:00Z",
  completed_at: "2026-10-01T03:04:00Z",
  app_version: "0.1.0",
  schema_revision: "12",
  database_engine: "sqlite",
  restic_snapshot_id: "snap-abc",
  size_bytes: 1048576,
  verification_state: "unknown",
  last_verified_at: null,
  error_code: null,
  sanitized_error: null,
  created_at: "2026-10-01T03:00:00Z",
}

const SET_FAILED: BackupSetView = {
  ...SET_OK,
  id: "b2",
  state: "FAILED",
  restic_snapshot_id: null,
  error_code: "backup_task_failed",
  sanitized_error: "repository unreachable",
}

const SET_NO_SNAPSHOT: BackupSetView = {
  ...SET_OK,
  id: "b3",
  state: "COMPLETED",
  restic_snapshot_id: null,
}

type Call = { method: string; url: string; body: unknown }

let calls: Call[] = []
/** Set per test to fail the next write with a specific backend code. */
let failure: { status: number; code: string; message: string; details?: unknown } | null = null
let setsPage: { items: BackupSetView[]; next_cursor: string | null } = {
  items: [SET_OK, SET_FAILED, SET_NO_SNAPSHOT],
  next_cursor: null,
}

// jsdom implements neither object-URL method. `vi.stubGlobal("URL", …)` would
// replace the whole constructor and break `new URL()` inside the api client, so
// the two methods are swapped in place and put back afterwards.
const realCreateObjectURL = URL.createObjectURL
const realRevokeObjectURL = URL.revokeObjectURL
const createObjectURL = vi.fn((_blob: Blob | MediaSource) => "blob:recovery-kit")
const revokeObjectURL = vi.fn((_url: string) => void 0)

beforeEach(() => {
  createObjectURL.mockClear()
  revokeObjectURL.mockClear()
  URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL
  URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL
})

afterEach(() => {
  URL.createObjectURL = realCreateObjectURL
  URL.revokeObjectURL = realRevokeObjectURL
  calls = []
  failure = null
  setsPage = { items: [SET_OK, SET_FAILED, SET_NO_SNAPSHOT], next_cursor: null }
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function renderPanel(policies: BackupPolicyView[] = [POLICY]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(BACKUPS.policies, policies)
  client.setQueryData(BACKUPS.sets({ policyId: undefined, cursor: undefined }), setsPage)
  client.setQueryData(RECOVERY_KITS.status(policies[0]?.id ?? ""), {
    status: "never_generated",
    policy_id: policies[0]?.id ?? "",
    generated_at: null,
    app_version: "0.1.0",
  })

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })

      if (method !== "GET") {
        if (failure) {
          return json(
            {
              error: {
                code: failure.code,
                message: failure.message,
                details: failure.details,
              },
            },
            failure.status,
          )
        }
        // The recovery kit answers with the archive itself.
        if (url.includes("/backups/recovery-kit")) {
          return new Response(new Blob([new Uint8Array([1, 2, 3])]), {
            status: 200,
            headers: {
              "Content-Type": "application/octet-stream",
              "Content-Disposition": 'attachment; filename="zero-nvr-recovery.znrk"',
            },
          })
        }
        return json({ id: "b9", state: "PENDING" })
      }
      if (url.includes("/backups/recovery-kit/status")) {
        return json({
          status: "never_generated",
          policy_id: "p1",
          generated_at: null,
          app_version: "0.1.0",
        })
      }
      // The list route is `/backups` exactly; `/backups/policies` is longer.
      if (url.includes("/backups/policies")) return json(policies)
      if (url.includes("/backups?")) return json(setsPage)
      if (url.includes("/system/settings")) {
        return json({ general: { display_timezone: "Asia/Shanghai" } })
      }
      return json({})
    }),
  )

  return renderWithProviders(<BackupPanel />, { client })
}

function callsTo(fragment: string, method?: string) {
  return calls.filter(
    (c) => c.url.includes(fragment) && (!method || c.method === method),
  )
}

/** A policy's row, scoped to the list — the name also appears in a filter. */
function policyRow(name: string) {
  const list = screen.getByRole("list", { name: "备份策略列表" })
  return within(list).getByText(name).closest("li") as HTMLElement
}

async function openEditorFor(name = "每日全量") {
  fireEvent.click(within(policyRow(name)).getByTitle("编辑"))
  await screen.findByText(/^编辑：/)
}

/** A named control group, already scoped for queries. */
function group(name: string) {
  return within(screen.getByRole("group", { name }))
}

function fillPolicyBasics() {
  fireEvent.change(screen.getByLabelText("策略名称"), { target: { value: "新策略" } })
  fireEvent.change(screen.getByLabelText("仓库地址"), {
    target: { value: "s3:s3.example.com/bucket" },
  })
}

function fillCredentials() {
  fireEvent.change(group("仓库凭据").getByLabelText("仓库密码"), {
    target: { value: "s3cret" },
  })
}

/* -------------------------------------------------------------------------- */

describe("备份 · 策略表单的请求体", () => {
  it("新建时同时发送仓库、凭据与 schedule/retention 对象", async () => {
    renderPanel([])
    fireEvent.click(screen.getByRole("button", { name: /新建策略/ }))
    fillPolicyBasics()
    fillCredentials()
    // The system zone lives in its own query, so it fills the draft in a tick
    // after the modal opens; wait for it rather than asserting a cold-start
    // UTC that no operator would ever save.
    const zone = screen.getByLabelText("备份计划 时区") as HTMLInputElement
    await waitFor(() => expect(zone.value).toBe("Asia/Shanghai"))
    fireEvent.change(group("备份计划").getByLabelText("备份计划 cron"), {
      target: { value: "0 4 * * *" },
    })
    fireEvent.change(screen.getByLabelText("每天 N 份"), { target: { value: "7" } })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(callsTo("/backups/policies", "POST")).toHaveLength(1)
    })
    const sent = callsTo("/backups/policies", "POST")[0].body as Record<string, unknown>
    expect(sent.name).toBe("新策略")
    expect(sent.repository).toBe("s3:s3.example.com/bucket")
    expect(sent.credentials).toEqual({ password: "s3cret", environment: {} })
    expect(sent.schedule).toEqual({ cron: "0 4 * * *", timezone: "Asia/Shanghai" })
    expect(sent.retention).toEqual({ keep_daily: 7 })
  })

  it("只改一个无关字段也要发送 schedule / retention / repository_check_schedule", async () => {
    renderPanel()
    await openEditorFor()
    // Rename only. A body that omitted the three objects could never express
    // "stop scheduling" — `{}` is the only way to say it.
    fireEvent.change(screen.getByLabelText("策略名称"), { target: { value: "改名了" } })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(1)
    })
    const sent = callsTo("/backups/policies/p1", "PATCH")[0].body as Record<string, unknown>
    expect(sent.name).toBe("改名了")
    expect(sent.schedule).toEqual({ cron: "0 3 * * *", timezone: "Asia/Shanghai" })
    expect(sent.retention).toEqual({ keep_daily: 7, keep_last: 5 })
    expect(sent).toHaveProperty("repository_check_schedule")
  })

  it("清空 cron 发送空 schedule 对象，并说明该策略不再按计划运行", async () => {
    renderPanel()
    await openEditorFor()

    fireEvent.change(group("备份计划").getByLabelText("备份计划 cron"), {
      target: { value: "" },
    })
    expect(
      screen.getByText("保存后该策略将不再按计划运行：清空 cron 会发送空的 schedule 对象，这是关闭调度的唯一方式。"),
    ).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() => {
      expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(1)
    })
    const sent = callsTo("/backups/policies/p1", "PATCH")[0].body as Record<string, unknown>
    expect(sent.schedule).toEqual({})
  })

  it("cron 没有时区时被挡住；五段 cron 加合法 IANA 时区才通过", async () => {
    renderPanel()
    await openEditorFor()

    fireEvent.change(group("备份计划").getByLabelText("备份计划 时区"), {
      target: { value: "" },
    })
    expect(screen.getByText("填写 cron 时必须同时指定时区")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(0)

    fireEvent.change(group("备份计划").getByLabelText("备份计划 时区"), {
      target: { value: "Asia/Shanghai" },
    })
    expect(screen.queryByText("填写 cron 时必须同时指定时区")).toBeNull()
  })

  it("保留份数 0 是有意义的值，空框则整个键被丢掉", async () => {
    renderPanel()
    await openEditorFor()

    fireEvent.change(screen.getByLabelText("每天 N 份"), { target: { value: "0" } })
    // keep_last and keep_daily were seeded from the view; blank the rest so the
    // only distinction left is "0 sent" vs "'' dropped".
    fireEvent.change(screen.getByLabelText("每小时 N 份"), { target: { value: "" } })
    fireEvent.change(screen.getByLabelText("每周 N 份"), { target: { value: "" } })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(1)
    })
    const sent = callsTo("/backups/policies/p1", "PATCH")[0].body as Record<
      string,
      Record<string, unknown>
    >
    expect(sent.retention.keep_daily).toBe(0)
    expect(sent.retention).not.toHaveProperty("keep_hourly")
    expect(sent.retention).not.toHaveProperty("keep_weekly")
    for (const value of Object.values(sent.retention)) {
      expect(value).not.toBe("")
    }
  })

  it("仓库地址里内嵌凭据被挡住，并指向凭据字段", async () => {
    renderPanel()
    await openEditorFor()
    fireEvent.change(screen.getByLabelText("仓库地址"), {
      target: { value: "s3://user:pass@s3.example.com/bucket" },
    })

    expect(
      screen.getByText("地址里不能内嵌用户名或密码，请用下方凭据填写"),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(0)
  })

  it("保留环境变量名 RESTIC_PASSWORD 被挡住，因为它由其它字段生成", async () => {
    renderPanel()
    await openEditorFor()
    fireEvent.click(group("仓库凭据").getByRole("button", { name: "替换" }))
    fireEvent.click(group("仓库凭据").getByRole("button", { name: /添加环境变量/ }))
    fireEvent.change(group("仓库凭据").getByLabelText("环境变量名 1"), {
      target: { value: "RESTIC_PASSWORD" },
    })
    fireEvent.change(group("仓库凭据").getByLabelText("仓库密码"), {
      target: { value: "s3cret" },
    })

    expect(screen.getByText("RESTIC_PASSWORD 由其它字段生成，不能手工填写")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(0)
  })

  it("合法环境变量名会随凭据一起整份发送", async () => {
    renderPanel()
    await openEditorFor()
    fireEvent.click(group("仓库凭据").getByRole("button", { name: "替换" }))
    fireEvent.click(group("仓库凭据").getByRole("button", { name: /添加环境变量/ }))
    fireEvent.change(group("仓库凭据").getByLabelText("环境变量名 1"), {
      target: { value: "AWS_ACCESS_KEY_ID" },
    })
    fireEvent.change(group("仓库凭据").getByLabelText("环境变量值 1"), {
      target: { value: "AKIA" },
    })
    fireEvent.change(group("仓库凭据").getByLabelText("仓库密码"), {
      target: { value: "s3cret" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(1)
    })
    const sent = callsTo("/backups/policies/p1", "PATCH")[0].body as Record<string, unknown>
    expect(sent.credentials_action).toBe("replace")
    expect(sent.credentials).toEqual({
      password: "s3cret",
      environment: { AWS_ACCESS_KEY_ID: "AKIA" },
    })
  })
})

/* -------------------------------------------------------------------------- */

describe("备份 · 只写凭据的三态", () => {
  it("编辑时凭据默认保持不变，请求体里没有任何 credentials 键", async () => {
    renderPanel()
    await openEditorFor()

    expect(group("仓库凭据").getByText("已配置")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(1)
    })
    const sent = callsTo("/backups/policies/p1", "PATCH")[0].body as Record<string, unknown>
    expect(sent).not.toHaveProperty("credentials")
  })

  it("清空凭据发送 clear 与 null，并说明策略永远跑不了、二次调用静默成功", async () => {
    renderPanel()
    await openEditorFor()
    fireEvent.click(group("仓库凭据").getByRole("button", { name: "清空" }))

    expect(
      screen.getByText(
        "清空后该策略将永远无法运行备份，也没有恢复已存密码的办法。再次执行同一步会成功但不改变任何东西。",
      ),
    ).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() => {
      expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(1)
    })
    const sent = callsTo("/backups/policies/p1", "PATCH")[0].body as Record<string, unknown>
    expect(sent.credentials_action).toBe("clear")
    expect(sent.credentials).toBeNull()
  })

  it("清空仓库地址框不发送 repository 键——它只能被替换", async () => {
    renderPanel()
    await openEditorFor()
    // The box starts empty on purpose: the stored URL is unreadable, so an
    // empty box is the untouched state, not a request to clear.
    expect((screen.getByLabelText("仓库地址") as HTMLInputElement).value).toBe("")
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(callsTo("/backups/policies/p1", "PATCH")).toHaveLength(1)
    })
    const sent = callsTo("/backups/policies/p1", "PATCH")[0].body as Record<string, unknown>
    expect(sent).not.toHaveProperty("repository")
  })

  it("没有凭据的策略在列表里就说出来，而不是等到运行时失败", async () => {
    renderPanel([{ ...POLICY, credentials_configured: false }])
    await screen.findByText("没有凭据的策略无法运行备份。")
  })
})

/* -------------------------------------------------------------------------- */

describe("备份 · 立即备份与校验", () => {
  it("立即备份发送 policy_id 与 manual，并说明返回的是排队行", async () => {
    renderPanel()
    expect(
      screen.getByText("备份由后台任务执行，入队即返回排队行，实际结果要等任务跑完才会变。"),
    ).toBeTruthy()

    fireEvent.click(within(policyRow("每日全量")).getByRole("button", { name: /立即备份/ }))
    await waitFor(() => {
      expect(callsTo("/backups/run", "POST")).toHaveLength(1)
    })
    expect(callsTo("/backups/run", "POST")[0].body).toEqual({
      policy_id: "p1",
      reason: "manual",
    })
    // The success toast says the same thing in the mutation's own words.
    await waitFor(() => {
      expect(screen.getByText("这是后台任务，返回的是排队状态而不是结果。")).toBeTruthy()
    })
  })

  it("503 且 details 带 backup_persisted 时说明已创建且不要重复触发", async () => {
    failure = {
      status: 503,
      code: "backup_task_queue_unavailable",
      message: "queue unavailable",
      details: { backup_persisted: true, backup_id: "b42" },
    }
    renderPanel()
    fireEvent.click(within(policyRow("每日全量")).getByRole("button", { name: /立即备份/ }))

    await waitFor(() => {
      expect(screen.getByText("备份已创建，但任务队列不可用")).toBeTruthy()
    })
    expect(
      screen.getByText(/备份记录已经存在（b42）.*请不要重复触发。/),
    ).toBeTruthy()
    // No automatic retry anywhere: the button is the only trigger, and the
    // row is not re-submitted after the toast.
    expect(callsTo("/backups/run", "POST")).toHaveLength(1)
    expect(screen.queryByRole("button", { name: /重试/ })).toBeNull()
  })

  it("校验只对已完成且有快照的备份开放", async () => {
    renderPanel()
    const list = await screen.findByRole("list", { name: "备份记录列表" })

    // Three sets: COMPLETED+snapshot (open), FAILED, COMPLETED without a
    // snapshot. The button is disabled — not hidden — so the reason stays
    // visible, and only the snapshot rule differs between the two closed ones.
    const open = within(list).getByRole("button", { name: "校验" })
    const closed = within(list).getAllByRole("button", { name: "不可校验" })
    expect((open as HTMLButtonElement).disabled).toBe(false)
    expect(closed).toHaveLength(2)
    for (const b of closed) expect((b as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(open)
    await waitFor(() => {
      expect(callsTo("/backups/b1/verify", "POST")).toHaveLength(1)
    })
    expect(callsTo("/backups/b1/verify", "POST")[0].body).toBeUndefined()
  })

  it("响应里出现请求枚举表达不了的 scheduled 时有中文说法", async () => {
    renderPanel()
    const list = await screen.findByRole("list", { name: "备份记录列表" })
    // All three rows were written by the scheduler, whose `"scheduled"` reason
    // is not a value any client can send.
    expect(within(list).getAllByText(/定时触发/)).toHaveLength(3)
    expect(within(list).queryByText("scheduled")).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("备份 · 列表读取失败与空状态", () => {
  it("策略读取失败给出可读的失败界面", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes("/backups/policies")) {
          return json(
            { error: { code: "internal_error", message: "数据库连接中断" } },
            500,
          )
        }
        return json({})
      }),
    )
    renderWithProviders(<BackupPanel />, { client })

    expect(await screen.findByText("无法读取备份策略")).toBeTruthy()
    expect(screen.getByText("数据库连接中断")).toBeTruthy()
  })

  it("一条策略都没有时是真正的空状态，而不是「0 个备份」", async () => {
    renderPanel([])
    expect(await screen.findByText("还没有备份策略")).toBeTruthy()
    expect(
      screen.getByText("没有策略就不会有备份。建一条策略，指定仓库与定时计划后才会开始产出快照。"),
    ).toBeTruthy()
    expect(screen.queryByText("0 个备份")).toBeNull()
  })

  it("未按计划运行的策略在行上标出来，而不是显示空 cron", async () => {
    renderPanel([POLICY, UNSCHEDULED])
    expect(within(policyRow("手动策略")).getByText("未按计划运行")).toBeTruthy()
    expect(within(policyRow("每日全量")).getByText("0 3 * * * · Asia/Shanghai")).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */

describe("备份 · 恢复包", () => {
  it("说明包内容与无法作废的后果，然后才轮到生成按钮", async () => {
    renderPanel()
    const section = screen.getByText("恢复包").closest("section") as HTMLElement

    // The consequences are present on first paint, with no click required.
    expect(
      within(section).getByText(/ZERO_NVR_SECRET_KEY、ZLM 与 TURN 共享密钥、含密码的数据库连接串/),
    ).toBeTruthy()
    expect(within(section).getByText(/生成之后没有任何办法让它失效/)).toBeTruthy()
    expect(within(section).getByText(/口令不会被保存，忘了口令就等于永久失去这个恢复包/)).toBeTruthy()
    expect(within(section).getByRole("button", { name: /生成并下载/ })).toBeTruthy()
  })

  it("口令不足 16 个字符时禁用生成，并说明按字节计", async () => {
    renderPanel()
    const button = screen.getByRole("button", { name: /生成并下载/ })
    expect((button as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(screen.getByLabelText("恢复包口令"), {
      target: { value: "short" },
    })
    expect(
      screen.getByText("口令至少 16 个字符（按 UTF-8 字节计）。"),
    ).toBeTruthy()
    expect((button as HTMLButtonElement).disabled).toBe(true)
    expect(callsTo("/backups/recovery-kit", "POST")).toHaveLength(0)

    fireEvent.change(screen.getByLabelText("恢复包口令"), {
      target: { value: "0123456789abcdef" },
    })
    expect((button as HTMLButtonElement).disabled).toBe(false)
  })

  it("生成时发送口令，响应字节交给 blob 下载", async () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("恢复包口令"), {
      target: { value: "0123456789abcdef" },
    })
    fireEvent.click(screen.getByRole("button", { name: /生成并下载/ }))

    await waitFor(() => {
      expect(callsTo("/backups/recovery-kit", "POST")).toHaveLength(1)
    })
    expect(callsTo("/backups/recovery-kit", "POST")[0].body).toEqual({
      policy_id: "p1",
      passphrase: "0123456789abcdef",
    })
    await waitFor(() => {
      expect(createObjectURL).toHaveBeenCalledTimes(1)
    })
    expect(createObjectURL.mock.calls[0][0]).toBeInstanceOf(Blob)
    // The synthetic anchor is removed and the object URL handed back.
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:recovery-kit")
    expect(document.querySelector("a[download]")).toBeNull()
  })

  it("生成成功时提示无法重新下载也无法作废", async () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("恢复包口令"), {
      target: { value: "0123456789abcdef" },
    })
    fireEvent.click(screen.getByRole("button", { name: /生成并下载/ }))

    await waitFor(() => {
      expect(screen.getByText("请立刻保存——它无法重新下载，也无法作废。")).toBeTruthy()
    })
  })
})
