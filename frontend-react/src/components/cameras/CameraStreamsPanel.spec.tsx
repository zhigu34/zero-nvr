import { useState } from "react"
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { CameraStreamsPanel } from "./CameraStreamsPanel"
import { renderWithProviders } from "../../test-utils"
import { formatClock } from "../../lib/format"
import type {
  CameraDetail,
  CameraStreamBinding,
  CameraStreamDiagnostic,
  CameraStreamProfile,
} from "../../api/cameras"

/**
 * 这组用例盯的是三件**说谎就会出事**的事：
 *
 * 1. 状态与描述串读错字段。profile 上的编码字段叫 `codec`，而 `video_codec` 只
 *    存在于 `CameraSummary`；读错名字不报错，只会永远拿到 `undefined`——所以下面
 *    的 `BASE.video_codec` 故意放了一个诱饵值，描述串里出现它就说明读错了对象。
 * 2. 绑定保存是整体替换，而 `selection_mode` 必须原样回传。少了任何一条，保存后
 *    服务端的绑定集就和操作员以为的不一样。
 * 3. 检测结果里 `ready: false` 不是成功。把「读不到数据」显示成「检测完成」是这类
 *    面板最典型的谎报。
 */

function profile(over: Partial<CameraStreamProfile>): CameraStreamProfile {
  return {
    id: "p1",
    name: "主码流",
    adapter_profile_key: "main",
    codec: "H264",
    width: 1920,
    height: 1080,
    fps: 25,
    bitrate_kbps: 4096,
    gop_seconds: 2,
    audio_codec: "aac",
    has_audio: true,
    status: "available",
    last_verified_at: null,
    ...over,
  }
}

const STREAMS: CameraStreamProfile[] = [
  profile({}),
  profile({
    id: "p2",
    name: "子码流",
    adapter_profile_key: "sub",
    codec: "H265",
    width: 640,
    height: 360,
    fps: 15,
    bitrate_kbps: 512,
    audio_codec: null,
    has_audio: false,
    status: "unavailable",
  }),
  // 映射表里没有的 status：必须原样显示，而不是塌成「未验证」。
  profile({
    id: "p3",
    name: "厂商自定义流",
    adapter_profile_key: "vendor-7",
    codec: "H264",
    width: 1280,
    height: 720,
    fps: 20,
    bitrate_kbps: 2048,
    audio_codec: null,
    has_audio: false,
    status: "degraded_by_adapter",
  }),
  // 整串描述都是空的：回退到 adapter_profile_key。
  profile({
    id: "p4",
    name: "未探测流",
    adapter_profile_key: "raw-profile-4",
    codec: null,
    width: null,
    height: null,
    fps: null,
    bitrate_kbps: null,
    gop_seconds: null,
    audio_codec: null,
    has_audio: false,
    status: "unknown",
  }),
  // 纯音频 profile：只能进 AUDIO 用途。
  profile({
    id: "p5",
    name: "纯音频",
    adapter_profile_key: "audio-1",
    codec: "aac",
    width: null,
    height: null,
    fps: null,
    bitrate_kbps: 64,
    gop_seconds: null,
    status: "available",
  }),
]

const BASE: CameraDetail = {
  id: "cam-1",
  name: "前门人行入口",
  enabled: true,
  maintenance: false,
  retired_at: null,
  location: "一层东侧",
  storage_label: null,
  adapter_type: "onvif",
  time_sync_mode: "monitor",
  ptz_capable: false,
  manufacturer: null,
  model: null,
  form_factor: "box",
  ip: "192.168.1.50",
  port: 554,
  rtsp_path: "/Streaming/Channels/101",
  sub_rtsp_path: "/Streaming/Channels/102",
  // 诱饵：这是 CameraSummary 的字段，不属于 CameraStreamProfile。
  video_codec: "video-codec-decoy",
  width: 1920,
  height: 1080,
  fps: 25,
  audio_codec: "aac",
  connectivity_status: "online",
  last_probe_at: null,
  last_online_at: null,
  streams: STREAMS,
  bindings: [
    { purpose: "RECORD", stream_profile_id: "p1", selection_mode: "auto" },
    { purpose: "AUDIO", stream_profile_id: "p1", selection_mode: "manual" },
  ],
}

const DIAGNOSTIC: CameraStreamDiagnostic = {
  profile: STREAMS[0],
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
  audio: {
    kind: "audio",
    codec: "aac",
    // 轨道在，但探测读不到。这是本组用例最要紧的一条。
    ready: false,
    width: null,
    height: null,
    fps: null,
    gop_seconds: null,
    sample_rate: null,
    channels: null,
  },
  verified_at: "2026-09-30T10:00:00Z",
}

type Call = { method: string; url: string; body: unknown }

let calls: Call[] = []
/** 非 null 时 verify 请求挂起不返回，用来观察 pending 态。 */
let holdVerify: Promise<Response> | null = null
let verifyResponse: CameraStreamDiagnostic = DIAGNOSTIC

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

beforeEach(() => {
  calls = []
  holdVerify = null
  verifyResponse = DIAGNOSTIC
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      calls.push({
        method,
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (url.includes("/verify")) {
        if (holdVerify) return holdVerify
        return json(verifyResponse)
      }
      if (method === "PUT") return json([])
      return json({})
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderPanel(camera: CameraDetail = BASE) {
  return renderWithProviders(<CameraStreamsPanel camera={camera} />)
}

/** 用途绑定下拉。 */
function bindingSelect(label: string) {
  return screen.getByLabelText(label) as HTMLSelectElement
}

function optionValues(select: HTMLSelectElement) {
  return Array.from(select.options).map((option) => option.value)
}

/** 某条码流在「可用媒体配置」列表里的那一行。 */
function rowOf(name: string) {
  const list = screen.getByRole("list", { name: "码流配置列表" })
  return within(list).getByText(name).closest("li") as HTMLElement
}

/** 某条用途在「可用媒体配置」列表里的那一行。 */
function trackRow(profileName: string, kind: "视频" | "音频") {
  return rowOf(profileName)
    .querySelector("ul")!
    .querySelectorAll("li")
    .item(kind === "视频" ? 0 : 1) as HTMLElement
}

function putBody() {
  const call = calls.find(
    (item) => item.method === "PUT" && item.url.includes("/stream-bindings"),
  )
  return call?.body as { bindings: Record<string, unknown>[] } | undefined
}

async function saveBindings() {
  fireEvent.click(screen.getByRole("button", { name: /保存绑定/ }))
  await waitFor(() => {
    expect(putBody()).toBeDefined()
  })
}

/* -------------------------------------------------------------------------- */

describe("码流配置 · 状态与描述串", () => {
  it("三种已知状态翻译成中文", () => {
    renderPanel()
    expect(within(rowOf("主码流")).getByText("可用")).toBeTruthy()
    expect(within(rowOf("子码流")).getByText("不可用")).toBeTruthy()
    expect(within(rowOf("未探测流")).getByText("未验证")).toBeTruthy()
  })

  it("未知状态原样显示，不塌成「未验证」", () => {
    renderPanel()
    // 映射表里没有的状态是一项信息，不是噪声；显示成「未验证」等于告诉操作员
    // 后端没写过结论，而实际上写了一个我们还不认识的结论。
    expect(
      within(rowOf("厂商自定义流")).getByText("degraded_by_adapter"),
    ).toBeTruthy()
    expect(within(rowOf("厂商自定义流")).queryByText("未验证")).toBeNull()
  })

  it("描述串读的是 codec，不是 CameraSummary 上的 video_codec", () => {
    renderPanel()
    expect(
      within(rowOf("主码流")).getByText("H264 · 1920×1080 · 25fps · 4096kbps · 音频 aac"),
    ).toBeTruthy()
    // 读错字段的表现是「什么都不显示」，不是报错，所以必须显式否定。
    expect(screen.queryByText(/video-codec-decoy/)).toBeNull()
  })

  it("整串为空时回退到 adapter_profile_key", () => {
    renderPanel()
    expect(within(rowOf("未探测流")).getByText("raw-profile-4")).toBeTruthy()
  })

  it("没有码流时给出空状态，而不是一个空 section", () => {
    renderPanel({ ...BASE, streams: [] })
    expect(screen.getByText("该通道还没有记录任何码流")).toBeTruthy()
    expect(screen.queryByRole("list", { name: "码流配置列表" })).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("码流配置 · 检测结果要真的显示出来", () => {
  it("渲染 video / audio 两条轨道，ready:false 不算成功", async () => {
    renderPanel()
    fireEvent.click(screen.getByRole("button", { name: "检测 主码流" }))

    await screen.findByText("已读到数据")
    const video = trackRow("主码流", "视频")
    const audio = trackRow("主码流", "音频")

    expect(video.textContent).toContain("H264 · 1920×1080 · 25fps · GOP 2s")
    expect(video.textContent).toContain("已读到数据")

    // 轨道存在但读不到数据，和检测成功是两回事。
    expect(audio.textContent).toContain("轨道存在，但探测读不到数据")
    expect(audio.textContent).not.toContain("已读到数据")
    expect(trackRow("主码流", "视频").textContent).not.toContain("轨道存在")
  })

  it("没有某条轨道时说的是「没有这条轨道」，不是「读不到」", async () => {
    verifyResponse = { ...DIAGNOSTIC, audio: null }
    renderPanel()
    fireEvent.click(screen.getByRole("button", { name: "检测 主码流" }))

    await screen.findByText("已读到数据")
    const audio = trackRow("主码流", "音频")
    expect(audio.textContent).toContain("没有这条轨道")
    expect(audio.textContent).not.toContain("探测读不到数据")
  })

  it("显示检测时间，并以 profile.id 作为 mutation 变量", async () => {
    renderPanel()
    fireEvent.click(screen.getByRole("button", { name: "检测 主码流" }))

    await screen.findByText("已读到数据")
    const row = rowOf("主码流")
    const time = within(row).getByText(/检测时间/)
    expect(time.textContent).toContain(formatClock(DIAGNOSTIC.verified_at))

    const call = calls.find((item) => item.url.includes("/verify"))
    expect(call?.url).toBe("/api/v1/cameras/cam-1/streams/p1/verify")
  })

  it("检测中按钮禁用并显示进行中文案", async () => {
    let release: (() => void) | null = null
    holdVerify = new Promise<Response>((resolve) => {
      release = () => resolve(json(DIAGNOSTIC))
    })
    renderPanel()

    fireEvent.click(screen.getByRole("button", { name: "检测 主码流" }))
    const button = await screen.findByRole("button", { name: "正在检测 主码流" })
    expect((button as HTMLButtonElement).disabled).toBe(true)
    expect(button.textContent).toBe("检测中…")

    await act(async () => {
      release?.()
    })
    await screen.findByText("已读到数据")
  })
})

/* -------------------------------------------------------------------------- */

describe("用途绑定 · 下拉里的选项是业务规则", () => {
  it("AUDIO 只列 has_audio 的 profile", () => {
    renderPanel()
    // p2 / p3 / p4 都是纯视频；p5 虽是纯音频 profile，但 has_audio 为真。
    expect(optionValues(bindingSelect("音频"))).toEqual(["", "p1", "p5"])
  })

  it("非 AUDIO 用途排除 codec 为 aac 的 profile", () => {
    renderPanel()
    for (const label of ["录像", "实时主码流", "实时子码流", "AI 检测", "抓图"]) {
      expect(optionValues(bindingSelect(label))).not.toContain("p5")
      expect(optionValues(bindingSelect(label))).toContain("p2")
    }
  })

  it("当前绑定被过滤掉时仍出现在下拉里，并标注出来", () => {
    // 手工改过的行：录像绑在一条纯音频 profile 上。
    renderPanel({
      ...BASE,
      bindings: [{ purpose: "RECORD", stream_profile_id: "p5", selection_mode: "manual" }],
    })
    const select = bindingSelect("录像")
    expect(select.value).toBe("p5")
    // 原生 select 遇到没有对应 option 的 value 会显示成空，操作员就会以为
    // 这条用途没绑——那是一次静默的误报。
    expect(
      Array.from(select.options).map((option) => option.textContent),
    ).toContain("纯音频（当前绑定）")
  })

  it("一个用途都没绑定时，六个下拉照样全部渲染", () => {
    renderPanel({ ...BASE, bindings: [] })
    for (const label of ["录像", "实时主码流", "实时子码流", "AI 检测", "抓图", "音频"]) {
      expect(optionValues(bindingSelect(label))[0]).toBe("")
    }
    expect(bindingSelect("录像").value).toBe("")
  })
})

/* -------------------------------------------------------------------------- */

describe("用途绑定 · 保存提交完整集合", () => {
  it("动过的用途存 manual：auto 会让直播路径把操作员的选择丢掉", async () => {
    renderPanel()

    fireEvent.change(bindingSelect("录像"), { target: { value: "p2" } })
    fireEvent.change(bindingSelect("抓图"), { target: { value: "p3" } })
    await saveBindings()

    // RECORD 原本是 `auto`。`auto` 的运行时含义是直播路径**每次请求都重新按
    // H.264 评分挑码流**（cameras/api.py:2331-2345），所以把 p2 存成 auto 等于
    // 告诉服务端「你继续自己挑」——操作员的显式选择会被丢弃，保存却报成功。
    // 他刚点过这个下拉，那就是一次 manual 选择。
    expect(putBody()?.bindings).toEqual([
      { purpose: "RECORD", stream_profile_id: "p2", selection_mode: "manual" },
      { purpose: "SNAPSHOT", stream_profile_id: "p3", selection_mode: "manual" },
      { purpose: "AUDIO", stream_profile_id: "p1", selection_mode: "manual" },
    ])
  })

  it("没动过的用途原样保留 auto：这个表单不替服务端做主", async () => {
    renderPanel()

    // 只动 SNAPSHOT。RECORD 的 auto 必须原样回去——端点是整体替换，表单把这个
    // 用途顺手写成 manual，就等于无声地收走了服务端重新挑选的权利。Vue 版就是
    // 因为硬编码 manual 一直在犯这个错。
    fireEvent.change(bindingSelect("抓图"), { target: { value: "p2" } })
    await saveBindings()

    const bindings = (putBody()?.bindings ?? []) as {
      purpose: string
      stream_profile_id: string
      selection_mode: string
    }[]
    const record = bindings.find((item) => item.purpose === "RECORD")
    expect(record).toEqual({
      purpose: "RECORD",
      stream_profile_id: "p1",
      selection_mode: "auto",
    })
  })

  it("没动过的用途也必须一起提交——端点是整体替换", async () => {
    renderPanel()
    fireEvent.change(bindingSelect("抓图"), { target: { value: "p2" } })
    await saveBindings()

    // 端点先删光再重建（cameras/service.py:569-583），漏掉 AUDIO 就是解绑它。
    expect(putBody()?.bindings.map((item) => item.purpose).sort()).toEqual([
      "AUDIO",
      "RECORD",
      "SNAPSHOT",
    ])
  })

  it("清空一个用途后，其余绑定仍要跟着一起发", async () => {
    renderPanel()
    fireEvent.change(bindingSelect("音频"), { target: { value: "" } })
    await saveBindings()

    expect(putBody()?.bindings).toEqual([
      { purpose: "RECORD", stream_profile_id: "p1", selection_mode: "auto" },
    ])
  })

  it("没有绑定时提交空集合，而不是省略请求", async () => {
    renderPanel({ ...BASE, bindings: [] })
    await saveBindings()

    expect(putBody()?.bindings).toEqual([])
  })
})

/* -------------------------------------------------------------------------- */

describe("用途绑定 · 换一条通道就重新播种", () => {
  it("交互过的下拉不会把状态带到下一条通道", async () => {
    const other: CameraDetail = {
      ...BASE,
      id: "cam-2",
      name: "后院周界",
      streams: [profile({ id: "q1", name: "周界主码流", codec: "H264" })],
      bindings: [{ purpose: "RECORD", stream_profile_id: "q1", selection_mode: "auto" }],
    }

    function Harness() {
      const [index, setIndex] = useState(0)
      return (
        <div>
          <button type="button" onClick={() => setIndex(1)}>
            切换通道
          </button>
          <CameraStreamsPanel camera={index === 0 ? BASE : other} />
        </div>
      )
    }
    renderWithProviders(<Harness />)

    fireEvent.change(bindingSelect("录像"), { target: { value: "p3" } })
    expect(bindingSelect("录像").value).toBe("p3")

    fireEvent.click(screen.getByRole("button", { name: "切换通道" }))
    // 没重新播种的话，这里要么停在 p3（p3 已不在候选里，显示成空），要么
    // 停在 p1——两个都不是这一条通道真实的绑定。
    expect(bindingSelect("录像").value).toBe("q1")
    expect(optionValues(bindingSelect("录像"))).toEqual(["", "q1"])
  })
})
