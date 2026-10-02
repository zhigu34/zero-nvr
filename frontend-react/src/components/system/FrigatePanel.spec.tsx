import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { FrigatePanel } from "./FrigatePanel"
import { renderWithProviders } from "../../test-utils"
import { CAMS, FRIGATE } from "../../lib/queries"
import type { CameraSummary } from "../../api/cameras"
import type { FrigateProviderPut, FrigateProviderView } from "../../api/frigate"

/**
 * Three of the twelve-odd tests below are about one number: what a naive
 * editor would put in the request body.
 *
 * The Frigate PUT replaces the whole object (`api.py:429-443`), so a body built
 * from the fields that changed is not "minimal" — it is destructive. And the
 * five credential fields are write-only, so an editor that cannot express "do
 * not touch" would either clear them on every save or, worse, appear to work.
 * Every assertion below is about a **key set** rather than a value for exactly
 * that reason: a test that only checked "the body mentions the credentials"
 * passes on an implementation that wipes them.
 */

type Call = { method: string; url: string; body: unknown }

let calls: Call[] = []
/** The PUT body the fake server accepted, so a refetch can reflect it. */
let saved: FrigateProviderPut | null = null
let credentialsConfigured = false

/**
 * What the read endpoint does. `not_configured` is not a failure mode — it is
 * the first-run state, and it arrives as a 404 with a code, which is the whole
 * reason `isNotConfigured` exists.
 */
type ProviderState =
  | { kind: "not_configured" }
  | { kind: "view"; view: FrigateProviderView }
  | { kind: "error"; status: number; code: string; message: string }

function camera(id: string, name: string): CameraSummary {
  return {
    id,
    name,
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: null,
    storage_label: null,
    adapter_type: null,
    time_sync_mode: "monitor",
    ptz_capable: false,
    manufacturer: null,
    model: null,
    form_factor: "unknown",
    ip: null,
    port: null,
    rtsp_path: null,
    sub_rtsp_path: null,
    video_codec: null,
    width: null,
    height: null,
    fps: null,
    audio_codec: null,
    connectivity_status: "online",
    last_probe_at: null,
    last_online_at: null,
  }
}

const FRONT = camera("c1", "前门")
const BACK = camera("c2", "后院")
const CAMERAS = [FRONT, BACK]

/** A saved provider: enabled, MQTT off, one mapping, credentials stored. */
const CONFIGURED: FrigateProviderView = {
  // `configured` is never false in a response — the 404 happens first
  // (`schemas.py:51`). It is spelled true here to keep that visible.
  configured: true,
  enabled: true,
  mode: "external",
  instance_id: "9f1c2b7d4e5a6b7c8d9e0f1a2b3c4d5e",
  base_url: "http://frigate.internal:5000",
  camera_map: [{ frigate_camera: "front_door", camera_id: FRONT.id }],
  mqtt_enabled: false,
  mqtt_host: null,
  mqtt_port: 1883,
  mqtt_topic_prefix: "frigate",
  mqtt_tls: false,
  credentials_configured: true,
}

const WITH_MQTT: FrigateProviderView = {
  ...CONFIGURED,
  mqtt_enabled: true,
  mqtt_host: "mqtt.internal",
  mqtt_port: 8883,
  mqtt_topic_prefix: "frigate/events",
  mqtt_tls: true,
}

const DISABLED: FrigateProviderView = { ...CONFIGURED, enabled: false }

afterEach(() => {
  calls = []
  saved = null
  credentialsConfigured = false
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function notConfiguredResponse() {
  return json(
    { error: { code: "frigate_not_configured", message: "Frigate integration is not configured." } },
    404,
  )
}

/** What the server returns after a PUT: the row the 404 said was missing. */
function viewFromPut(body: FrigateProviderPut): FrigateProviderView {
  return {
    configured: true,
    enabled: body.enabled,
    mode: body.mode,
    instance_id: CONFIGURED.instance_id,
    base_url: body.base_url,
    camera_map: body.camera_map,
    mqtt_enabled: body.mqtt_enabled,
    mqtt_host: body.mqtt_host,
    mqtt_port: body.mqtt_port,
    mqtt_topic_prefix: body.mqtt_topic_prefix,
    mqtt_tls: body.mqtt_tls,
    credentials_configured: credentialsConfigured,
  }
}

function renderPanel(state: ProviderState = { kind: "not_configured" }) {
  credentialsConfigured =
    state.kind === "view" ? state.view.credentials_configured : false

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  if (state.kind === "view") client.setQueryData(FRIGATE.provider, state.view)
  client.setQueryData(CAMS.list(false), CAMERAS)

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })

      if (url.includes("/integrations/frigate/test")) {
        return json({ ok: true, version: "0.14.1" })
      }
      if (url.includes("/integrations/frigate/backfill")) {
        return json({ queued: true, lookback_seconds: body?.lookback_seconds })
      }
      if (url.includes("/integrations/frigate")) {
        if (method === "PUT") {
          saved = body as FrigateProviderPut
          if (saved.credentials_action === "replace") credentialsConfigured = true
          if (saved.credentials_action === "clear") credentialsConfigured = false
          return json(viewFromPut(saved))
        }
        if (saved) return json(viewFromPut(saved))
        if (state.kind === "view") return json(state.view)
        if (state.kind === "error") {
          return json(
            { error: { code: state.code, message: state.message } },
            state.status,
          )
        }
        return notConfiguredResponse()
      }
      if (url.includes("/cameras")) return json(CAMERAS)
      return json({})
    }),
  )

  return renderWithProviders(<FrigatePanel />, { client })
}

/* ------------------------------------------------------------- helpers */

function callsTo(fragment: string, method?: string) {
  return calls.filter(
    (c) => c.url.includes(fragment) && (!method || c.method === method),
  )
}

function savedBody() {
  return callsTo("/integrations/frigate", "PUT")[0].body as Record<string, unknown>
}

/** The whole credential control: state label, verb selector and the five fields. */
function credentialsGroup() {
  return screen.getByRole("group", { name: "Frigate 凭据" })
}

function chooseCredentialAction(label: "保持不变" | "替换" | "清空") {
  const verbs = screen.getByRole("group", { name: "Frigate 凭据操作" })
  fireEvent.click(within(verbs).getByRole("button", { name: label }))
}

/** A mapping row, named by position so a duplicate name cannot make it ambiguous. */
function mappingRow(index: number) {
  return screen.getByRole("group", { name: `映射行 ${index}` })
}

function addMapping(frigateName: string, cameraId: string) {
  // `queryAll` because the first-run form starts with no rows at all.
  const index = screen.queryAllByRole("group", { name: /映射行/ }).length + 1
  fireEvent.click(screen.getByRole("button", { name: /添加映射/ }))
  const row = mappingRow(index)
  fireEvent.change(within(row).getByLabelText("Frigate 侧机位名"), {
    target: { value: frigateName },
  })
  fireEvent.change(within(row).getByLabelText("本系统摄像机"), {
    target: { value: cameraId },
  })
  return row
}

function saveButton() {
  return screen.getByRole("button", { name: /保存配置/ }) as HTMLButtonElement
}

function fillBaseUrl(value: string) {
  fireEvent.change(screen.getByLabelText("Frigate 地址"), { target: { value } })
}

async function clickSave() {
  fireEvent.click(saveButton())
  await waitFor(() => {
    expect(callsTo("/integrations/frigate", "PUT")).toHaveLength(1)
  })
}

/* -------------------------------------------------------------------------- */

describe("Frigate 集成 · 404 是首次状态，不是读取失败", () => {
  it("frigate_not_configured 渲染首次配置表单，不出现错误横幅", async () => {
    renderPanel({ kind: "not_configured" })

    expect(await screen.findByText("尚未配置 Frigate")).toBeTruthy()
    expect(screen.queryByText("无法读取 Frigate 集成")).toBeNull()
    // A usable form, not a dead end: the address field is right there.
    expect(screen.getByLabelText("Frigate 地址")).toBeTruthy()
    expect(screen.getByRole("switch", { name: "启用 Frigate 集成" })).toBeTruthy()
    expect(callsTo("/integrations/frigate", "PUT")).toHaveLength(0)
  })

  it("首次状态填完地址即可保存，且带上整份表单", async () => {
    renderPanel({ kind: "not_configured" })
    await screen.findByText("尚未配置 Frigate")
    fillBaseUrl("http://frigate.internal:5000")
    addMapping("front_door", FRONT.id)
    await clickSave()

    expect(savedBody().base_url).toBe("http://frigate.internal:5000")
    expect(savedBody().camera_map).toEqual([
      { frigate_camera: "front_door", camera_id: FRONT.id },
    ])
  })

  it("真正的读取失败给出的是失败界面，不是同一块表单", async () => {
    renderPanel({
      kind: "error",
      status: 403,
      code: "forbidden",
      message: "缺少 integration.manage 权限",
    })

    expect(await screen.findByText("无法读取 Frigate 集成")).toBeTruthy()
    expect(screen.getByText("缺少 integration.manage 权限")).toBeTruthy()
    // The two states must not render the same screen.
    expect(screen.queryByText("尚未配置 Frigate")).toBeNull()
    expect(screen.queryByLabelText("Frigate 地址")).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("Frigate 集成 · PUT 是整对象替换", () => {
  it("只改一个字段，body 仍然带齐全部字段", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    // One field touched. Everything else must still be sent, or the replace
    // endpoint wipes it server-side.
    fillBaseUrl("http://frigate.internal:5001")
    await clickSave()

    expect(Object.keys(savedBody()).sort()).toEqual([
      "base_url",
      "camera_map",
      "credentials_action",
      "enabled",
      "mode",
      "mqtt_enabled",
      "mqtt_host",
      "mqtt_port",
      "mqtt_tls",
      "mqtt_topic_prefix",
    ])
    expect(savedBody().base_url).toBe("http://frigate.internal:5001")
    // Untouched, and still present.
    expect(savedBody().camera_map).toEqual([
      { frigate_camera: "front_door", camera_id: FRONT.id },
    ])
    expect(savedBody().mqtt_topic_prefix).toBe("frigate")
  })

  it("编辑普通字段不会惊动已存的凭据", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    fillBaseUrl("http://frigate.internal:5002")
    await clickSave()

    // `keep` is the verb that changes nothing. The frozen `buildFrigatePut`
    // always states it, so the guarantee that matters is the *value*: a body
    // carrying no `credentials` key cannot overwrite the stored secret, and a
    // body carrying `replace` or `clear` certainly can.
    expect(savedBody().credentials_action).toBe("keep")
    expect(savedBody()).not.toHaveProperty("credentials")
  })
})

/* -------------------------------------------------------------------------- */

describe("Frigate 集成 · 凭据三态", () => {
  it("默认停在「保持不变」，body 里没有凭据值", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")

    // The stored values are unreadable, so the only honest state is keep.
    expect(within(credentialsGroup()).getByText("已配置")).toBeTruthy()
    expect(within(credentialsGroup()).queryAllByRole("textbox")).toHaveLength(0)

    fillBaseUrl("http://frigate.internal:5003")
    await clickSave()

    expect(savedBody().credentials_action).toBe("keep")
    expect(savedBody()).not.toHaveProperty("credentials")
  })

  it("选「替换」只填一项，就只发这一项，不是五个空串", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    chooseCredentialAction("替换")

    // All five fields are shown together, because the replace is a whole-set
    // replace with no per-field verb.
    for (const label of [
      "HTTP Bearer Token",
      "HTTP 用户名",
      "HTTP 密码",
      "MQTT 用户名",
      "MQTT 密码",
    ]) {
      expect(within(credentialsGroup()).getByLabelText(label)).toBeTruthy()
    }
    fireEvent.change(within(credentialsGroup()).getByLabelText("HTTP 密码"), {
      target: { value: "s3cr3t" },
    })
    await clickSave()

    expect(savedBody().credentials_action).toBe("replace")
    // The server runs the object through `exclude_none=True` and rejects an
    // empty result (`api.py:387-399`); empty strings would also clear the four
    // fields the operator did not touch.
    expect(savedBody().credentials).toEqual({ http_password: "s3cr3t" })
  })

  it("选「清空」发的是 credentials: null", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    chooseCredentialAction("清空")
    await clickSave()

    expect(savedBody().credentials_action).toBe("clear")
    expect(savedBody().credentials).toBeNull()
  })

  it("选「替换」却什么都没填会被挡住", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    chooseCredentialAction("替换")
    fireEvent.click(saveButton())

    expect(
      screen.getByText("选择「替换」时至少要填一项凭据，否则服务端会拒绝"),
    ).toBeTruthy()
    expect(saveButton().disabled).toBe(true)
    expect(callsTo("/integrations/frigate", "PUT")).toHaveLength(0)
  })

  it("已保存的凭据不会出现在任何输入框里", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")

    // The read model only carries `credentials_configured`; even the five
    // inputs of a replace start empty rather than pre-filled.
    chooseCredentialAction("替换")
    for (const label of [
      "HTTP Bearer Token",
      "HTTP 用户名",
      "HTTP 密码",
      "MQTT 用户名",
      "MQTT 密码",
    ]) {
      const input = within(credentialsGroup()).getByLabelText(label) as HTMLInputElement
      expect(input.value).toBe("")
    }
  })
})

/* -------------------------------------------------------------------------- */

describe("Frigate 集成 · 摄像机映射", () => {
  it("重复的 Frigate 侧机位名被本地挡住，并指出是哪一个", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    addMapping("front_door", BACK.id)

    // The backend's 400 does not name the key (`api.py:345-354`); the client
    // does, which is the only place the operator learns which row to fix.
    expect(screen.getByText("Frigate 侧机位名重复：front_door")).toBeTruthy()
    fireEvent.click(saveButton())
    expect(callsTo("/integrations/frigate", "PUT")).toHaveLength(0)
  })

  it("只填了名字没选摄像机时也会被挡住", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    const index = screen.getAllByRole("group", { name: /映射行/ }).length + 1
    fireEvent.click(screen.getByRole("button", { name: /添加映射/ }))
    fireEvent.change(within(mappingRow(index)).getByLabelText("Frigate 侧机位名"), {
      target: { value: "side_gate" },
    })

    expect(screen.getByText(/还有 1 条映射没有选择本系统摄像机/)).toBeTruthy()
    fireEvent.click(saveButton())
    expect(callsTo("/integrations/frigate", "PUT")).toHaveLength(0)
  })

  it("删除一行会把它从整对象替换里去掉", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    addMapping("back_yard", BACK.id)
    fireEvent.click(within(mappingRow(2)).getByRole("button", { name: "删除映射 2" }))
    await clickSave()

    expect(savedBody().camera_map).toEqual([
      { frigate_camera: "front_door", camera_id: FRONT.id },
    ])
  })
})

/* -------------------------------------------------------------------------- */

describe("Frigate 集成 · MQTT 只在启用时生效", () => {
  it("启用 MQTT 却没填主机时保存被挡住", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    fillBaseUrl("http://frigate.internal:5000")
    fireEvent.click(screen.getByRole("switch", { name: "启用 MQTT" }))
    fireEvent.click(saveButton())

    expect(screen.getByText("启用 MQTT 时必须填写主机")).toBeTruthy()
    expect(callsTo("/integrations/frigate", "PUT")).toHaveLength(0)
  })

  it("关掉 MQTT 后不会把残留的主机发出去", async () => {
    renderPanel({ kind: "view", view: WITH_MQTT })
    await screen.findByText("已启用")
    expect(screen.getByLabelText("MQTT 主机")).toBeTruthy()

    fireEvent.click(screen.getByRole("switch", { name: "启用 MQTT" }))
    // The fields are gone with the feature, and the panel says what the PUT
    // will do about the host it no longer shows.
    expect(screen.queryByLabelText("MQTT 主机")).toBeNull()
    expect(screen.getByText(/保存会把 mqtt_host 写成 null/)).toBeTruthy()
    await clickSave()

    expect(savedBody().mqtt_enabled).toBe(false)
    expect(savedBody().mqtt_host).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("Frigate 集成 · 有外部副作用的两个动作", () => {
  it("挂载时不发任何测试请求", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    // `/test` makes a real outbound HTTP call to Frigate (10s timeout,
    // `api.py:556-561`). A mount-time probe would be a side effect nobody
    // asked for.
    expect(callsTo("/integrations/frigate/test")).toHaveLength(0)
  })

  it("点一次才发一次 POST", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    fireEvent.click(screen.getByRole("button", { name: /测试连接/ }))

    await waitFor(() => {
      expect(callsTo("/integrations/frigate/test", "POST")).toHaveLength(1)
    })
  })

  it("还没保存配置时不能测试，并说明原因", async () => {
    renderPanel({ kind: "not_configured" })
    await screen.findByText("尚未配置 Frigate")
    const test = screen.getByRole("button", { name: /测试连接/ }) as HTMLButtonElement
    expect(test.disabled).toBe(true)
    expect(screen.getByText("尚未保存配置，无法测试。")).toBeTruthy()
  })

  it("集成停用时回填被禁用，理由写明是未启用", async () => {
    renderPanel({ kind: "view", view: DISABLED })
    await screen.findByText("已停用")
    const backfill = screen.getByRole("button", {
      name: /回填事件/,
    }) as HTMLButtonElement
    expect(backfill.disabled).toBe(true)
    expect(screen.getByText(/集成当前未启用，保存并启用后才能回填/)).toBeTruthy()
    fireEvent.click(backfill)
    expect(callsTo("/integrations/frigate/backfill")).toHaveLength(0)
  })

  it("确认后按夹紧后的回看窗口入队", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    // Beyond the 86400 ceiling (`schemas.py:71-76`): the operator is told the
    // real number before agreeing, and the request carries the same number.
    fireEvent.change(screen.getByLabelText("回看窗口（秒）"), {
      target: { value: 999999 },
    })
    expect(screen.getByText("实际入队 24 小时")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: /回填事件/ }))

    const dialog = await screen.findByRole("alertdialog")
    expect(within(dialog).getByText(/将回看 24 小时（86400 秒）/)).toBeTruthy()
    fireEvent.click(within(dialog).getByRole("button", { name: "入队" }))

    await waitFor(() => {
      expect(callsTo("/integrations/frigate/backfill", "POST")).toHaveLength(1)
    })
    expect(callsTo("/integrations/frigate/backfill", "POST")[0].body).toEqual({
      lookback_seconds: 86400,
    })
  })

  it("取消确认就不入队", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    fireEvent.click(screen.getByRole("button", { name: /回填事件/ }))

    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull()
    })
    expect(callsTo("/integrations/frigate/backfill")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */

describe("Frigate 集成 · 已保存的配置", () => {
  it("表单被服务端已有的值填好，instance_id 只读展示", async () => {
    renderPanel({ kind: "view", view: WITH_MQTT })
    await screen.findByText("已启用")

    expect(
      (screen.getByLabelText("Frigate 地址") as HTMLInputElement).value,
    ).toBe("http://frigate.internal:5000")
    expect(
      (within(mappingRow(1)).getByLabelText("Frigate 侧机位名") as HTMLInputElement)
        .value,
    ).toBe("front_door")
    expect((screen.getByLabelText("MQTT 主机") as HTMLInputElement).value).toBe(
      "mqtt.internal",
    )
    // Server-owned, shown but never written by the form.
    expect(screen.getByText(CONFIGURED.instance_id)).toBeTruthy()
  })

  it("两种模式各自说明自己的后果", async () => {
    renderPanel({ kind: "view", view: CONFIGURED })
    await screen.findByText("已启用")
    expect(screen.getByText(/外部：Frigate 由你自己运行/)).toBeTruthy()

    fireEvent.change(screen.getByLabelText("Frigate 模式"), { target: { value: "managed" } })
    expect(screen.getByText(/托管：保存并启用后由服务端生成 Frigate 配置方案/)).toBeTruthy()
    await clickSave()
    expect(savedBody().mode).toBe("managed")
  })
})
