import { describe, expect, it } from "vitest"

import type { RuntimeTuning } from "../api/systemSettings"
import {
  RUNTIME_FIELDS,
  diffRuntime,
  formatByUnit,
  formatBytes,
  ntpModeForServers,
  parseServerList,
  validateRuntime,
} from "./systemSettingsSchema"

/**
 * Every range here mirrors a Pydantic bound. These are the checks that keep a
 * mis-typed limit from becoming a 422 after the operator has filled in the
 * whole page.
 */

const BASE: RuntimeTuning = {
  prebuffer_fragment_seconds: 4,
  prebuffer_buffer_seconds: 60,
  turn_credential_ttl_seconds: 300,
  playback_cache_max_bytes: 512 * 1024 * 1024,
  playback_cache_ttl_seconds: 3600,
  playback_restore_lock_ttl_seconds: 600,
  live_transcode_max_derivatives: 2,
  live_transcode_idle_ttl_seconds: 30,
  live_transcode_lease_ttl_seconds: 60,
  live_transcode_startup_timeout_seconds: 10,
  live_transcode_cpu_threads: 2,
  live_transcode_video_bitrate_kbps: 2048,
}

describe("runtime field specs", () => {
  it("covers every field of the runtime group", () => {
    // A field added to the schema without a spec here would render with no
    // validation and no unit — the form would silently accept anything.
    expect(RUNTIME_FIELDS.length).toBe(Object.keys(BASE).length)
    for (const spec of RUNTIME_FIELDS) {
      expect(BASE).toHaveProperty(spec.key)
    }
  })

  it("caps the playback cache at 1 TiB, not 1 GiB", () => {
    // `system/schemas.py:146` is `1024 * 1024 * 1024 * 1024`. A 1 GiB cap
    // would reject valid values.
    const spec = RUNTIME_FIELDS.find(
      (f) => f.key === "playback_cache_max_bytes",
    )!
    expect(spec.max).toBe(1024 * 1024 * 1024 * 1024)
  })

  it("marks the startup timeout as the only float field", () => {
    const floats = RUNTIME_FIELDS.filter((spec) => !spec.integer)
    expect(floats.map((spec) => spec.key)).toEqual([
      "live_transcode_startup_timeout_seconds",
    ])
  })
})

describe("validateRuntime", () => {
  it("accepts the current values", () => {
    expect(validateRuntime(BASE)).toEqual([])
  })

  it("rejects a value below the minimum", () => {
    const errors = validateRuntime({ prebuffer_fragment_seconds: 1 })
    expect(errors[0].field).toBe("prebuffer_fragment_seconds")
  })

  it("rejects a value above the maximum", () => {
    const errors = validateRuntime({ live_transcode_max_derivatives: 9 })
    expect(errors[0].field).toBe("live_transcode_max_derivatives")
  })

  it("rejects a fraction in an integer field", () => {
    // Pydantic types these as `int`; a float is a 422, not a rounding.
    const errors = validateRuntime({ live_transcode_cpu_threads: 2.5 })
    expect(errors[0].message).toContain("整数")
  })

  it("accepts a fraction in the one float field", () => {
    expect(
      validateRuntime({ live_transcode_startup_timeout_seconds: 10.5 }),
    ).toEqual([])
  })

  it("rejects a non-numeric value without crashing", () => {
    const errors = validateRuntime({
      playback_cache_ttl_seconds: Number.NaN,
    })
    expect(errors[0].message).toContain("数字")
  })

  it("ignores fields the form did not touch", () => {
    expect(validateRuntime({})).toEqual([])
  })

  it("reports each bad field separately", () => {
    const errors = validateRuntime({
      prebuffer_fragment_seconds: 0,
      live_transcode_cpu_threads: 99,
    })
    expect(errors).toHaveLength(2)
  })
})

describe("unit formatting", () => {
  it("scales bytes", () => {
    expect(formatBytes(512)).toBe("512 B")
    expect(formatBytes(64 * 1024 * 1024)).toBe("64 MiB")
    expect(formatBytes(64 * 1024)).toBe("64 KiB")
    expect(formatBytes(1024 ** 3)).toBe("1 GiB")
    expect(formatBytes(1024 ** 4)).toBe("1 TiB")
  })

  it("names the unit so a byte count is never read as a duration", () => {
    expect(formatByUnit(64 * 1024 * 1024, "bytes")).toBe("64 MiB")
    expect(formatByUnit(3600, "seconds")).toBe("1 小时")
    expect(formatByUnit(2048, "kbps")).toBe("2048 kbps")
    expect(formatByUnit(2, "count")).toBe("2")
  })

  it("never emits NaN", () => {
    expect(formatBytes(Number.NaN)).toBe("—")
  })
})

describe("NTP server list", () => {
  it("splits on commas and newlines and trims", () => {
    expect(parseServerList("a, b\nc , ,d")).toEqual(["a", "b", "c", "d"])
  })

  it("flips the mode with the list", () => {
    // `system/api.py:1086` rewrites the mode whenever the list is written.
    expect(ntpModeForServers(["ntp1"])).toEqual({
      managed_camera_ntp_mode: "manual",
      managed_camera_ntp_servers: ["ntp1"],
    })
    expect(ntpModeForServers([])).toEqual({
      managed_camera_ntp_mode: "dhcp",
      managed_camera_ntp_servers: [],
    })
  })
})

describe("diffRuntime", () => {
  it("sends only what changed", () => {
    const changed = diffRuntime(BASE, {
      live_transcode_cpu_threads: 4,
      live_transcode_max_derivatives: 2,
    })
    expect(changed).toEqual({ live_transcode_cpu_threads: 4 })
  })

  it("ignores fields that were not provided", () => {
    expect(diffRuntime(BASE, {})).toEqual({})
  })

  it("does not resend a value that did not move", () => {
    // Resending the NTP-mode-adjacent values is what flips the mode; a no-op
    // patch that still carries a server list would not be a no-op.
    expect(diffRuntime(BASE, { ...BASE })).toEqual({})
  })
})
