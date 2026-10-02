/**
 * Frigate integration contract. Mirrors
 * `backend/app/modules/system/schemas.py:10-80` and `system/api.py:305-594`.
 *
 * ## "Not configured" is a 404, and it is the normal first-run state
 *
 * `GET /system/integrations/frigate` raises `frigate_not_configured` (404) when
 * no row exists (`api.py:316-324`). The response schema does carry a
 * `configured: bool = True` field (`schemas.py:51`) — but that field is never
 * False, because the 404 happens first. Reading it as a flag would mean the UI
 * can never tell "unconfigured" from "configured", and an operator who has
 * never set up Frigate would see an error banner instead of a form.
 *
 * So this module treats a 404 with code `frigate_not_configured` as data, and
 * `isNotConfigured` is the only thing that decides between the empty state and
 * the failure surface.
 *
 * ## The PUT is a whole-object replace
 *
 * `FrigateProviderPut` has no optional fields that mean "leave this alone":
 * `enabled`, `mode`, `base_url`, `mqtt_*` and `camera_map` are all replaced
 * wholesale (`api.py:429-443`). A form that only sends what it changed wipes
 * everything else, so the body is built from the full form state every time —
 * see `buildFrigatePut`.
 *
 * ## Credentials: the same three-verb protocol as notifications
 *
 * `credentials_action: keep | replace | clear`, and credential values are
 * accepted **only** with `replace`:
 *
 * - `replace` without values → 400 `frigate_credentials_update_invalid`
 * - values without `replace` → 400, same code (`api.py:356-381`)
 * - `replace` with an object whose every field is null → 400, same code
 *   (`exclude_none=True` leaves it empty, `api.py:387-399`)
 *
 * Unlike notifications this is a five-field set, and a `replace` replaces the
 * whole set — there is no per-field verb. So the form shows all five together
 * and explains that replacing means re-entering every one of them.
 */
import { api, ApiError } from "./client"

/* -------------------------------------------------------------------------- */
/* Wire shapes                                                                */
/* -------------------------------------------------------------------------- */

export type FrigateMode = "managed" | "external"

export type FrigateCameraMapping = {
  frigate_camera: string
  camera_id: string
}

export type FrigateCredentialsInput = {
  http_bearer_token?: string | null
  http_username?: string | null
  http_password?: string | null
  mqtt_username?: string | null
  mqtt_password?: string | null
}

export type FrigateProviderView = {
  /**
   * Always true — see the module note. Do not branch on it; use
   * `isNotConfigured(error)`.
   */
  configured: boolean
  enabled: boolean
  mode: FrigateMode
  instance_id: string
  base_url: string
  camera_map: FrigateCameraMapping[]
  mqtt_enabled: boolean
  mqtt_host: string | null
  mqtt_port: number
  mqtt_topic_prefix: string
  mqtt_tls: boolean
  /** The read model's only word about credentials. They are never returned. */
  credentials_configured: boolean
}

export type FrigateProviderPut = {
  enabled: boolean
  mode: FrigateMode
  base_url: string
  camera_map: FrigateCameraMapping[]
  mqtt_enabled: boolean
  mqtt_host: string | null
  mqtt_port: number
  mqtt_topic_prefix: string
  mqtt_tls: boolean
  credentials_action: SecretAction
  credentials?: FrigateCredentialsInput | null
}

export type FrigateProviderTest = { ok: boolean; version: string | null }

export type FrigateBackfillRequest = {
  /** 60 … 86400, default 600 (`schemas.py:71-76`). */
  lookback_seconds: number
}

export type FrigateBackfillQueued = {
  queued: boolean
  lookback_seconds: number
}

export type SecretAction = "keep" | "replace" | "clear"

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

/** `integration.manage`. 404 `frigate_not_configured` on first run. */
export function getFrigateProvider(signal?: AbortSignal) {
  return api.get<FrigateProviderView>("/integrations/frigate", signal)
}

export function putFrigateProvider(body: FrigateProviderPut) {
  return api.put<FrigateProviderView>("/integrations/frigate", body)
}

/**
 * A real outbound HTTP call to the configured Frigate, with a 10s timeout
 * (`api.py:556`). It is a POST with an external side effect, so it is only ever
 * an explicit click — never a probe on mount.
 */
export function testFrigateProvider() {
  return api.post<FrigateProviderTest>("/integrations/frigate/test")
}

/** 409 `frigate_not_enabled` when the integration is off (`api.py:587-592`). */
export function queueFrigateBackfill(body: FrigateBackfillRequest) {
  return api.post<FrigateBackfillQueued>("/integrations/frigate/backfill", body)
}

/* -------------------------------------------------------------------------- */
/* First-run detection                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Whether an error means "Frigate has never been set up" rather than
 * "something broke".
 *
 * Matched on the code, not the status: `frigate_not_enabled` is also a 409 and
 * also entirely normal, and the two need different messages.
 */
export function isNotConfigured(error: unknown): boolean {
  return error instanceof ApiError && error.code === "frigate_not_configured"
}

/** 409 — configured but switched off, so backfill has nothing to talk to. */
export function isNotEnabled(error: unknown): boolean {
  return error instanceof ApiError && error.code === "frigate_not_enabled"
}

/* -------------------------------------------------------------------------- */
/* Build body                                                                 */
/* -------------------------------------------------------------------------- */

export type FrigateForm = {
  enabled: boolean
  mode: FrigateMode
  baseUrl: string
  cameraMap: FrigateCameraMapping[]
  mqttEnabled: boolean
  mqttHost: string
  mqttPort: number
  mqttTopicPrefix: string
  mqttTls: boolean
  credentialsAction: SecretAction
  credentials: FrigateCredentialsInput
}

export type FrigateFormField =
  | "baseUrl"
  | "cameraMap"
  | "mqttHost"
  | "mqttPort"
  | "mqttTopicPrefix"
  | "credentials"

export type FrigateFormError = { field: FrigateFormField; message: string }

export const FRIGATE_MIN_PORT = 1
export const FRIGATE_MAX_PORT = 65535
export const FRIGATE_MIN_LOOKBACK = 60
export const FRIGATE_MAX_LOOKBACK = 86400

/**
 * Validate the form, in the order the server would reject it.
 *
 * Two rules here exist only because the server would otherwise answer with a
 * code that does not name the field: the duplicate camera key
 * (`frigate_camera_mapping_duplicate`, `api.py:347-354`) and the empty
 * credential replacement (`frigate_credentials_update_invalid`).
 */
export function validateFrigateForm(form: FrigateForm): FrigateFormError[] {
  const errors: FrigateFormError[] = []

  if (form.baseUrl.trim() === "") {
    errors.push({ field: "baseUrl", message: "请填写 Frigate 地址" })
  }

  const keys = form.cameraMap.map((m) => m.frigate_camera.trim())
  if (keys.some((k) => k === "")) {
    errors.push({ field: "cameraMap", message: "每条映射都需要 Frigate 侧的机位名" })
  }
  const duplicates = keys.filter((k, i) => k !== "" && keys.indexOf(k) !== i)
  if (duplicates.length > 0) {
    errors.push({
      field: "cameraMap",
      message: `Frigate 侧机位名重复：${[...new Set(duplicates)].join("、")}`,
    })
  }
  // `camera_id` is a required UUID (`schemas.py:11-15`) and the service
  // rejects one that names no camera here (`frigate.py:99-128`). Checking only
  // the Frigate-side name leaves a guaranteed 422 for the server to find.
  const unmapped = form.cameraMap.filter((m) => !m.camera_id).length
  if (unmapped > 0) {
    errors.push({
      field: "cameraMap",
      message: `还有 ${unmapped} 条映射没有选择本系统的摄像机`,
    })
  }

  if (form.mqttEnabled) {
    if (form.mqttHost.trim() === "") {
      errors.push({ field: "mqttHost", message: "启用 MQTT 时必须填写主机" })
    }
    if (
      !Number.isInteger(form.mqttPort) ||
      form.mqttPort < FRIGATE_MIN_PORT ||
      form.mqttPort > FRIGATE_MAX_PORT
    ) {
      errors.push({
        field: "mqttPort",
        message: `端口需在 ${FRIGATE_MIN_PORT}–${FRIGATE_MAX_PORT} 之间`,
      })
    }
    if (form.mqttTopicPrefix.trim() === "") {
      errors.push({ field: "mqttTopicPrefix", message: "主题前缀不能为空" })
    }
  }

  if (form.credentialsAction === "replace") {
    // `exclude_none=True` on the server means an object of empty strings is
    // still "no values", so blank inputs must not count as supplied.
    const supplied = Object.entries(form.credentials).filter(
      ([, value]) => typeof value === "string" && value.length > 0,
    )
    if (supplied.length === 0) {
      errors.push({
        field: "credentials",
        message: "选择「替换」时至少要填一项凭据，否则服务端会拒绝",
      })
    }
  }

  return errors
}

/**
 * Build the PUT body from the whole form, never from a diff.
 *
 * The endpoint replaces the object (`api.py:429-443`), so anything the form
 * does not carry here is gone. Credentials are the one part that is
 * conditional, and only because they have an explicit verb.
 */
export function buildFrigatePut(form: FrigateForm): FrigateProviderPut {
  const body: FrigateProviderPut = {
    enabled: form.enabled,
    mode: form.mode,
    base_url: form.baseUrl.trim(),
    camera_map: form.cameraMap.map((m) => ({
      frigate_camera: m.frigate_camera.trim(),
      camera_id: m.camera_id,
    })),
    mqtt_enabled: form.mqttEnabled,
    mqtt_host: form.mqttEnabled ? form.mqttHost.trim() : null,
    mqtt_port: form.mqttPort,
    mqtt_topic_prefix: form.mqttTopicPrefix.trim(),
    mqtt_tls: form.mqttTls,
    credentials_action: form.credentialsAction,
  }

  if (form.credentialsAction === "replace") {
    const credentials: FrigateCredentialsInput = {}
    for (const [key, value] of Object.entries(form.credentials)) {
      if (typeof value === "string" && value.length > 0) {
        credentials[key as keyof FrigateCredentialsInput] = value
      }
    }
    body.credentials = credentials
  } else if (form.credentialsAction === "clear") {
    body.credentials = null
  }

  return body
}

/** Seed the form from a saved provider, for the edit path. */
export function frigateFormFromView(
  view: FrigateProviderView | null,
): FrigateForm {
  return {
    enabled: view?.enabled ?? false,
    mode: view?.mode ?? "external",
    baseUrl: view?.base_url ?? "",
    cameraMap: view?.camera_map.map((m) => ({ ...m })) ?? [],
    mqttEnabled: view?.mqtt_enabled ?? false,
    mqttHost: view?.mqtt_host ?? "",
    mqttPort: view?.mqtt_port ?? 1883,
    mqttTopicPrefix: view?.mqtt_topic_prefix ?? "frigate",
    mqttTls: view?.mqtt_tls ?? false,
    // Secrets are unreadable, so "do not touch" is the only honest default.
    credentialsAction: "keep",
    credentials: {},
  }
}

export const FRIGATE_MODE_LABEL: Record<FrigateMode, string> = {
  managed: "托管（本系统负责部署 Frigate）",
  external: "外部（自行运行的 Frigate）",
}
