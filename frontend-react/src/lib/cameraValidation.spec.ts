import { describe, expect, it } from "vitest"

import {
  acceptsDeviceFields,
  allowedTimeSyncModes,
  validateBindings,
  validateCameraForm,
  validateCameraName,
  validateRtspUrl,
  validateTimeSyncMode,
} from "./cameraValidation"

/**
 * These rules exist because the backend's corresponding failures are *silent*
 * or arrive too late to be actionable. Each test names the backend behaviour
 * it is standing in front of.
 */

describe("validateRtspUrl", () => {
  it("accepts a plain rtsp URL", () => {
    expect(validateRtspUrl("rtsp://192.168.1.50:554/stream")).toBeNull()
  })

  it("accepts credentials in the URL", () => {
    // How this product is actually deployed; rejecting it would break every
    // existing camera.
    expect(
      validateRtspUrl("rtsp://admin:pass@192.168.1.50:554/live"),
    ).toBeNull()
  })

  it("accepts a URL with no explicit port", () => {
    // The backend defaults to 554 rather than rejecting it.
    expect(validateRtspUrl("rtsp://cam.example.com/stream")).toBeNull()
  })

  it("rejects a non-rtsp scheme", () => {
    expect(validateRtspUrl("http://192.168.1.50/stream")).toContain("rtsp://")
  })

  it("rejects an empty value", () => {
    expect(validateRtspUrl("   ")).toContain("不能为空")
  })

  it("rejects something that is not a URL at all", () => {
    expect(validateRtspUrl("not a url")).toContain("格式不正确")
  })

  it("rejects a non-numeric port", () => {
    // The URL parser refuses a non-numeric port on a non-special scheme
    // outright, so this lands in the generic "malformed" branch rather than
    // a port-specific one. Either way the value never reaches the backend.
    expect(validateRtspUrl("rtsp://192.168.1.50:abc/stream")).toBeTruthy()
  })
})

describe("validateCameraName", () => {
  it("requires a value", () => {
    expect(validateCameraName("  ")).toContain("不能为空")
  })

  it("enforces the 128 character limit", () => {
    expect(validateCameraName("x".repeat(129))).toContain("128")
    expect(validateCameraName("x".repeat(128))).toBeNull()
  })
})

describe("time sync mode", () => {
  it("offers only ignore for a manual RTSP camera", () => {
    // `cameras/service.py:405` rejects anything else for a non-ONVIF device.
    expect(allowedTimeSyncModes("manual_rtsp")).toEqual(["ignore"])
    expect(allowedTimeSyncModes(null)).toEqual(["ignore"])
    expect(allowedTimeSyncModes("")).toEqual(["ignore"])
  })

  it("offers all three for an ONVIF camera", () => {
    expect(allowedTimeSyncModes("onvif")).toEqual([
      "manage_ntp",
      "monitor",
      "ignore",
    ])
  })

  it("explains why an unsupported mode is refused", () => {
    const message = validateTimeSyncMode("manage_ntp", "manual_rtsp")
    expect(message).toContain("ONVIF")
  })

  it("accepts every offered mode", () => {
    for (const mode of allowedTimeSyncModes("onvif")) {
      expect(validateTimeSyncMode(mode, "onvif")).toBeNull()
    }
  })
})

describe("acceptsDeviceFields", () => {
  it("is false exactly when the backend would discard the values", () => {
    // `cameras/service.py:438` drops these when device_id is null — with a
    // 200 response and no warning, which is why the form must not offer them.
    expect(acceptsDeviceFields(null)).toBe(false)
    expect(acceptsDeviceFields("")).toBe(false)
    expect(acceptsDeviceFields("device-1")).toBe(true)
  })
})

describe("validateBindings", () => {
  it("accepts a well-formed set", () => {
    expect(
      validateBindings([
        { purpose: "RECORD", streamProfileId: "p1" },
        { purpose: "LIVE_LOW", streamProfileId: "p2" },
      ]),
    ).toEqual([])
  })

  it("catches a repeated purpose before the whole batch is rejected", () => {
    const problems = validateBindings([
      { purpose: "RECORD", streamProfileId: "p1" },
      { purpose: "RECORD", streamProfileId: "p2" },
    ])
    expect(problems).toEqual([{ kind: "duplicate_purpose", purpose: "RECORD" }])
  })

  it("catches a purpose with no profile selected", () => {
    const problems = validateBindings([
      { purpose: "RECORD", streamProfileId: "" },
    ])
    expect(problems).toEqual([{ kind: "missing_profile", purpose: "RECORD" }])
  })

  it("reports both kinds at once", () => {
    const problems = validateBindings([
      { purpose: "RECORD", streamProfileId: "" },
      { purpose: "RECORD", streamProfileId: "p2" },
    ])
    expect(problems.map((p) => p.kind).sort()).toEqual([
      "duplicate_purpose",
      "missing_profile",
    ])
  })
})

describe("validateCameraForm", () => {
  it("requires an RTSP URL only when creating", () => {
    const creating = validateCameraForm({
      name: "前门",
      adapterType: "manual_rtsp",
      rtspUrl: "",
      isCreate: true,
    })
    expect(creating.map((e) => e.field)).toContain("rtsp_url")

    const editing = validateCameraForm({
      name: "前门",
      adapterType: "manual_rtsp",
      isCreate: false,
    })
    expect(editing).toEqual([])
  })

  it("collects every problem rather than stopping at the first", () => {
    const errors = validateCameraForm({
      name: "",
      adapterType: "manual_rtsp",
      timeSyncMode: "manage_ntp",
      rtspUrl: "http://bad",
      isCreate: true,
    })
    expect(errors.map((e) => e.field).sort()).toEqual([
      "name",
      "rtsp_url",
      "time_sync_mode",
    ])
  })
})
