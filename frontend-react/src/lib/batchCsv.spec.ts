import { createElement } from "react"
import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { OnboardingBatch } from "../components/cameras/OnboardingBatch"
import { renderWithProviders } from "../test-utils"
import {
  BATCH_CSV_HEADERS,
  CsvParseError,
  buildBatchCsvTemplate,
  parseBatchCsv,
  parseCsvRecords,
} from "./batchCsv"
import type {
  OnvifIdentityState,
  OnvifInspectionView,
  OnvifProfileView,
} from "../api/onboarding"

/**
 * Two kinds of claim, and they are not the same kind.
 *
 * The **parser** tests are about files. A BOM, a CRLF, a quoted comma, an
 * escaped quote, a reordered header, a column nobody defined — each is
 * something an operator's spreadsheet produces, and a `split(",")` turns every
 * one of them into a silently wrong device rather than an error.
 *
 * The **component** tests are about the one fact the feature rests on: there is
 * no bulk endpoint and no dry-run, so a batch is a serial loop of writing
 * requests. What matters is therefore *what was sent, in what order, and what
 * was not sent* — a `review` row that must not import, a row that must not
 * start before the previous one finished, and a password that has to be in the
 * request body and nowhere else.
 */

const BOM = "\uFEFF"
const PASSWORD = "sup3r-s3cret-pw"

/* -------------------------------------------------------------------------- */
/* Fetch stub                                                                  */
/* -------------------------------------------------------------------------- */

type Call = { method: string; url: string; body: Record<string, unknown> | undefined }

let calls: Call[] = []
/** Fails (HTTP) whichever calls the predicate picks; the rest answer normally. */
let failWhen: ((call: Call) => boolean) | null = null
/** Rejects the request outright, i.e. a network failure rather than a 4xx. */
let rejectWhen: ((call: Call) => boolean) | null = null
let failure: { status: number; code: string; message: string } = {
  status: 422,
  code: "onvif_connection_failed",
  message: "onvif connection failed",
}
/** Identity is decided per row, so the verdict is a function of the request. */
let identityFor: (call: Call) => OnvifIdentityState = () => "new_device"
/** How many cameras one import claims to have produced. */
let importedCameras = 1
/** Parks the first matching request until the test lets it finish. */
let gate: {
  match: (url: string) => boolean
  promise: Promise<void>
  release: () => void
} | null = null

const PROFILE: OnvifProfileView = {
  token: "p1",
  name: "主码流",
  video_source_token: "vs1",
  codec: "H.264",
  width: 1920,
  height: 1080,
  fps: 25,
  bitrate_kbps: 4096,
  gop_seconds: 2,
  audio_codec: null,
  has_audio: false,
  stream_uri_available: true,
}

function inspection(call: Call): OnvifInspectionView {
  const state = identityFor(call)
  return {
    device: {
      manufacturer: "Hikvision",
      model: "DS-2CD",
      firmware_version: "5.7",
      serial_number: "SN1",
      hardware_id: null,
    },
    capabilities: ["events"],
    profiles: [PROFILE],
    identity: {
      state,
      matched_device_id: state === "new_device" ? null : "dev-9",
      matched_device_name: state === "new_device" ? null : "已有前门",
      conflicting_device_ids: state === "identity_conflict" ? ["dev-9", "dev-3"] : [],
      reason: null,
    },
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

// jsdom implements neither object-URL method, and `vi.stubGlobal("URL", …)`
// would replace the constructor the api client itself uses. Swapped in place,
// as `components/storage/BackupPanel.spec.tsx:88-106` does it.
const realCreateObjectURL = URL.createObjectURL
const realRevokeObjectURL = URL.revokeObjectURL
let objectUrls: Blob[] = []
let downloadAnchors: HTMLAnchorElement[] = []

beforeEach(() => {
  calls = []
  failWhen = null
  rejectWhen = null
  gate = null
  identityFor = () => "new_device"
  importedCameras = 1
  objectUrls = []
  downloadAnchors = []
  failure = {
    status: 422,
    code: "onvif_connection_failed",
    message: "onvif connection failed",
  }

  URL.createObjectURL = ((blob: Blob) => {
    objectUrls.push(blob)
    return "blob:batch-template"
  }) as unknown as typeof URL.createObjectURL
  URL.revokeObjectURL = (() => {}) as typeof URL.revokeObjectURL

  // The download is asserted through the bytes handed to the object URL, so the
  // anchor's click is stubbed: jsdom logs a navigation error for a `blob:`
  // href and that says nothing about the template.
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function click(
    this: HTMLAnchorElement,
  ) {
    downloadAnchors.push(this)
  })

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      const call: Call = { method, url, body }
      calls.push(call)

      if (gate && gate.match(url)) {
        const held = gate
        gate = null
        await held.promise
      }

      if (rejectWhen?.(call)) throw new TypeError("Failed to fetch")
      if (failWhen?.(call)) {
        return json(
          { error: { code: failure.code, message: failure.message } },
          failure.status,
        )
      }
      // Order matters: `/cameras/onvif/test` also contains `/cameras`, and the
      // create path is the bare one.
      if (url.includes("/cameras/onvif/test")) return json(inspection(call))
      if (url.includes("/cameras/onvif/import")) {
        return json({
          device_id: "dev-new",
          reconfigured: false,
          cameras: Array.from({ length: importedCameras }, (_, index) => ({
            id: `cam-${index + 1}`,
          })),
        })
      }
      if (url.includes("/cameras/test")) {
        return json({
          ok: true,
          streams: [
            {
              role: "primary",
              name: "主码流",
              video: {
                kind: "video",
                codec: "H.264",
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
        })
      }
      if (method === "POST" && url === "/api/v1/cameras") return json({ id: "cam-new" })
      return json([])
    }),
  )
})

afterEach(() => {
  vi.restoreAllMocks()
  URL.createObjectURL = realCreateObjectURL
  URL.revokeObjectURL = realRevokeObjectURL
  vi.unstubAllGlobals()
  calls = []
  failWhen = null
  rejectWhen = null
  gate = null
})

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

function renderBatch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  // This spec is a .ts file, so the element is built without JSX.
  return renderWithProviders(createElement(OnboardingBatch), { client })
}

const HEADERS = BATCH_CSV_HEADERS.join(",")

/** A CSV built from the real column order, so a test names only what it means. */
function csv(rows: string[][], headers: string = HEADERS): string {
  return [headers, ...rows].join("\n")
}

function onvifRow(host: string, name: string): string[] {
  return [
    "onvif",
    name,
    "大厅",
    host,
    "80",
    "80",
    "admin",
    PASSWORD,
    "",
    "",
    "",
    "",
    "店内",
    "A 区",
    "备注",
  ]
}

function rtspRow(host: string, name: string): string[] {
  return [
    "rtsp",
    name,
    "B 座",
    host,
    "554",
    "",
    "admin",
    PASSWORD,
    "Streaming/Channels/101",
    "Streaming/Channels/102",
    "",
    "",
    "店内",
    "B 区",
    "备注",
  ]
}

async function pickFile(text: string, name = "cams.csv") {
  const file = new File([text], name, { type: "text/csv" })
  fireEvent.change(screen.getByLabelText("批量导入 CSV 文件"), {
    target: { files: [file] },
  })
  return file
}

function batchList() {
  return screen.getByRole("list", { name: "批量行列表" })
}

/**
 * A row, found by its heading.
 *
 * The heading is the one string on the card that never changes — not the state
 * badge, not the message — so a test can hold on to a row across a state
 * transition without knowing what that transition will say.
 */
function batchRow(line: number) {
  return within(batchList()).getByText(new RegExp(`^第 ${line} 行 · `))
    .closest("li") as HTMLElement
}

/** The completion summary, scoped: the same claim is made elsewhere on screen. */
function summaryBox() {
  return screen.getByRole("status", { name: "批量导入结果" })
}

function startButton() {
  return screen.getByRole("button", { name: /开始导入/ })
}

function postsTo(fragment: string) {
  return calls.filter((c) => c.method === "POST" && c.url.includes(fragment))
}

function createCalls() {
  return calls.filter((c) => c.method === "POST" && c.url === "/api/v1/cameras")
}

/** Parks the next matching request until `release()` is called. */
function holdNext(match: (url: string) => boolean) {
  let release!: () => void
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  gate = { match, promise, release }
  return { release }
}

function readBlob(blob: Blob): Promise<string> {
  // jsdom's Blob implements neither `text()` nor `arrayBuffer()`.
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ""))
    reader.onerror = () => reject(new Error("unreadable"))
    reader.readAsText(blob)
  })
}

/* -------------------------------------------------------------------------- */
/* Parser                                                                      */
/* -------------------------------------------------------------------------- */

describe("batchCsv · 文件解析", () => {
  it("BOM 不会混进第一列表头，否则按名字取值全部落空", () => {
    const parsed = parseCsvRecords(`${BOM}kind,name\nonvif,前门`)
    expect(parsed.headers[0]).toBe("kind")
    expect(parsed.rows[0].values.kind).toBe("onvif")
  })

  it("CRLF 不会把 \\r 留在每个值里", () => {
    const row = parseBatchCsv("kind,name,host\r\nonvif,前门,192.168.1.64\r\n")[0]
    expect(row.name).toBe("前门")
    expect(row.host).toBe("192.168.1.64")
  })

  it("引号里的逗号和转义引号都能读出来", () => {
    const row = parseBatchCsv(
      csv([
        [
          "onvif",
          '"前门, 东侧"',
          '"A 座, 3 层"',
          "192.168.1.64",
          "80",
          "80",
          "admin",
          PASSWORD,
          "",
          "",
          "",
          "",
          "店内",
          "A 区",
          '"他说""好"""',
        ],
      ]),
    )[0]
    expect(row.name).toBe("前门, 东侧")
    expect(row.location).toBe("A 座, 3 层")
    expect(row.remark).toBe('他说"好"')
    expect(row.errors).toEqual([])
  })

  it("表头按名字匹配，顺序换了照样能取到", () => {
    const shuffled = [
      "remark",
      "host",
      "kind",
      "password",
      "name",
      "onvif_port",
      "username",
    ].join(",")
    const row = parseBatchCsv(
      csv(
        [["换行的表头", "192.168.1.64", "onvif", PASSWORD, "侧门", "80", "admin"]],
        shuffled,
      ),
    )[0]
    expect(row.kind).toBe("onvif")
    expect(row.name).toBe("侧门")
    expect(row.host).toBe("192.168.1.64")
    expect(row.onvifPort).toBe(80)
    expect(row.errors).toEqual([])
  })

  it("多出来的列被忽略，而不是让整个文件作废", () => {
    // An operator's own spreadsheet will have columns we never defined, and
    // the alternative is a batch form that only accepts one exact export.
    const withExtras = [...BATCH_CSV_HEADERS, "firmware", "vendor"].join(",")
    const row = parseBatchCsv(
      csv(
        [
          [
            "onvif",
            "前门",
            "大厅",
            "192.168.1.64",
            "80",
            "80",
            "admin",
            PASSWORD,
            "",
            "",
            "",
            "",
            "店内",
            "A 区",
            "备注",
            "5.7.3",
            " Hik ",
          ],
        ],
        withExtras,
      ),
    )[0]
    expect(row.errors).toEqual([])
    expect(row.name).toBe("前门")
  })

  it("缺必填字段只报这一行，后面的行照常解析", () => {
    const rows = parseBatchCsv(
      csv([onvifRow("", "缺地址"), onvifRow("192.168.1.65", "正常")]),
    )
    expect(rows).toHaveLength(2)
    expect(rows[0].errors.join(" ")).toContain("缺少 host")
    expect(rows[1].errors).toEqual([])
    expect(rows[1].host).toBe("192.168.1.65")
  })

  it("rtsp 行缺名称和地址会被逐条点名", () => {
    const row = parseBatchCsv(csv([rtspRow("", "")]))[0]
    expect(row.errors.join(" ")).toContain("缺少 name")
    expect(row.errors.join(" ")).toContain("缺少 host")
  })

  it("未知列不算错，同名列才算：同名两列无法区分是哪一列的值", () => {
    expect(() => parseCsvRecords("kind,name,remark\na,b,c")).not.toThrow()
    try {
      parseCsvRecords("kind,name,name\na,b,c")
      throw new Error("should have thrown")
    } catch (caught) {
      expect(caught).toBeInstanceOf(CsvParseError)
      expect((caught as CsvParseError).code).toBe("csv_duplicate_header")
    }
  })

  it("引号没闭合是文件级错误，不是某一行的错误", () => {
    try {
      parseCsvRecords('kind,name\nonvif,"前门')
      throw new Error("should have thrown")
    } catch (caught) {
      expect((caught as CsvParseError).code).toBe("csv_unterminated_quote")
      expect((caught as CsvParseError).line).toBe(2)
    }
  })

  it("模板带全部 15 列表头，并且能被自己的解析器读回两行合法数据", () => {
    const template = buildBatchCsvTemplate()
    for (const header of BATCH_CSV_HEADERS) expect(template).toContain(header)
    expect(template.replace(new RegExp(`^${BOM}`), "").split("\r\n")[0]).toBe(HEADERS)

    // The strongest form of the claim: the file we hand out is one our own
    // parser accepts, so an operator can start from it without editing it.
    const rows = parseBatchCsv(template)
    expect(rows).toHaveLength(2)
    expect(rows.every((row) => row.errors.length === 0)).toBe(true)
    expect(rows.map((row) => row.kind)).toEqual(["onvif", "rtsp"])
  })
})

/* -------------------------------------------------------------------------- */
/* Preview                                                                     */
/* -------------------------------------------------------------------------- */

describe("OnboardingBatch · 选文件与预览", () => {
  it("选完文件只做本地解析，一个请求都不发", async () => {
    renderBatch()
    await pickFile(csv([onvifRow("192.168.1.64", "前门")]))

    await waitFor(() => expect(batchList()).toBeTruthy())
    expect(calls).toHaveLength(0)
    // The preview is a parse check, and has to say so: the only endpoint that
    // could "validate" a row is the one that writes it.
    expect(screen.getByText(/只是本地的解析结果/)).toBeTruthy()
  })

  it("预览列出每一行，并指出格式有误的那一行", async () => {
    renderBatch()
    await pickFile(csv([onvifRow("", "缺地址"), onvifRow("192.168.1.65", "正常")]))

    await waitFor(() => expect(batchList()).toBeTruthy())
    expect(within(batchRow(2)).getByText(/缺少 host/)).toBeTruthy()
    expect(screen.getByText(/可导入 1 行 · 格式有误 1 行/)).toBeTruthy()
  })

  it("文件坏了给的是文件级提示，且不留下任何行", async () => {
    renderBatch()
    await pickFile('kind,name\nonvif,"前门')

    expect(await screen.findByText(/引号没有闭合/)).toBeTruthy()
    expect(screen.queryByRole("list", { name: "批量行列表" })).toBeNull()
  })

  it("下载的模板就是解析器认识的那份，包含全部 15 列表头", async () => {
    renderBatch()
    fireEvent.click(screen.getByRole("button", { name: /下载 CSV 模板/ }))

    expect(objectUrls).toHaveLength(1)
    const text = await readBlob(objectUrls[0])
    const headerLine = text.replace(new RegExp(`^${BOM}`), "").split("\r\n")[0]
    expect(headerLine.split(",")).toEqual([...BATCH_CSV_HEADERS])
    // The anchor is thrown away and the object URL handed back.
    expect(downloadAnchors).toHaveLength(1)
    expect(downloadAnchors[0].download).toBe("camera-onboarding-template.csv")
    expect(document.querySelector("a[download]")).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */
/* The two paths                                                               */
/* -------------------------------------------------------------------------- */

describe("OnboardingBatch · 两种行的两条路径", () => {
  it("ONVIF 行先检查再导入，且导入的就是刚刚验证过的那些码流", async () => {
    renderBatch()
    await pickFile(csv([onvifRow("192.168.1.64", "前门")]))
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    await waitFor(() => expect(postsTo("/cameras/onvif/import")).toHaveLength(1))
    const inspect = postsTo("/cameras/onvif/test")[0].body as Record<string, unknown>
    const importBody = postsTo("/cameras/onvif/import")[0].body as Record<string, unknown>

    // `profile_tokens: null` would mean "every profile" and `[]` is the ask
    // that comes back 422 onvif_no_usable_profiles, so the batch sends the
    // tokens it saw itself verify.
    expect(importBody.profile_tokens).toEqual(["p1"])
    expect(inspect).toMatchObject({ host: "192.168.1.64", port: 80, username: "admin" })
    expect(inspect).not.toHaveProperty("profile_tokens")
    // The identity the server just returned is what the import body is built
    // from — the only way `confirm_existing_device_id` can ever be the id the
    // server actually matched.
    expect(importBody).not.toHaveProperty("confirm_existing_device_id")
    expect(within(batchRow(2)).getByText("成功")).toBeTruthy()
  })

  it("rtsp 行先测试再创建，地址按 host + 端口 + 路径拼出来", async () => {
    renderBatch()
    await pickFile(csv([rtspRow("192.168.1.65", "停车场")]))
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    await waitFor(() => expect(createCalls()).toHaveLength(1))
    const probed = postsTo("/cameras/test")
    expect(probed).toHaveLength(1)
    const primary = probed[0].body as {
      primary_stream: { rtsp_url: string }
      secondary_stream: { rtsp_url: string } | null
    }
    // `POST /cameras` checks only URL syntax (`cameras/service.py:104,112`),
    // so probe-before-create is a client convention worth keeping.
    expect(primary.primary_stream.rtsp_url).toBe(
      `rtsp://admin:${PASSWORD}@192.168.1.65:554/Streaming/Channels/101`,
    )
    expect(primary.secondary_stream?.rtsp_url).toContain("Streaming/Channels/102")
    // One body, two calls — the camera is created from exactly what was probed.
    expect(createCalls()[0].body).toEqual(probed[0].body)
    expect(within(batchRow(2)).getByText("成功")).toBeTruthy()
  })

  it("一行建出多台机位时是「已创建多台」，不是失败", async () => {
    importedCameras = 2
    renderBatch()
    await pickFile(csv([onvifRow("192.168.1.64", "多通道设备")]))
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    // Cameras are grouped by `video_source_token`
    // (`onvif_onboarding.py:1149-1176`), so one row can legitimately be many.
    expect(await within(batchRow(2)).findByText("已创建多台")).toBeTruthy()
    expect(within(batchRow(2)).getByText(/这一行创建了 2 台机位/)).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */
/* review is not failed                                                        */
/* -------------------------------------------------------------------------- */

describe("OnboardingBatch · 身份不是 new_device 时不导入", () => {
  it("same_device 是「需人工确认」，不是失败，而且一个导入请求都不发", async () => {
    identityFor = () => "same_device"
    renderBatch()
    await pickFile(csv([onvifRow("192.168.1.64", "前门")]))
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    expect(
      await screen.findByText(/^完成：成功 0 · 已创建多台 0 · 需人工确认 1 · 失败 0/),
    ).toBeTruthy()
    const row = batchRow(2)
    expect(within(row).getByText("需人工确认")).toBeTruthy()
    expect(within(row).queryByText("失败")).toBeNull()
    // Retrying this row blindly would 409 every time.
    expect(postsTo("/cameras/onvif/import")).toHaveLength(0)
  })

  it("identity_conflict 同样是需人工确认，并说清楚没有前进的路", async () => {
    identityFor = () => "identity_conflict"
    renderBatch()
    await pickFile(csv([onvifRow("192.168.1.64", "前门")]))
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    const row = batchRow(2)
    expect(await within(row).findByText("需人工确认")).toBeTruthy()
    // The contract's own blocked sentence, not a generic failure.
    expect(within(row).getByText(/无法通过导入新增/)).toBeTruthy()
    expect(postsTo("/cameras/onvif/import")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */
/* Serial, stoppable, not atomic                                               */
/* -------------------------------------------------------------------------- */

describe("OnboardingBatch · 串行、可中断、不原子", () => {
  it("一行还在飞的时候，下一行还没有开始请求", async () => {
    const held = holdNext((url) => url.includes("/cameras/onvif/test"))
    renderBatch()
    await pickFile(
      csv([onvifRow("192.168.1.64", "第一台"), onvifRow("192.168.1.65", "第二台")]),
    )
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    await waitFor(() => expect(postsTo("/cameras/onvif/test")).toHaveLength(1))
    // A batch is a serial loop of writing requests. Anything concurrent would
    // turn a slow file into a burst of 10 s inspections.
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(postsTo("/cameras/onvif/test")).toHaveLength(1)
    expect(postsTo("/cameras/onvif/import")).toHaveLength(0)
    expect(within(batchRow(2)).getByText("进行中")).toBeTruthy()
    expect(within(batchRow(3)).getByText("等待导入")).toBeTruthy()

    held.release()
    expect(
      await screen.findByText(/^完成：成功 2 · 已创建多台 0 · 需人工确认 0 · 失败 0/),
    ).toBeTruthy()
    expect(postsTo("/cameras/onvif/test")).toHaveLength(2)
  })

  it("中途停止会在下一行之前停下，已经跑完的结果原样保留", async () => {
    const held = holdNext((url) => url.includes("/cameras/onvif/test"))
    renderBatch()
    await pickFile(
      csv([
        onvifRow("192.168.1.64", "第一台"),
        onvifRow("192.168.1.65", "第二台"),
        onvifRow("192.168.1.66", "第三台"),
      ]),
    )
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())
    await waitFor(() => expect(postsTo("/cameras/onvif/test")).toHaveLength(1))

    // A 20-row file is minutes long, so stopping has to be possible. The
    // in-flight request cannot be recalled — no abort signal reaches these
    // endpoints — so "stop" means "no further rows", not "undo this one".
    fireEvent.click(screen.getByRole("button", { name: "停止导入" }))
    held.release()

    expect(await screen.findByText(/还有 2 行没有开始/)).toBeTruthy()
    expect(within(batchRow(2)).getByText("成功")).toBeTruthy()
    expect(within(batchRow(3)).getByText("等待导入")).toBeTruthy()
    expect(within(batchRow(4)).getByText("等待导入")).toBeTruthy()
    expect(postsTo("/cameras/onvif/test")).toHaveLength(1)
    expect(postsTo("/cameras/onvif/import")).toHaveLength(1)
  })

  it("汇总说清成功 / 需确认 / 失败，并说明失败不会回滚", async () => {
    // The identity verdict is per row, not per file: the second host is a
    // device we already know, the third is simply unreachable.
    identityFor = (call) =>
      (call.body as { host?: string })?.host === "192.168.1.65" ? "same_device" : "new_device"
    failWhen = (call) =>
      call.url.includes("/cameras/onvif/import") &&
      (call.body as { host?: string })?.host === "192.168.1.67"
    renderBatch()
    await pickFile(
      csv([
        onvifRow("192.168.1.64", "成功的那台"),
        onvifRow("192.168.1.65", "已存在的设备"),
        onvifRow("192.168.1.67", "连不上的设备"),
      ]),
    )
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    expect(
      await screen.findByText(/^完成：成功 1 · 已创建多台 0 · 需人工确认 1 · 失败 1/),
    ).toBeTruthy()
    // The consequence belongs on the screen, not in a tooltip: there is no
    // rollback to run and no dry-run that could have caught this earlier.
    expect(within(summaryBox()).getByText(/不会回滚/)).toBeTruthy()
    // Translated, and no server prose leaking through.
    expect(within(batchRow(4)).getByText(/无法连接该设备/)).toBeTruthy()
    expect(within(batchRow(3)).getByText("需人工确认")).toBeTruthy()
  })

  it("一行的请求直接失败（断网）也不会中断后面的行", async () => {
    rejectWhen = (call) =>
      call.url.includes("/cameras/onvif/test") &&
      (call.body as { host?: string })?.host === "192.168.1.67"
    renderBatch()
    await pickFile(
      csv([onvifRow("192.168.1.67", "第一台"), onvifRow("192.168.1.68", "第二台")]),
    )
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    expect(
      await screen.findByText(/^完成：成功 1 · 已创建多台 0 · 需人工确认 0 · 失败 1/),
    ).toBeTruthy()
    // A network blip on one camera is not a verdict on the next one.
    expect(within(batchRow(2)).getByText(/请求没有到达服务端/)).toBeTruthy()
    const imported = postsTo("/cameras/onvif/import")
    expect(imported).toHaveLength(1)
    expect((imported[0].body as { host: string }).host).toBe("192.168.1.68")
  })

  it("格式有误的行是失败并指出行号，其余行照常导入", async () => {
    renderBatch()
    await pickFile(csv([onvifRow("", "缺地址"), onvifRow("192.168.1.65", "正常")]))
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    expect(
      await screen.findByText(/^完成：成功 1 · 已创建多台 0 · 需人工确认 0 · 失败 1/),
    ).toBeTruthy()
    // The reason names the line, so it can be found in the spreadsheet.
    expect(within(batchRow(2)).getByText(/^第 2 行：缺少 host/)).toBeTruthy()
    expect(postsTo("/cameras/onvif/test")).toHaveLength(1)
  })
})

/* -------------------------------------------------------------------------- */
/* The password                                                                */
/* -------------------------------------------------------------------------- */

describe("OnboardingBatch · 密码只进请求体", () => {
  it("密码出现在请求体里，且不出现在任何可见文本、输入框或通知中", async () => {
    renderBatch()
    await pickFile(
      csv([onvifRow("192.168.1.64", "前门"), rtspRow("192.168.1.65", "停车场")]),
    )
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())
    expect(
      await screen.findByText(/^完成：成功 2 · 已创建多台 0 · 需人工确认 0 · 失败 0/),
    ).toBeTruthy()

    // Not vacuous: the password really was sent. Without this, "the DOM does
    // not contain it" would also pass on a batch that never sent anything.
    const inspectBody = postsTo("/cameras/onvif/test")[0].body as { password: string }
    const rtspBody = postsTo("/cameras/test")[0].body as {
      primary_stream: { rtsp_url: string }
    }
    expect(inspectBody.password).toBe(PASSWORD)
    expect(rtspBody.primary_stream.rtsp_url).toContain(PASSWORD)

    // Nowhere else: not the row, not the preview, not a toast, not an input.
    expect(document.body.textContent).not.toContain(PASSWORD)
    const values = Array.from(document.querySelectorAll("input")).map(
      (input) => (input as HTMLInputElement).value,
    )
    expect(values).not.toContain(PASSWORD)
  })

  it("预览里展示的是 main_path，不是拼好的地址", async () => {
    renderBatch()
    await pickFile(csv([rtspRow("192.168.1.65", "停车场")]))
    await waitFor(() => expect(batchList()).toBeTruthy())

    // The assembled `rtsp://user:pass@…` is itself the secret, so the row shows
    // the path the operator typed instead.
    expect(within(batchRow(2)).getByText("主码流：Streaming/Channels/101")).toBeTruthy()
    expect(document.body.textContent).not.toContain(PASSWORD)
  })

  it("一行失败时，报错里没有密码", async () => {
    failWhen = (call) => call.url.includes("/cameras/onvif/import")
    renderBatch()
    await pickFile(csv([onvifRow("192.168.1.64", "前门")]))
    await waitFor(() => expect(batchList()).toBeTruthy())

    fireEvent.click(startButton())

    expect(await screen.findByText(/^完成：成功 0/)).toBeTruthy()
    expect(within(batchRow(2)).getByText(/无法连接该设备/)).toBeTruthy()
    expect(document.body.textContent).not.toContain(PASSWORD)
  })
})
