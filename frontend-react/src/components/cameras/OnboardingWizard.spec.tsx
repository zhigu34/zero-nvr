import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { OnboardingWizard } from "./OnboardingWizard"
import { renderWithProviders } from "../../test-utils"
import {
  buildManualCameraInput,
  emptyManualCameraForm,
  type DiscoveryCandidateView,
  type DiscoverySessionView,
  type ManualCameraForm,
  type OnvifIdentityView,
  type OnvifInspectionView,
  type OnvifProfileView,
} from "../../api/onboarding"

/**
 * The wizard is a request-shape test with a screen attached.
 *
 * Almost every assertion below is about the **body that leaves the browser**,
 * because the four traps in this contract are all invisible on screen: an
 * untouched profile selection looks identical either way until you read the
 * JSON, a wrong `confirm_existing_device_id` is a *second* 409 for one mistake,
 * `POST /cameras` succeeding means nothing about the stream playing, and a 503
 * that already persisted looks exactly like a failure.
 *
 * So: record every fetch, scope every query to a named region, and never index
 * a list positionally. A positional `getAllByRole("button")[2]` would keep
 * passing after a step is inserted, which is precisely the change these tests
 * exist to catch.
 */

/* -------------------------------------------------------------------------- */
/* Fixtures                                                                   */
/* -------------------------------------------------------------------------- */

function profile(overrides: Partial<OnvifProfileView> = {}): OnvifProfileView {
  return {
    token: "p1",
    name: "主码流",
    video_source_token: "vs1",
    codec: "H264",
    width: 1920,
    height: 1080,
    fps: 25,
    bitrate_kbps: 4096,
    gop_seconds: 2,
    audio_codec: "aac",
    has_audio: true,
    stream_uri_available: true,
    ...overrides,
  }
}

function identity(overrides: Partial<OnvifIdentityView> = {}): OnvifIdentityView {
  return {
    state: "new_device",
    matched_device_id: null,
    matched_device_name: null,
    conflicting_device_ids: [],
    reason: null,
    ...overrides,
  }
}

function inspection(overrides: Partial<OnvifInspectionView> = {}): OnvifInspectionView {
  return {
    device: {
      manufacturer: "Vendor",
      model: "Cam-1",
      firmware_version: "1.0.4",
      serial_number: "SN-1",
      hardware_id: null,
    },
    capabilities: ["events", "ptz"],
    profiles: [profile(), profile({ token: "p2", name: "子码流", width: 640, height: 360 })],
    identity: identity(),
    ...overrides,
  }
}

function candidate(
  overrides: Partial<DiscoveryCandidateView> = {},
): DiscoveryCandidateView {
  return {
    id: "cand-1",
    candidate_key: "192.168.1.77:2020",
    host: "192.168.1.77",
    port: 2020,
    device_service_url: "http://192.168.1.77:2020/onvif/device_service",
    display_info: { name: "门卫" },
    state: "reachable",
    ...overrides,
  }
}

function session(candidates: DiscoveryCandidateView[] = []): DiscoverySessionView {
  return {
    id: "disc-1",
    method: "onvif_ws_discovery",
    status: "completed",
    started_at: "2026-10-02T00:00:00Z",
    completed_at: "2026-10-02T00:00:03Z",
    candidates,
  }
}

function probeOk() {
  return {
    ok: true as const,
    streams: [
      {
        role: "primary" as const,
        name: "主码流",
        video: {
          kind: "video",
          codec: "H264",
          ready: true,
          width: 1920,
          height: 1080,
          fps: 25,
          gop_seconds: 2,
          sample_rate: null,
          channels: null,
        },
        audio: null,
      },
    ],
  }
}

const MANUAL_FORM: ManualCameraForm = {
  ...emptyManualCameraForm(),
  name: "前门",
  primaryUrl: "rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101",
}

/* -------------------------------------------------------------------------- */
/* Fetch double                                                               */
/* -------------------------------------------------------------------------- */

type Call = { method: string; url: string; body: unknown }
type Route = {
  when: (call: Call) => boolean
  handle: (call: Call) => Response | Promise<Response>
}

let calls: Call[] = []
let routes: Route[] = []

afterEach(() => {
  calls = []
  routes = []
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function reply(body: unknown) {
  return () => json(body)
}

function refuse(
  status: number,
  code: string,
  message: string,
  details: Record<string, unknown> | null = null,
) {
  return () => json({ error: { code, message, details } }, status)
}

/** Never settles: the only honest way to hold a button in its pending state. */
function stall() {
  return () => new Promise<Response>(() => {})
}

const postTo = (path: string) => (c: Call) => c.method === "POST" && c.url.endsWith(path)

function on(when: (c: Call) => boolean, handle: Route["handle"]) {
  routes.push({ when, handle })
}

/** Records every request; only GETs are answered blindly (query invalidation). */
function renderWizard() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call: Call = {
        method: init?.method ?? "GET",
        url: String(input),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      }
      calls.push(call)
      if (call.method === "GET") return json([])
      const route = routes.find((r) => r.when(call))
      if (!route) throw new Error(`unexpected request: ${call.method} ${call.url}`)
      return route.handle(call)
    }),
  )
  return renderWithProviders(<OnboardingWizard />)
}

const posts = () => calls.filter((c) => c.method === "POST")
const postsTo = (path: string) => calls.filter((c) => c.method === "POST" && c.url.endsWith(path))

function bodyOf(path: string): Record<string, unknown> {
  const sent = postsTo(path)
  if (sent.length === 0) throw new Error(`no POST to ${path}`)
  return sent[sent.length - 1].body as Record<string, unknown>
}

/* -------------------------------------------------------------------------- */
/* Drivers                                                                    */
/* -------------------------------------------------------------------------- */

function valueOf(label: string): string {
  return (screen.getByLabelText(label) as HTMLInputElement).value
}

function typeInto(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

function openManualTab() {
  fireEvent.click(screen.getByRole("tab", { name: "手动 RTSP" }))
}

/** Fills a usable ONVIF connection, then reads the device's profile list. */
async function inspectDevice() {
  if (valueOf("设备密码") === "") typeInto("设备密码", "secret")
  fireEvent.click(screen.getByRole("button", { name: "检查设备" }))
  await screen.findByText("可导入的码流")
}

function importableGroup() {
  return screen.getByRole("group", { name: "可导入的码流" })
}

function profileCheckbox(name: RegExp) {
  return within(importableGroup()).getByRole("checkbox", { name })
}

async function importDevice(overrides: Partial<OnvifInspectionView> = {}) {
  on(postTo("/cameras/onvif/test"), reply(inspection(overrides)))
  on(postTo("/cameras/onvif/import"), reply({ device_id: "dev-9", reconfigured: false, cameras: [] }))
  if (valueOf("设备地址") === "") typeInto("设备地址", "192.168.1.64")
  await inspectDevice()
}

async function testedManualCamera() {
  on(postTo("/cameras/test"), reply(probeOk()))
  on(postTo("/cameras"), reply({ id: "cam-7", name: MANUAL_FORM.name }))
  openManualTab()
  typeInto("机位名称", MANUAL_FORM.name)
  typeInto("主码流地址", MANUAL_FORM.primaryUrl)
  fireEvent.click(screen.getByRole("button", { name: "测试连通性" }))
  await screen.findByRole("list", { name: "连通性测试结果" })
}

/**
 * The one assertion every network step shares: a pending label, a disabled
 * button, and — because jsdom happily dispatches clicks at a disabled button —
 * a request count that stays put.
 */
async function expectSinglePendingSubmit(pendingLabel: string, expectedPosts: number) {
  const button = await screen.findByRole("button", { name: pendingLabel })
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true))
  fireEvent.click(button)
  fireEvent.click(button)
  expect(posts()).toHaveLength(expectedPosts)
}

/* -------------------------------------------------------------------------- */

describe("接入向导 · 开始之前", () => {
  it("挂载不发任何请求，步骤指示停在第 1 步", () => {
    renderWizard()

    const steps = within(screen.getByRole("list", { name: "ONVIF 接入步骤" }))
    expect(steps.getAllByRole("listitem")).toHaveLength(3)
    expect(
      steps.getAllByRole("listitem")[0].getAttribute("aria-current"),
    ).toBe("step")
    expect(calls).toHaveLength(0)
  })
})

describe("接入向导 · ONVIF 发现", () => {
  it("零结果时说明这是组播广播，不是扫网段", async () => {
    renderWizard()
    on(postTo("/cameras/discovery"), reply(session([])))

    fireEvent.click(screen.getByRole("button", { name: "开始发现" }))

    const empty = (await screen.findByText("没有发现到任何设备")).closest(
      "div",
    ) as HTMLElement
    expect(within(empty).getByText(/同一广播域/)).toBeTruthy()
    expect(within(empty).getByText(/组播/)).toBeTruthy()
    expect(screen.queryByRole("list", { name: "发现候选列表" })).toBeNull()
    expect(postsTo("/cameras/discovery")).toHaveLength(1)
  })

  it("选用候选会填好地址与端口，导入时带上候选 id", async () => {
    renderWizard()
    on(postTo("/cameras/discovery"), reply(session([candidate()])))
    await importDevice()

    fireEvent.click(screen.getByRole("button", { name: "开始发现" }))
    fireEvent.click(
      await screen.findByRole("button", { name: /选择设备 门卫/ }),
    )
    expect(valueOf("设备地址")).toBe("192.168.1.77")
    expect(valueOf("ONVIF 端口")).toBe("2020")

    // Picking a device invalidates the inspection of the previous one, so the
    // check has to run again before anything may be written.
    expect(screen.queryByText("可导入的码流")).toBeNull()
    await inspectDevice()

    fireEvent.click(screen.getByRole("button", { name: "导入设备并创建机位" }))
    await waitFor(() => expect(postsTo("/cameras/onvif/import")).toHaveLength(1))

    const sent = bodyOf("/cameras/onvif/import")
    expect(sent.discovery_candidate_id).toBe("cand-1")
    expect(sent.host).toBe("192.168.1.77")
    expect(sent.port).toBe(2020)
  })

  it("源地址超过上限时在本地被挡住，不发请求", () => {
    renderWizard()
    typeInto(
      "本机源地址（可选）",
      Array.from({ length: 17 }, (_, i) => `192.168.1.${i + 1}`).join(", "),
    )

    fireEvent.click(screen.getByRole("button", { name: "开始发现" }))

    expect(screen.getByText(/最多 16 个源地址/)).toBeTruthy()
    expect(posts()).toHaveLength(0)
  })

  it("发现失败时给出原因与下一步，而不是一个停住的转圈", async () => {
    renderWizard()
    on(postTo("/cameras/discovery"), refuse(502, "onvif_discovery_failed", "probe failed"))

    fireEvent.click(screen.getByRole("button", { name: "开始发现" }))

    await screen.findByText("设备发现失败（onvif_discovery_failed）")
    // Distinct from the mutation's toast wording, which is not this advice.
    expect(screen.getByText(/且组播没有被交换机或防火墙拦截/)).toBeTruthy()
  })
})

describe("接入向导 · ONVIF 检查", () => {
  it("只列可导入的码流，取不到流地址的码流被标为不会被导入", async () => {
    renderWizard()
    await importDevice({
      profiles: [
        profile(),
        profile({ token: "p2", name: "快照码流", stream_uri_available: false }),
      ],
    })

    expect(within(importableGroup()).getByText(/主码流/)).toBeTruthy()
    expect(within(importableGroup()).queryByText(/快照码流/)).toBeNull()

    const excluded = screen.getByRole("group", { name: "无法导入的码流" })
    expect(within(excluded).getByText(/快照码流/)).toBeTruthy()
    expect(within(excluded).getByText(/有 1 个码流取不到可用的流地址/)).toBeTruthy()
  })

  it("地址栏里填了 URL 会在本地被挡住，不必等服务端 422", async () => {
    renderWizard()
    typeInto("设备地址", "rtsp://192.168.1.64")
    typeInto("设备密码", "secret")

    fireEvent.click(screen.getByRole("button", { name: "检查设备" }))

    expect(screen.getByText(/不要带 rtsp:\/\/ 前缀/)).toBeTruthy()
    expect(postsTo("/cameras/onvif/test")).toHaveLength(0)
  })

  it("422 连接失败不会替服务端猜是哪一项错了", async () => {
    renderWizard()
    on(
      postTo("/cameras/onvif/test"),
      refuse(422, "onvif_connection_failed", "onvif connect failed"),
    )
    typeInto("设备地址", "192.168.1.64")
    typeInto("设备密码", "secret")

    fireEvent.click(screen.getByRole("button", { name: "检查设备" }))

    await screen.findByText("设备检查失败（onvif_connection_failed）")
    // The mutation's own wording, which refuses to name a cause.
    expect(
      screen.getByText(
        "无法连接该设备。地址、端口、凭据或网络策略任一不对，结果都一样，请逐项排查。",
      ),
    ).toBeTruthy()
    expect(screen.getByText(/服务端不会告诉你是哪一项/)).toBeTruthy()
    // Nothing anywhere may say "wrong password": a 422 covers all three causes.
    expect(document.body.textContent).not.toMatch(/密码错误|密码不正确|密码已失效/)
  })
})

describe("接入向导 · profile_tokens 的 null 与 []", () => {
  it("没动过勾选时发的是 null，意思是导入全部码流", async () => {
    renderWizard()
    await importDevice()

    expect(screen.getByText("未改动选择：将导入全部 2 个")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "导入设备并创建机位" }))

    await waitFor(() => expect(postsTo("/cameras/onvif/import")).toHaveLength(1))
    const sent = bodyOf("/cameras/onvif/import")
    // Not `[]`: an empty array is a different, usually failing, request.
    expect(sent.profile_tokens).toBeNull()
  })

  it("勾选之后发的是勾选列表", async () => {
    renderWizard()
    await importDevice()

    fireEvent.click(profileCheckbox(/子码流/))
    expect(screen.getByText("已选 1 / 2 个")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "导入设备并创建机位" }))

    await waitFor(() => expect(postsTo("/cameras/onvif/import")).toHaveLength(1))
    expect(bodyOf("/cameras/onvif/import").profile_tokens).toEqual(["p1"])
  })

  it("把勾选清空会在本地被挡住，不会发出一个 0 码流的导入", async () => {
    renderWizard()
    await importDevice()

    fireEvent.click(profileCheckbox(/主码流/))
    fireEvent.click(profileCheckbox(/子码流/))
    fireEvent.click(screen.getByRole("button", { name: "导入设备并创建机位" }))

    expect(
      screen.getByText("已取消全部勾选将导入 0 个码流。请至少选一个，或恢复默认的「全部」。"),
    ).toBeTruthy()
    expect(postsTo("/cameras/onvif/import")).toHaveLength(0)
  })

  it("恢复默认后重新发 null", async () => {
    renderWizard()
    await importDevice()

    fireEvent.click(profileCheckbox(/主码流/))
    fireEvent.click(screen.getByRole("button", { name: "恢复默认：导入全部" }))
    expect(screen.getByText("未改动选择：将导入全部 2 个")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "导入设备并创建机位" }))
    await waitFor(() => expect(postsTo("/cameras/onvif/import")).toHaveLength(1))
    expect(bodyOf("/cameras/onvif/import").profile_tokens).toBeNull()
  })
})

describe("接入向导 · 身份四态", () => {
  it("新设备直接导入，且不带 confirm_existing_device_id", async () => {
    renderWizard()
    await importDevice({ identity: identity({ state: "new_device" }) })

    // The verdict is shown twice on purpose: with the device facts above, and
    // as a badge on the write that is about to be offered.
    const verdict = screen.getByText("身份判定").parentElement as HTMLElement
    expect(within(verdict).getByText("新设备")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "导入设备并创建机位" }))

    await waitFor(() => expect(postsTo("/cameras/onvif/import")).toHaveLength(1))
    const sent = bodyOf("/cameras/onvif/import")
    expect(Object.hasOwn(sent, "confirm_existing_device_id")).toBe(false)
  })

  it("已在本系统里就只提供重新读取，不再提供导入", async () => {
    renderWizard()
    on(
      postTo("/cameras/dev-7/onvif/refresh"),
      reply({ device_id: "dev-7", diff: {}, cameras: [] }),
    )
    await importDevice({
      identity: identity({ state: "same_device", matched_device_id: "dev-7" }),
    })

    expect(screen.getByRole("button", { name: "重新读取设备能力" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "导入设备并创建机位" })).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "重新读取设备能力" }))
    await waitFor(() => expect(postsTo("/cameras/dev-7/onvif/refresh")).toHaveLength(1))
    expect(postsTo("/cameras/onvif/import")).toHaveLength(0)
  })

  it("疑似同一台要先显式确认，再原样回传服务端的 matched_device_id", async () => {
    renderWizard()
    await importDevice({
      identity: identity({
        state: "probable_match_requires_confirmation",
        matched_device_id: "dev-7",
        matched_device_name: "后院",
      }),
    })

    const confirm = screen.getByRole("button", { name: "确认是同一台并导入" })
    expect((confirm as HTMLButtonElement).disabled).toBe(true)

    // Clicking it without the explicit confirmation must not write anything.
    fireEvent.click(confirm)
    expect(postsTo("/cameras/onvif/import")).toHaveLength(0)

    const gate = within(screen.getByRole("group", { name: "身份确认" }))
    fireEvent.click(gate.getByRole("checkbox"))
    expect(
      (screen.getByRole("button", { name: "确认是同一台并导入" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false)

    fireEvent.click(screen.getByRole("button", { name: "确认是同一台并导入" }))
    await waitFor(() => expect(postsTo("/cameras/onvif/import")).toHaveLength(1))
    // Exactly the id the server handed out — a locally derived one returns a
    // different 409 for the same mistake.
    expect(bodyOf("/cameras/onvif/import").confirm_existing_device_id).toBe("dev-7")
  })

  it("身份冲突既没有导入按钮，也说明了原因", async () => {
    renderWizard()
    await importDevice({
      identity: identity({
        state: "identity_conflict",
        matched_device_id: "dev-3",
        matched_device_name: "后院",
        conflicting_device_ids: ["dev-3", "dev-4"],
      }),
    })

    expect(screen.getByText("无法通过导入新增这台设备")).toBeTruthy()
    expect(screen.getByText(/该设备与本系统中已有的设备身份冲突（后院）/)).toBeTruthy()
    expect(screen.queryByRole("button", { name: "导入设备并创建机位" })).toBeNull()
    expect(screen.queryByRole("button", { name: "确认是同一台并导入" })).toBeNull()
    expect(postsTo("/cameras/onvif/import")).toHaveLength(0)
  })
})

describe("接入向导 · 导入的失败与结果", () => {
  it("全部码流都取不到流地址时，不提供只能失败的导入按钮", async () => {
    renderWizard()
    await importDevice({
      profiles: [profile({ stream_uri_available: false })],
    })

    expect(screen.getByText("没有可导入的码流")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "导入设备并创建机位" })).toBeNull()
    expect(postsTo("/cameras/onvif/import")).toHaveLength(0)
  })

  it("503 且已落库时给出「不要重复导入」，并且不再提供导入按钮", async () => {
    renderWizard()
    on(postTo("/cameras/onvif/test"), reply(inspection()))
    on(
      postTo("/cameras/onvif/import"),
      refuse(503, "camera_runtime_queue_unavailable", "queue down", {
        configuration_persisted: true,
        device_id: "dev-9",
      }),
    )
    typeInto("设备地址", "192.168.1.64")
    await inspectDevice()

    fireEvent.click(screen.getByRole("button", { name: "导入设备并创建机位" }))

    await screen.findByText("设备与机位已经落库，请勿重复导入")
    expect(
      screen.getByText(/再次导入同一份表单会造出第二台同名设备/),
    ).toBeTruthy()
    expect(
      screen.getByText(
        /请不要重复导入——重复导入会造出第二台同名设备/,
      ),
    ).toBeTruthy()
    // The re-import is withdrawn, not merely discouraged: no automatic retry,
    // and no way to press the same form into a second device.
    expect(screen.queryByRole("button", { name: "导入设备并创建机位" })).toBeNull()
    expect(postsTo("/cameras/onvif/import")).toHaveLength(1)
  })

  it("导入成功后机位来自响应，并说明数量不等于码流数", async () => {
    renderWizard()
    on(postTo("/cameras/onvif/test"), reply(inspection()))
    on(
      postTo("/cameras/onvif/import"),
      reply({
        device_id: "dev-9",
        reconfigured: false,
        // Cameras are grouped by video_source_token, so two selected profiles
        // can well come back as three cameras.
        cameras: [
          { id: "cam-1", name: "前门 1" },
          { id: "cam-2", name: "前门 2" },
          { id: "cam-3", name: "后门 1" },
        ],
      }),
    )
    typeInto("设备地址", "192.168.1.64")
    await inspectDevice()

    fireEvent.click(screen.getByRole("button", { name: "导入设备并创建机位" }))

    await screen.findByText("导入完成：实际创建 3 个机位。")
    const created = within(
      screen.getByRole("group", { name: "本次导入创建的机位" }),
    )
    expect(created.getByText("· 前门 1")).toBeTruthy()
    expect(created.getByText("· 前门 2")).toBeTruthy()
    expect(created.getByText("· 后门 1")).toBeTruthy()
    expect(
      screen.getByText(/机位按 video_source_token 分组，数量由设备决定，与所选码流数不一定相同。/),
    ).toBeTruthy()
    // The claim this must never make.
    expect(document.body.textContent).not.toMatch(/每个码流\s*1\s*个机位|一码流一机位/)
  })
})

describe("接入向导 · 手动 RTSP", () => {
  it("没有成功的连通性测试就不提供创建", async () => {
    renderWizard()
    openManualTab()
    typeInto("机位名称", MANUAL_FORM.name)
    typeInto("主码流地址", MANUAL_FORM.primaryUrl)

    expect(screen.queryByRole("button", { name: "创建机位" })).toBeNull()
    expect(screen.getByText(/还没有一次成功的连通性测试/)).toBeTruthy()
  })

  it("先测试再创建，创建请求体就是 buildManualCameraInput 的输出", async () => {
    renderWizard()
    await testedManualCamera()

    fireEvent.click(screen.getByRole("button", { name: "创建机位" }))
    await waitFor(() => expect(postsTo("/cameras")).toHaveLength(1))
    expect(bodyOf("/cameras")).toEqual(buildManualCameraInput(MANUAL_FORM))
  })

  it("空的或非 rtsp:// 的主码流地址会在本地被挡住", async () => {
    renderWizard()
    on(postTo("/cameras/test"), reply(probeOk()))
    openManualTab()
    typeInto("机位名称", MANUAL_FORM.name)

    // Empty: the probe is never sent, so the operator never waits 12 s to be
    // told the field is blank.
    fireEvent.click(screen.getByRole("button", { name: "测试连通性" }))
    expect(
      screen.getByText("主码流地址必须是 rtsp:// 开头且带主机名的完整 URL"),
    ).toBeTruthy()
    expect(postsTo("/cameras/test")).toHaveLength(0)

    typeInto("主码流地址", "http://192.168.1.64/stream")
    fireEvent.click(screen.getByRole("button", { name: "测试连通性" }))
    expect(postsTo("/cameras/test")).toHaveLength(0)

    typeInto("主码流地址", MANUAL_FORM.primaryUrl)
    fireEvent.click(screen.getByRole("button", { name: "测试连通性" }))
    await screen.findByRole("list", { name: "连通性测试结果" })
    expect(postsTo("/cameras/test")).toHaveLength(1)
  })

  it("「密码之后改不了」在创建之前就写在面板上，不只出现在成功提示里", async () => {
    renderWizard()
    openManualTab()

    const warning = /RTSP 地址与密码之后无法在此修改/
    expect(screen.getByText(warning)).toBeTruthy()
    expect(screen.queryByRole("button", { name: "创建机位" })).toBeNull()
    // The toast layer must not be where this lives.
    expect(
      within(screen.getByRole("region", { name: "通知" })).queryByText(warning),
    ).toBeNull()

    await testedManualCamera()
    expect(screen.getByText(warning)).toBeTruthy()
    expect(screen.getByRole("button", { name: "创建机位" })).toBeTruthy()
  })

  it("测试通过后又改了地址，创建按钮会收回去", async () => {
    renderWizard()
    await testedManualCamera()

    typeInto("主码流地址", "rtsp://user:pass@192.168.1.64:554/Streaming/Channels/201")

    expect(screen.queryByRole("button", { name: "创建机位" })).toBeNull()
    expect(screen.getByText(/表单在测试之后被改过/)).toBeTruthy()
  })

  it("连通性测试失败时说明原因与下一步", async () => {
    renderWizard()
    on(postTo("/cameras/test"), refuse(422, "invalid_rtsp_url", "bad url"))
    openManualTab()
    typeInto("机位名称", MANUAL_FORM.name)
    typeInto("主码流地址", MANUAL_FORM.primaryUrl)

    fireEvent.click(screen.getByRole("button", { name: "测试连通性" }))

    await screen.findByText("连通性测试失败（invalid_rtsp_url）")
    expect(screen.getByText(/能不能播由连通性测试决定/)).toBeTruthy()
  })
})

describe("接入向导 · 每一步都有进行中状态", () => {
  it("发现", async () => {
    renderWizard()
    on(postTo("/cameras/discovery"), stall())
    fireEvent.click(screen.getByRole("button", { name: "开始发现" }))
    await expectSinglePendingSubmit("发现中…", 1)
  })

  it("检查", async () => {
    renderWizard()
    on(postTo("/cameras/onvif/test"), stall())
    typeInto("设备地址", "192.168.1.64")
    typeInto("设备密码", "secret")
    fireEvent.click(screen.getByRole("button", { name: "检查设备" }))
    await expectSinglePendingSubmit("检查中…", 1)
  })

  it("导入", async () => {
    renderWizard()
    on(postTo("/cameras/onvif/test"), reply(inspection()))
    on(postTo("/cameras/onvif/import"), stall())
    typeInto("设备地址", "192.168.1.64")
    await inspectDevice()
    fireEvent.click(screen.getByRole("button", { name: "导入设备并创建机位" }))
    // One inspection plus one import: the import must not fire twice.
    await expectSinglePendingSubmit("导入中…", 2)
  })

  it("重新读取能力", async () => {
    renderWizard()
    on(
      postTo("/cameras/dev-7/onvif/refresh"),
      stall(),
    )
    await importDevice({
      identity: identity({ state: "same_device", matched_device_id: "dev-7" }),
    })
    fireEvent.click(screen.getByRole("button", { name: "重新读取设备能力" }))
    await expectSinglePendingSubmit("重新读取中…", 2)
  })

  it("连通性测试", async () => {
    renderWizard()
    on(postTo("/cameras/test"), stall())
    openManualTab()
    typeInto("机位名称", MANUAL_FORM.name)
    typeInto("主码流地址", MANUAL_FORM.primaryUrl)
    fireEvent.click(screen.getByRole("button", { name: "测试连通性" }))
    await expectSinglePendingSubmit("测试中…", 1)
  })

  it("创建机位", async () => {
    renderWizard()
    on(postTo("/cameras/test"), reply(probeOk()))
    on(postTo("/cameras"), stall())
    openManualTab()
    typeInto("机位名称", MANUAL_FORM.name)
    typeInto("主码流地址", MANUAL_FORM.primaryUrl)
    fireEvent.click(screen.getByRole("button", { name: "测试连通性" }))
    await screen.findByRole("list", { name: "连通性测试结果" })

    fireEvent.click(screen.getByRole("button", { name: "创建机位" }))
    await expectSinglePendingSubmit("创建中…", 2)
  })
})
