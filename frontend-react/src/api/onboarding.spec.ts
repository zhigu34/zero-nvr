import { afterEach, describe, expect, it, vi } from "vitest"

import {
  buildManualCameraInput,
  buildOnvifImportInput,
  confirmationIdFor,
  describeProbeStream,
  emptyManualCameraForm,
  emptyOnvifForm,
  identityAction,
  identityBlockedReason,
  importPersistedAnyway,
  importableProfiles,
  inspectOnvif,
  startDiscovery,
  validateManualCameraForm,
  validateOnvifForm,
  type ManualCameraForm,
  type OnvifForm,
  type OnvifIdentityView,
  type OnvifInspectionView,
  type OnvifProfileView,
} from "./onboarding"
import { ApiError } from "./client"

/**
 * Four traps, all of which produce a request that means the opposite of what
 * the operator intended:
 *
 * 1. **`profile_tokens: null` is "every profile"**, `[]` is "none" and can
 *    reach 422 `onvif_no_usable_profiles` (`onvif_onboarding.py:229-230`).
 *    A form that starts with nothing ticked naturally sends `[]`.
 * 2. **`confirm_existing_device_id` must be echoed exactly** as the server's own
 *    `matched_device_id`; deriving it locally yields a *different* 409 for one
 *    mistake.
 * 3. **`stream_uri_available` is the gate**, not profile count.
 * 4. **N profiles is not N cameras** — cameras are grouped by
 *    `video_source_token`.
 */

function profile(overrides: Partial<OnvifProfileView> = {}): OnvifProfileView {
  return {
    token: "p1",
    name: "主码流",
    video_source_token: "vs1",
    codec: "h264",
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

function identity(
  overrides: Partial<OnvifIdentityView> = {},
): OnvifIdentityView {
  return {
    state: "new_device",
    matched_device_id: null,
    matched_device_name: null,
    conflicting_device_ids: [],
    reason: null,
    ...overrides,
  }
}

function inspection(
  profiles: OnvifProfileView[] = [profile()],
): OnvifInspectionView {
  return {
    device: {
      manufacturer: "Vendor",
      model: "Cam-1",
      firmware_version: "1.0",
      serial_number: "SN1",
      hardware_id: null,
    },
    capabilities: ["events", "ptz"],
    profiles,
    identity: identity(),
  }
}

function onvifForm(overrides: Partial<OnvifForm> = {}): OnvifForm {
  return {
    ...emptyOnvifForm("192.168.1.64", 80),
    password: "secret",
    name: "前门",
    ...overrides,
  }
}

function manualForm(overrides: Partial<ManualCameraForm> = {}): ManualCameraForm {
  return {
    ...emptyManualCameraForm(),
    name: "前门",
    primaryUrl: "rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101",
    ...overrides,
  }
}

afterEach(() => vi.unstubAllGlobals())

function capture() {
  const seen: { method: string; url: string; body: unknown }[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({
        method: init?.method ?? "GET",
        url: String(input),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
  return seen
}

describe("endpoints", () => {
  it("uses the documented paths", async () => {
    const seen = capture()
    await startDiscovery()
    await startDiscovery(["192.168.1.10"])
    await inspectOnvif({ host: "h", password: "p" })

    expect(seen.map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST /api/v1/cameras/discovery",
      "POST /api/v1/cameras/discovery?source_address=192.168.1.10",
      "POST /api/v1/cameras/onvif/test",
    ])
  })

  it("appends each source address separately, not comma-joined", () => {
    // The parameter is `repeated`, so a joined list would be one invalid value.
    const seen = capture()
    return startDiscovery(["10.0.0.1", "10.0.0.2"]).then(() => {
      expect(seen[0].url).toBe(
        "/api/v1/cameras/discovery?source_address=10.0.0.1&source_address=10.0.0.2",
      )
    })
  })
})

describe("profile selection", () => {
  it("sends null when the operator never touched the selection", () => {
    // null means "every usable profile" — the common case.
    const body = buildOnvifImportInput(onvifForm(), identity())
    expect(body.profile_tokens).toBeNull()
  })

  it("sends the ticked list once the selection was touched", () => {
    const body = buildOnvifImportInput(
      onvifForm({ selectedProfileTokens: ["p1", "p2"], selectionTouched: true }),
      identity(),
    )
    expect(body.profile_tokens).toEqual(["p1", "p2"])
  })

  it("sends [] for a deliberately emptied selection, and blocks it in the form", () => {
    // The body still carries [] — that is the operator's explicit ask — but the
    // form refuses to submit it, because [] reaches 422 on the server.
    const form = onvifForm({ selectionTouched: true, selectedProfileTokens: [] })
    expect(buildOnvifImportInput(form, identity()).profile_tokens).toEqual([])
    expect(validateOnvifForm(form).map((e) => e.field)).toContain("profiles")
  })

  it("an untouched empty selection is not an error", () => {
    expect(validateOnvifForm(onvifForm()).map((e) => e.field)).not.toContain(
      "profiles",
    )
  })

  it("filters out profiles with no usable stream URI", () => {
    // The real gate. A profile can be present and still unusable.
    const result = importableProfiles(
      inspection([
        profile({ token: "p1" }),
        profile({ token: "p2", stream_uri_available: false }),
      ]),
    )
    expect(result.map((p) => p.token)).toEqual(["p1"])
  })

  it("handles a null inspection without throwing", () => {
    expect(importableProfiles(null)).toEqual([])
  })
})

describe("identity", () => {
  it("routes each verdict to the only action that can work", () => {
    expect(identityAction(identity({ state: "new_device" }))).toBe("import")
    expect(identityAction(identity({ state: "same_device" }))).toBe("refresh")
    expect(
      identityAction(identity({ state: "probable_match_requires_confirmation" })),
    ).toBe("confirm")
    // A conflict is unrecoverable through import.
    expect(identityAction(identity({ state: "identity_conflict" }))).toBe("blocked")
  })

  it("echoes the server's matched_device_id back, and only for the confirm state", () => {
    const confirm = identity({
      state: "probable_match_requires_confirmation",
      matched_device_id: "dev-7",
    })
    expect(confirmationIdFor(confirm)).toBe("dev-7")
    expect(
      confirmationIdFor(identity({ state: "same_device", matched_device_id: "dev-7" })),
    ).toBeNull()
  })

  it("never invents a confirmation id", () => {
    // With no matched id there is nothing to echo, and sending anything else
    // produces a different 409 for the same mistake.
    const form = onvifForm()
    const body = buildOnvifImportInput(
      form,
      identity({ state: "probable_match_requires_confirmation", matched_device_id: null }),
    )
    expect(Object.hasOwn(body, "confirm_existing_device_id")).toBe(false)
  })

  it("explains a conflict instead of offering a button that will 409", () => {
    const reason = identityBlockedReason(
      identity({
        state: "identity_conflict",
        matched_device_name: "后院",
        conflicting_device_ids: ["a", "b"],
      }),
    )
    expect(reason).toContain("后院")
    expect(identityBlockedReason(identity())).toBeNull()
  })

  it("treats an unknown verdict as blocked rather than importing anyway", () => {
    expect(
      identityAction(identity({ state: "something_new" as never })),
    ).toBe("blocked")
  })
})

describe("importPersistedAnyway", () => {
  it("recognises a 503 whose graph was already committed", () => {
    const error = new ApiError(503, "camera_runtime_queue_unavailable", "x", {
      configuration_persisted: true,
      device_id: "dev-1",
    })
    expect(importPersistedAnyway(error)).toEqual({
      persisted: true,
      deviceId: "dev-1",
    })
  })

  it("treats a plain 503 as a real failure", () => {
    expect(
      importPersistedAnyway(new ApiError(503, "camera_runtime_queue_unavailable", "x", {})),
    ).toBeNull()
    expect(importPersistedAnyway(new Error("network"))).toBeNull()
  })
})

describe("validateOnvifForm", () => {
  it("accepts a bare host and blocks a URL in the host field", () => {
    expect(validateOnvifForm(onvifForm({ host: "192.168.1.64" }))).toEqual([])
    // The field is a host, not a URL (`cameras/schemas.py:260-272`).
    for (const host of [
      "rtsp://192.168.1.64",
      "192.168.1.64/stream",
      "user@192.168.1.64",
      "192.168.1.64:554",
    ]) {
      expect(validateOnvifForm(onvifForm({ host })).map((e) => e.field)).toContain(
        "host",
      )
    }
  })

  it("requires a password and bounds the port", () => {
    expect(validateOnvifForm(onvifForm({ password: "" })).map((e) => e.field)).toContain(
      "password",
    )
    for (const port of [0, 70000, 80.5]) {
      expect(validateOnvifForm(onvifForm({ port })).map((e) => e.field)).toContain(
        "port",
      )
    }
  })

  it("bounds the name, location and storage label", () => {
    expect(validateOnvifForm(onvifForm({ name: "x".repeat(129) })).map((e) => e.field)).toContain(
      "name",
    )
    expect(
      validateOnvifForm(onvifForm({ location: "x".repeat(257) })).map((e) => e.field),
    ).toContain("location")
    expect(
      validateOnvifForm(onvifForm({ storageLabel: "x".repeat(129) })).map((e) => e.field),
    ).toContain("storageLabel")
  })
})

describe("manual RTSP form", () => {
  it("checks only scheme and host, which is all the server checks", () => {
    expect(validateManualCameraForm(manualForm())).toEqual([])
    // Syntactically fine, unreachable — the probe is what decides, not this.
    expect(
      validateManualCameraForm(manualForm({ primaryUrl: "rtsp://10.0.0.1:554/nope" })),
    ).toEqual([])
  })

  it("rejects a non-rtsp or hostless URL", () => {
    for (const url of ["http://host/stream", "rtsp://", "not a url", ""]) {
      expect(
        validateManualCameraForm(manualForm({ primaryUrl: url })).map((e) => e.field),
      ).toContain("primaryUrl")
    }
  })

  it("only validates the secondary stream when it is enabled", () => {
    expect(
      validateManualCameraForm(manualForm({ hasSecondary: false, secondaryUrl: "" })),
    ).toEqual([])
    // The name has a default, so an empty secondary URL is the only complaint.
    expect(
      validateManualCameraForm(manualForm({ hasSecondary: true, secondaryUrl: "" })),
    ).toEqual([
      {
        field: "secondaryUrl",
        message: "子码流地址必须是 rtsp:// 开头且带主机名的完整 URL",
      },
    ])
    // Blanking the name as well produces both.
    expect(
      validateManualCameraForm(
        manualForm({ hasSecondary: true, secondaryUrl: "", secondaryName: "  " }),
      ).map((e) => e.field).sort(),
    ).toEqual(["secondaryName", "secondaryUrl"])
  })

  it("omits the secondary stream entirely when disabled", () => {
    const body = buildManualCameraInput(manualForm({ hasSecondary: false }))
    expect(Object.hasOwn(body, "secondary_stream")).toBe(false)
    const withSecondary = buildManualCameraInput(
      manualForm({ hasSecondary: true, secondaryUrl: "rtsp://h/s" }),
    )
    expect(withSecondary.secondary_stream).toEqual({ name: "子码流", rtsp_url: "rtsp://h/s" })
  })
})

describe("describeProbeStream", () => {
  const track = {
    kind: "video",
    codec: "h264",
    ready: true,
    width: 1920,
    height: 1080,
    fps: 25,
    gop_seconds: 2,
    sample_rate: null,
    channels: null,
  }

  it("says a missing track was not resolved, not that it failed", () => {
    // A camera with no audio track would otherwise read as broken.
    expect(describeProbeStream({ role: "primary", name: "m", video: null, audio: null })).toContain(
      "未解析到",
    )
  })

  it("distinguishes not-ready from resolved", () => {
    expect(
      describeProbeStream({
        role: "primary",
        name: "m",
        video: { ...track, ready: false },
        audio: null,
      }),
    ).toContain("尚未就绪")
  })

  it("reports dimensions and audio presence", () => {
    expect(
      describeProbeStream({ role: "secondary", name: "m", video: track, audio: track }),
    ).toBe("子码流：h264 · 1920×1080 · 25fps · 含音频")
  })
})
