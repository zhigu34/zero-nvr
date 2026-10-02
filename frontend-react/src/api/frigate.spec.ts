import { afterEach, describe, expect, it, vi } from "vitest"

import {
  buildFrigatePut,
  FRIGATE_MAX_LOOKBACK,
  FRIGATE_MIN_LOOKBACK,
  frigateFormFromView,
  getFrigateProvider,
  isNotConfigured,
  isNotEnabled,
  putFrigateProvider,
  queueFrigateBackfill,
  testFrigateProvider,
  validateFrigateForm,
  type FrigateForm,
  type FrigateProviderView,
} from "./frigate"
import { ApiError } from "./client"

/**
 * Two contracts are easy to get wrong and both fail quietly:
 *
 * 1. **`GET` 404s on first run** rather than returning `configured: false`, so
 *    an unconfigured integration is data, not an error. The `configured` field
 *    in the response schema is never False and must not be branched on.
 * 2. **The PUT replaces the whole object.** A body built from a diff of changed
 *    fields silently wipes everything the form did not carry.
 */

function view(overrides: Partial<FrigateProviderView> = {}): FrigateProviderView {
  return {
    configured: true,
    enabled: true,
    mode: "external",
    instance_id: "f-1",
    base_url: "http://frigate.local:5000",
    camera_map: [{ frigate_camera: "front", camera_id: "cam-1" }],
    mqtt_enabled: false,
    mqtt_host: null,
    mqtt_port: 1883,
    mqtt_topic_prefix: "frigate",
    mqtt_tls: false,
    credentials_configured: true,
    ...overrides,
  }
}

function form(overrides: Partial<FrigateForm> = {}): FrigateForm {
  return {
    enabled: true,
    mode: "external",
    baseUrl: "http://frigate.local:5000",
    cameraMap: [],
    mqttEnabled: false,
    mqttHost: "",
    mqttPort: 1883,
    mqttTopicPrefix: "frigate",
    mqttTls: false,
    credentialsAction: "keep",
    credentials: {},
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
  it("uses the documented paths and methods", async () => {
    const seen = capture()

    await getFrigateProvider()
    await putFrigateProvider(buildFrigatePut(form()))
    await testFrigateProvider()
    await queueFrigateBackfill({ lookback_seconds: 600 })

    expect(seen.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/integrations/frigate",
      "PUT /api/v1/integrations/frigate",
      "POST /api/v1/integrations/frigate/test",
      "POST /api/v1/integrations/frigate/backfill",
    ])
  })
})

describe("first-run detection", () => {
  it("treats frigate_not_configured as data, not a failure", () => {
    expect(isNotConfigured(new ApiError(404, "frigate_not_configured", "x"))).toBe(
      true,
    )
    // A 409 with a different meaning must not be conflated with the 404.
    expect(isNotConfigured(new ApiError(409, "frigate_not_enabled", "x"))).toBe(
      false,
    )
    expect(isNotConfigured(new Error("network down"))).toBe(false)
  })

  it("separates not-enabled from not-configured", () => {
    expect(isNotEnabled(new ApiError(409, "frigate_not_enabled", "x"))).toBe(true)
    expect(isNotEnabled(new ApiError(404, "frigate_not_configured", "x"))).toBe(
      false,
    )
  })
})

describe("buildFrigatePut", () => {
  it("always sends every field, because the endpoint replaces the object", () => {
    const body = buildFrigatePut(form({ enabled: false }))
    expect(Object.keys(body).sort()).toEqual(
      [
        "base_url",
        "camera_map",
        "credentials_action",
        "enabled",
        "mode",
        "mqtt_enabled",
        "mqtt_host",
        "mqtt_port",
        "mqtt_topic_prefix",
        "mqtt_tls",
      ].sort(),
    )
    expect(body.enabled).toBe(false)
  })

  it("nulls mqtt_host when MQTT is off, rather than sending a stale host", () => {
    // The field is a plain `str | None`; a leftover host with mqtt_enabled
    // false is a state the form never meant to express.
    const body = buildFrigatePut(
      form({ mqttEnabled: false, mqttHost: "mqtt.local" }),
    )
    expect(body.mqtt_host).toBeNull()
    expect(buildFrigatePut(form({ mqttEnabled: true, mqttHost: " mqtt.local " })))
      .toMatchObject({ mqtt_host: "mqtt.local" })
  })

  it("sends no credentials on keep", () => {
    const body = buildFrigatePut(form({ credentialsAction: "keep" }))
    expect(body.credentials_action).toBe("keep")
    expect(Object.hasOwn(body, "credentials")).toBe(false)
  })

  it("drops blank fields on replace, because exclude_none leaves an empty object", () => {
    // The server rejects a replacement whose every value is null
    // (`api.py:387-399`); empty strings would survive that check as values.
    const body = buildFrigatePut(
      form({
        credentialsAction: "replace",
        credentials: { http_bearer_token: "tok", http_password: "" },
      }),
    )
    expect(body.credentials).toEqual({ http_bearer_token: "tok" })
  })

  it("sends null on clear", () => {
    expect(buildFrigatePut(form({ credentialsAction: "clear" }))).toMatchObject({
      credentials_action: "clear",
      credentials: null,
    })
  })
})

describe("validateFrigateForm", () => {
  it("accepts a minimal external configuration", () => {
    expect(validateFrigateForm(form())).toEqual([])
  })

  it("requires a base URL", () => {
    expect(validateFrigateForm(form({ baseUrl: "  " }))[0].field).toBe("baseUrl")
  })

  it("names the duplicated Frigate camera key", () => {
    // The server's `frigate_camera_mapping_duplicate` does not say which key.
    const errors = validateFrigateForm(
      form({
        cameraMap: [
          { frigate_camera: "front", camera_id: "cam-1" },
          { frigate_camera: "front", camera_id: "cam-2" },
        ],
      }),
    )
    expect(errors[0].field).toBe("cameraMap")
    expect(errors[0].message).toContain("front")
  })

  it("rejects a mapping with no camera chosen on this system", () => {
    // `camera_id` is a required UUID and the service rejects an unknown one
    // (`frigate.py:99-128`) — checking only the Frigate-side name leaves a
    // guaranteed 422 for the server to find.
    const errors = validateFrigateForm(
      form({ cameraMap: [{ frigate_camera: "front", camera_id: "" }] }),
    )
    expect(errors.map((e) => e.field)).toContain("cameraMap")
    expect(errors[0].message).toContain("1")
  })

  it("only demands MQTT details when MQTT is on", () => {
    expect(
      validateFrigateForm(form({ mqttEnabled: false, mqttHost: "", mqttPort: 0 })),
    ).toEqual([])
    const errors = validateFrigateForm(form({ mqttEnabled: true, mqttHost: "" }))
    expect(errors.map((e) => e.field)).toContain("mqttHost")
  })

  it("bounds the MQTT port the way the schema does", () => {
    for (const port of [0, 70000, 1.5]) {
      expect(
        validateFrigateForm(
          form({ mqttEnabled: true, mqttHost: "m", mqttPort: port }),
        ).map((e) => e.field),
      ).toContain("mqttPort")
    }
    expect(
      validateFrigateForm(
        form({ mqttEnabled: true, mqttHost: "m", mqttPort: 1883 }),
      ),
    ).toEqual([])
  })

  it("rejects a replacement with no values, matching the server's own check", () => {
    const errors = validateFrigateForm(
      form({ credentialsAction: "replace", credentials: { http_username: "" } }),
    )
    expect(errors.map((e) => e.field)).toContain("credentials")
  })
})

describe("backfill bounds", () => {
  it("matches the schema's range", () => {
    expect(FRIGATE_MIN_LOOKBACK).toBe(60)
    expect(FRIGATE_MAX_LOOKBACK).toBe(86400)
  })
})

describe("frigateFormFromView", () => {
  it("seeds every field from a saved provider", () => {
    const seeded = frigateFormFromView(
      view({ mqtt_enabled: true, mqtt_host: "mqtt.local", mqtt_tls: true }),
    )
    expect(seeded.baseUrl).toBe("http://frigate.local:5000")
    expect(seeded.mqttHost).toBe("mqtt.local")
    expect(seeded.mqttTls).toBe(true)
    expect(seeded.cameraMap).toEqual([
      { frigate_camera: "front", camera_id: "cam-1" },
    ])
  })

  it("copies the camera map so editing the form cannot mutate the cache", () => {
    const saved = view()
    const seeded = frigateFormFromView(saved)
    seeded.cameraMap[0].frigate_camera = "changed"
    expect(saved.camera_map[0].frigate_camera).toBe("front")
  })

  it("defaults credentials to keep, because secrets are unreadable", () => {
    expect(frigateFormFromView(view()).credentialsAction).toBe("keep")
  })

  it("produces a valid empty form on first run", () => {
    const seeded = frigateFormFromView(null)
    expect(seeded.enabled).toBe(false)
    expect(seeded.mode).toBe("external")
    expect(seeded.mqttPort).toBe(1883)
    expect(validateFrigateForm(seeded).map((e) => e.field)).toEqual(["baseUrl"])
  })
})
