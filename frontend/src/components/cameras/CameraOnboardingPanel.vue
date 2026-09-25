<script setup lang="ts">
import { computed, ref } from "vue"
import { useI18n } from "vue-i18n"

import {
  CsvParseError,
  parseCsvRecords,
  type CsvRecord
} from "../../cameraBatchCsv"
import {
  createManualCamera,
  discoverOnvif,
  importOnvif,
  inspectOnvif,
  listCameraGroups,
  testManualCamera,
  updateCamera,
  updateCameraGroup,
  type CameraGroup,
  type CameraProbeResult,
  type DiscoveryCandidate,
  type DiscoverySession,
  type ManualCameraInput,
  type OnvifInspection
} from "../../api/cameras"
import { errorMessage } from "../../api/client"
import {
  putRecordingPolicy,
  type RecordingPolicyPut
} from "../../api/recordings"
import {
  listStorageTargets,
  type StorageTarget
} from "../../api/storage"
import { useAuthStore } from "../../stores/auth"

const emit = defineEmits<{
  created: []
  changed: []
  close: []
}>()

const auth = useAuthStore()
const { t, te } = useI18n({ useScope: "global" })

type Mode = "onvif" | "rtsp" | "batch_file"
type WorkingAction =
  | "discover"
  | "inspect"
  | "import"
  | "batch"
  | "file-batch"
  | "test"
  | "create"
  | null

const mode = ref<Mode>("onvif")
const working = ref<WorkingAction>(null)
const requestError = ref<string | null>(null)
const successMessage = ref<string | null>(null)

const manualName = ref("")
const manualLocation = ref("")
const manualStorageLabel = ref("")
const primaryName = ref(t("cameras.onboarding.mainStream"))
const primaryUrl = ref("")
const secondaryEnabled = ref(false)
const secondaryName = ref(t("cameras.onboarding.subStream"))
const secondaryUrl = ref("")
const manualProbe = ref<CameraProbeResult | null>(null)
const manualProbeFingerprint = ref<string | null>(null)

const discovery = ref<DiscoverySession | null>(null)
const selectedCandidateId = ref<string | null>(null)
const onvifHost = ref("")
const onvifPort = ref(80)
const onvifUsername = ref("")
const onvifPassword = ref("")
const onvifName = ref("")
const onvifLocation = ref("")
const onvifStorageLabel = ref("")
const inspection = ref<OnvifInspection | null>(null)
const inspectionFingerprint = ref<string | null>(null)
const selectedProfiles = ref<string[]>([])
const confirmExistingIdentity = ref(false)

type BatchResultState =
  | "pending"
  | "running"
  | "success"
  | "partial"
  | "review"
  | "failed"

interface BatchResult {
  candidate_id: string
  label: string
  state: BatchResultState
  message: string
  camera_ids: string[]
}

interface BatchCredentialOverride {
  username: string
  password: string
}

const batchSelectedIds = ref<string[]>([])
const batchUsername = ref("")
const batchPassword = ref("")
const batchNameTemplate = ref("{name}")
const batchGroupId = ref("")
const batchRecordingMode = ref<"continuous" | "events" | "off">(
  "continuous"
)
const batchStorageTargetId = ref("")
const batchTimeSyncMode = ref<
  "monitor" | "manage_ntp" | "ignore"
>("monitor")
const batchGroups = ref<CameraGroup[]>([])
const batchStorageTargets = ref<StorageTarget[]>([])
const batchOverrides = ref<Record<string, BatchCredentialOverride>>({})
const batchResults = ref<BatchResult[]>([])

type FileImportKind = "onvif" | "rtsp"

interface FileImportRow {
  line: number
  kind: FileImportKind | null
  name: string
  host: string
  onvif_port: number
  rtsp_port: number
  username: string
  password: string
  main_path: string
  sub_path: string
  main_url: string
  sub_url: string
  location: string
  storage_label: string
  errors: string[]
}

interface FileBatchResult {
  line: number
  label: string
  state: BatchResultState
  message: string
  camera_ids: string[]
}

const fileBatchName = ref("")
const fileBatchRows = ref<FileImportRow[]>([])
const fileBatchResults = ref<FileBatchResult[]>([])
const fileBatchCompleted = ref(false)

const identity = computed(() => inspection.value?.identity ?? null)
const identityRequiresConfirmation = computed(
  () => identity.value?.state === "probable_match_requires_confirmation"
)
const identityConflict = computed(
  () => identity.value?.state === "identity_conflict"
)
const importActionLabel = computed(() => {
  if (working.value === "import") return t("cameras.onboarding.importing")
  if (identity.value?.state === "same_device") return t("cameras.onboarding.refreshExisting")
  if (identityRequiresConfirmation.value) return t("cameras.onboarding.confirmRefresh")
  return t("cameras.onboarding.importDevice")
})

const batchCandidates = computed(() => {
  const selected = new Set(batchSelectedIds.value)
  return (discovery.value?.candidates ?? []).filter(
    (candidate) => selected.has(candidate.id)
  )
})

const canBatchImport = computed(
  () =>
    batchCandidates.value.length > 0 &&
    batchCandidates.value.every((candidate) => Boolean(candidate.host)) &&
    working.value === null
)

const batchResultMap = computed(
  () =>
    new Map(
      batchResults.value.map((result) => [
        result.candidate_id,
        result
      ])
    )
)

const fileBatchReadyCount = computed(
  () => fileBatchRows.value.filter((row) => !row.errors.length).length
)
const fileBatchInvalidCount = computed(
  () => fileBatchRows.value.length - fileBatchReadyCount.value
)
const canFileBatchImport = computed(
  () =>
    fileBatchReadyCount.value > 0 &&
    !fileBatchCompleted.value &&
    working.value === null
)

const canCreateManual = computed(
  () =>
    manualProbe.value !== null &&
    manualProbeFingerprint.value === JSON.stringify(manualBody()) &&
    working.value === null
)

const canImport = computed(
  () =>
    inspection.value !== null &&
    inspectionFingerprint.value === JSON.stringify(onvifCredentials()) &&
    selectedProfiles.value.length > 0 &&
    !identityConflict.value &&
    (!identityRequiresConfirmation.value || confirmExistingIdentity.value) &&
    working.value === null
)

function normalizeOptional(value: string): string | null {
  const normalized = value.trim()
  return normalized || null
}

function validRtspUrl(value: string): boolean {
  try {
    const parsed = new URL(value)
    return parsed.protocol === "rtsp:" && Boolean(parsed.hostname)
  } catch {
    return false
  }
}

function csvPort(
  rawValue: string,
  fallback: number,
  errors: string[],
  field: "onvif_port" | "rtsp_port"
): number {
  if (!rawValue) return fallback

  const parsed = Number(rawValue)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    errors.push(
      t("cameras.onboarding.csvInvalidNamedPort", { field })
    )
    return fallback
  }
  return parsed
}

function rtspHost(host: string): string {
  if (host.includes(":") && !host.startsWith("[")) {
    return `[${host}]`
  }
  return host
}

function buildRtspUrl(
  row: Pick<
    FileImportRow,
    | "host"
    | "rtsp_port"
    | "username"
    | "password"
  >,
  path: string,
  overrideUrl: string
): string {
  if (overrideUrl) return overrideUrl
  if (!row.host || !path) return ""

  const normalizedPath = path.startsWith("/") ? path : `/${path}`
  const username = encodeURIComponent(row.username)
  const password = encodeURIComponent(row.password)
  const auth =
    row.username || row.password
      ? `${username}${row.password ? `:${password}` : ""}@`
      : ""
  return `rtsp://${auth}${rtspHost(row.host)}:${row.rtsp_port}${normalizedPath}`
}

function csvParseErrorMessage(error: CsvParseError): string {
  const key = `cameras.onboarding.${error.code}`
  if (te(key)) {
    return t(key, { line: error.line ?? "?" })
  }
  return error.message
}

function fileImportRow(record: CsvRecord): FileImportRow {
  const value = (key: string) => (record.values[key] ?? "").trim()
  const rawKind = value("type").toLowerCase()
  const errors: string[] = []
  let kind: FileImportKind | null = null

  if (!rawKind) {
    errors.push(t("cameras.onboarding.csvMissingType"))
  } else if (rawKind === "onvif" || rawKind === "rtsp") {
    kind = rawKind
  } else {
    errors.push(
      t("cameras.onboarding.csvUnsupportedType", { type: rawKind })
    )
  }

  const host = value("host")
  const name = value("name")
  const username = value("username")
  const password = record.values.password ?? ""
  const onvifPort = csvPort(
    value("onvif_port") || (kind === "onvif" ? value("port") : ""),
    80,
    errors,
    "onvif_port"
  )
  const rtspPort = csvPort(
    value("rtsp_port"),
    554,
    errors,
    "rtsp_port"
  )
  const mainPath = value("main_path")
  const subPath = value("sub_path")
  const mainUrl = value("main_url") || value("rtsp_url")
  const subUrl = value("sub_url") || value("secondary_rtsp_url")

  if (kind === "onvif" && !host) {
    errors.push(t("cameras.onboarding.csvMissingHost"))
  }

  if (kind === "rtsp") {
    if (!name) {
      errors.push(t("cameras.onboarding.csvMissingName"))
    }
    if (!mainUrl && !host) {
      errors.push(t("cameras.onboarding.csvMissingRtspHost"))
    }
    if (!mainUrl && !mainPath) {
      errors.push(t("cameras.onboarding.csvMissingMainPath"))
    }
    if (mainPath.includes("://") || subPath.includes("://")) {
      errors.push(t("cameras.onboarding.csvPathNotUrl"))
    }
    if (mainUrl && !validRtspUrl(mainUrl)) {
      errors.push(t("cameras.onboarding.csvInvalidMainUrl"))
    }
    if (subUrl && !validRtspUrl(subUrl)) {
      errors.push(t("cameras.onboarding.csvInvalidSubUrl"))
    }
    if (!subUrl && subPath && !host) {
      errors.push(t("cameras.onboarding.csvSubPathNeedsHost"))
    }
  }

  const row: FileImportRow = {
    line: record.line,
    kind,
    name,
    host,
    onvif_port: onvifPort,
    rtsp_port: rtspPort,
    username,
    password,
    main_path: mainPath,
    sub_path: subPath,
    main_url: mainUrl,
    sub_url: subUrl,
    location: value("location"),
    storage_label: value("storage_label"),
    errors
  }

  if (kind === "rtsp" && !errors.length) {
    const primaryUrl = buildRtspUrl(row, row.main_path, row.main_url)
    const secondaryUrl = buildRtspUrl(row, row.sub_path, row.sub_url)
    if (!primaryUrl || !validRtspUrl(primaryUrl)) {
      errors.push(t("cameras.onboarding.csvInvalidResolvedMainUrl"))
    }
    if (secondaryUrl && !validRtspUrl(secondaryUrl)) {
      errors.push(t("cameras.onboarding.csvInvalidResolvedSubUrl"))
    }
  }

  return row
}

function manualBody(): ManualCameraInput {
  return {
    mode: "manual_rtsp",
    name: manualName.value.trim(),
    location: normalizeOptional(manualLocation.value),
    storage_label: normalizeOptional(manualStorageLabel.value),
    primary_stream: {
      name: primaryName.value.trim(),
      rtsp_url: primaryUrl.value.trim()
    },
    secondary_stream: secondaryEnabled.value
      ? {
          name: secondaryName.value.trim(),
          rtsp_url: secondaryUrl.value.trim()
        }
      : null
  }
}

function clearMessages(): void {
  requestError.value = null
  successMessage.value = null
}

async function handleBatchFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ""
  if (!file) return

  clearMessages()
  fileBatchResults.value = []
  fileBatchCompleted.value = false
  fileBatchName.value = file.name

  try {
    const parsed = parseCsvRecords(await file.text())
    if (!parsed.headers.includes("type")) {
      requestError.value = t("cameras.onboarding.csvMissingTypeHeader")
      fileBatchRows.value = []
      return
    }
    fileBatchRows.value = parsed.rows.map(fileImportRow)
    if (!fileBatchRows.value.length) {
      requestError.value = t("cameras.onboarding.csvNoDataRows")
    }
  } catch (caught) {
    fileBatchRows.value = []
    requestError.value =
      caught instanceof CsvParseError
        ? csvParseErrorMessage(caught)
        : errorMessage(caught)
  }
}

function downloadBatchTemplate(): void {
  const csv = [
    "type,name,host,onvif_port,rtsp_port,username,password,main_path,sub_path,main_url,sub_url,location,storage_label,remark",
    [
      "onvif",
      "Front Door",
      "192.168.1.50",
      "80",
      "",
      "admin",
      "password",
      "",
      "",
      "",
      "",
      "Entrance",
      "front",
      t("cameras.onboarding.csvExampleRemark")
    ].join(","),
    [
      "rtsp",
      "Garage",
      "192.168.1.60",
      "",
      "554",
      "admin",
      "password",
      "/Streaming/Channels/101",
      "/Streaming/Channels/102",
      "",
      "",
      "Garage",
      "garage",
      t("cameras.onboarding.csvExampleRemark")
    ].join(",")
  ].join("\r\n")
  const url = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" })
  )
  const link = document.createElement("a")
  link.href = url
  link.download = "zero-nvr-camera-import.csv"
  link.click()
  URL.revokeObjectURL(url)
}

async function testRtsp(): Promise<void> {
  clearMessages()
  manualProbe.value = null
  manualProbeFingerprint.value = null
  working.value = "test"
  try {
    const body = manualBody()
    manualProbe.value = await testManualCamera(body)
    manualProbeFingerprint.value = JSON.stringify(body)
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

async function createRtsp(): Promise<void> {
  clearMessages()
  working.value = "create"
  try {
    await createManualCamera(manualBody())
    successMessage.value = t("cameras.onboarding.manualCreated")
    primaryUrl.value = ""
    secondaryUrl.value = ""
    manualProbe.value = null
    manualProbeFingerprint.value = null
    emit("created")
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

async function loadBatchDefaults(): Promise<void> {
  const groupsPromise = listCameraGroups()
  const targetsPromise = auth.hasPermission("storage.manage")
    ? listStorageTargets()
    : Promise.resolve([] as StorageTarget[])

  const [groupResult, targetResult] = await Promise.allSettled([
    groupsPromise,
    targetsPromise
  ])

  if (groupResult.status === "fulfilled") {
    batchGroups.value = groupResult.value
  }
  if (targetResult.status === "fulfilled") {
    batchStorageTargets.value = targetResult.value.filter(
      (item) =>
        item.type === "local" &&
        item.role === "recording" &&
        item.enabled
    )
    if (
      !batchStorageTargetId.value &&
      batchStorageTargets.value.length
    ) {
      batchStorageTargetId.value =
        batchStorageTargets.value[0]?.id ?? ""
    }
  }
}

function batchCredential(
  candidateId: string
): BatchCredentialOverride {
  const existing = batchOverrides.value[candidateId]
  if (existing) return existing

  const created: BatchCredentialOverride = {
    username: "",
    password: ""
  }
  batchOverrides.value[candidateId] = created
  return created
}

function initializeBatchCandidates(
  candidates: DiscoveryCandidate[]
): void {
  batchSelectedIds.value = []
  batchResults.value = []
  batchOverrides.value = Object.fromEntries(
    candidates.map((candidate) => [
      candidate.id,
      {
        username: "",
        password: ""
      }
    ])
  )
}

async function runDiscovery(): Promise<void> {
  clearMessages()
  discovery.value = null
  working.value = "discover"
  try {
    const result = await discoverOnvif()
    discovery.value = result
    initializeBatchCandidates(result.candidates)
    await loadBatchDefaults()
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

function useCandidate(candidate: DiscoveryCandidate): void {
  if (!candidate.host) return

  selectedCandidateId.value = candidate.id
  onvifHost.value = candidate.host
  onvifPort.value = candidate.port ?? 80
  inspection.value = null
  inspectionFingerprint.value = null
  selectedProfiles.value = []
  confirmExistingIdentity.value = false
}

function onvifCredentials() {
  return {
    host: onvifHost.value.trim(),
    port: Number(onvifPort.value),
    username: onvifUsername.value.trim(),
    password: onvifPassword.value
  }
}

async function inspectDevice(): Promise<void> {
  clearMessages()
  inspection.value = null
  inspectionFingerprint.value = null
  selectedProfiles.value = []
  confirmExistingIdentity.value = false
  working.value = "inspect"

  try {
    const credentials = onvifCredentials()
    const result = await inspectOnvif(credentials)
    inspection.value = result
    inspectionFingerprint.value = JSON.stringify(credentials)
    selectedProfiles.value = result.profiles
      .filter((profile) => profile.stream_uri_available)
      .map((profile) => profile.token)
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

async function importDevice(): Promise<void> {
  if (!inspection.value || selectedProfiles.value.length === 0) return

  clearMessages()
  working.value = "import"
  try {
    const imported = await importOnvif({
      ...onvifCredentials(),
      name: normalizeOptional(onvifName.value),
      location: normalizeOptional(onvifLocation.value),
      storage_label: normalizeOptional(onvifStorageLabel.value),
      profile_tokens: [...selectedProfiles.value],
      discovery_candidate_id: selectedCandidateId.value,
      confirm_existing_device_id:
        identityRequiresConfirmation.value && confirmExistingIdentity.value
          ? identity.value?.matched_device_id ?? null
          : null
    })
    successMessage.value =
      imported.reconfigured
        ? t("cameras.onboarding.onvifRefreshed")
        : t("cameras.onboarding.onvifImported")
    onvifPassword.value = ""
    emit("created")
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

function profileSummary(profile: OnvifInspection["profiles"][number]): string {
  const parts = [
    profile.codec,
    profile.width && profile.height
      ? `${profile.width}×${profile.height}`
      : null,
    profile.fps ? `${profile.fps} fps` : null
  ]
  return parts.filter(Boolean).join(" · ") || t("cameras.onboarding.profileUnavailable")
}

function candidateName(candidate: DiscoveryCandidate): string {
  const discoveredName = candidate.display_info.name
  if (
    typeof discoveredName === "string" &&
    discoveredName.trim()
  ) {
    return discoveredName.trim()
  }
  return candidate.host || t("cameras.onboarding.onvifDevice")
}

function batchDeviceName(
  candidate: DiscoveryCandidate,
  result: OnvifInspection
): string {
  const baseName =
    candidateName(candidate) ||
    result.device.model ||
    result.device.manufacturer ||
    candidate.host ||
    t("cameras.onboarding.onvifDevice")
  const rendered = batchNameTemplate.value
    .replaceAll("{name}", baseName)
    .replaceAll("{host}", candidate.host ?? "")
    .trim()
  return (rendered || baseName).slice(0, 128)
}

function batchPolicy(): RecordingPolicyPut {
  const eventsOnly = batchRecordingMode.value === "events"
  const disabled = batchRecordingMode.value === "off"

  return {
    baseline_mode:
      eventsOnly || disabled ? "disabled" : "continuous",
    schedule: {},
    schedule_timezone: null,
    event_recording_enabled: eventsOnly,
    event_filter: {},
    segment_target_seconds: 300,
    pre_roll_seconds: 10,
    post_roll_seconds: 10,
    storage_target_id: batchStorageTargetId.value || null,
    retention_policy_id: null,
    enabled: !disabled
  }
}

function setBatchResult(
  candidate: DiscoveryCandidate,
  state: BatchResultState,
  message: string,
  cameraIds: string[] = []
): void {
  const next: BatchResult = {
    candidate_id: candidate.id,
    label: candidateName(candidate),
    state,
    message,
    camera_ids: cameraIds
  }
  const index = batchResults.value.findIndex(
    (item) => item.candidate_id === candidate.id
  )
  if (index >= 0) {
    batchResults.value.splice(index, 1, next)
  } else {
    batchResults.value.push(next)
  }
}

async function applyBatchGroup(cameraIds: string[]): Promise<void> {
  if (!batchGroupId.value || !cameraIds.length) return

  const group = batchGroups.value.find(
    (item) => item.id === batchGroupId.value
  )
  if (!group) {
    throw new Error(t("cameras.onboarding.selectedGroupMissing"))
  }

  const merged = Array.from(
    new Set([...group.camera_ids, ...cameraIds])
  )
  const updated = await updateCameraGroup(group.id, {
    camera_ids: merged
  })
  batchGroups.value = batchGroups.value.map((item) =>
    item.id === updated.id ? updated : item
  )
}

async function applyBatchDefaults(
  cameraIds: string[],
  options: { timeSync: boolean }
): Promise<void> {
  for (const cameraId of cameraIds) {
    if (options.timeSync) {
      await updateCamera(cameraId, {
        time_sync_mode: batchTimeSyncMode.value
      })
    }
    await putRecordingPolicy(cameraId, batchPolicy())
  }
  await applyBatchGroup(cameraIds)
}

function setFileBatchResult(
  row: FileImportRow,
  state: BatchResultState,
  message: string,
  cameraIds: string[] = []
): void {
  const label = row.name || row.host || `CSV line ${row.line}`
  const next: FileBatchResult = {
    line: row.line,
    label,
    state,
    message,
    camera_ids: cameraIds
  }
  const index = fileBatchResults.value.findIndex(
    (item) => item.line === row.line
  )
  if (index >= 0) {
    fileBatchResults.value.splice(index, 1, next)
  } else {
    fileBatchResults.value.push(next)
  }
}

async function runFileBatchImport(): Promise<void> {
  if (!canFileBatchImport.value) return

  clearMessages()
  working.value = "file-batch"
  fileBatchResults.value = []
  let changed = false

  try {
    await loadBatchDefaults()

    for (const row of fileBatchRows.value) {
      if (row.errors.length || !row.kind) {
        setFileBatchResult(
          row,
          "failed",
          row.errors.join(" · ") ||
            t("cameras.onboarding.csvUnsupportedType", { type: "?" })
        )
        continue
      }
      setFileBatchResult(
        row,
        "running",
        t("cameras.onboarding.fileBatchValidating")
      )

      let cameraIds: string[] = []
      try {
        if (row.kind === "onvif") {
          const credentials = {
            host: row.host,
            port: row.onvif_port,
            username: row.username,
            password: row.password
          }
          const inspected = await inspectOnvif(credentials)
          if (inspected.identity.state !== "new_device") {
            const message =
              inspected.identity.state === "identity_conflict"
                ? t("cameras.onboarding.identityConflictReview")
                : inspected.identity.state ===
                    "probable_match_requires_confirmation"
                  ? t("cameras.onboarding.weakIdentityReview")
                  : t("cameras.onboarding.existingReview")
            setFileBatchResult(row, "review", message)
            continue
          }

          const profileTokens = inspected.profiles
            .filter((profile) => profile.stream_uri_available)
            .map((profile) => profile.token)
          if (!profileTokens.length) {
            setFileBatchResult(
              row,
              "failed",
              t("cameras.onboarding.noProfiles")
            )
            continue
          }

          const imported = await importOnvif({
            ...credentials,
            name: normalizeOptional(row.name),
            location: normalizeOptional(row.location),
            storage_label: normalizeOptional(row.storage_label),
            profile_tokens: profileTokens
          })
          cameraIds = imported.cameras.map((camera) => camera.id)
          changed = true
          await applyBatchDefaults(cameraIds, { timeSync: true })
        } else {
          const mainUrl = buildRtspUrl(
            row,
            row.main_path,
            row.main_url
          )
          const subUrl = buildRtspUrl(
            row,
            row.sub_path,
            row.sub_url
          )
          const body: ManualCameraInput = {
            mode: "manual_rtsp",
            name: row.name,
            location: normalizeOptional(row.location),
            storage_label: normalizeOptional(row.storage_label),
            primary_stream: {
              name: t("cameras.onboarding.mainStream"),
              rtsp_url: mainUrl
            },
            secondary_stream: subUrl
              ? {
                  name: t("cameras.onboarding.subStream"),
                  rtsp_url: subUrl
                }
              : null
          }
          await testManualCamera(body)
          const created = await createManualCamera(body)
          cameraIds = [created.id]
          changed = true
          await applyBatchDefaults(cameraIds, { timeSync: false })
        }

        setFileBatchResult(
          row,
          "success",
          t("cameras.onboarding.fileBatchImported", {
            count: cameraIds.length
          }),
          cameraIds
        )
      } catch (caught) {
        setFileBatchResult(
          row,
          cameraIds.length ? "partial" : "failed",
          cameraIds.length
            ? t("cameras.onboarding.batchPartial", {
                error: errorMessage(caught)
              })
            : errorMessage(caught),
          cameraIds
        )
      }
    }

    const successful = fileBatchResults.value.filter(
      (item) => item.state === "success"
    ).length
    const partial = fileBatchResults.value.filter(
      (item) => item.state === "partial"
    ).length
    const review = fileBatchResults.value.filter(
      (item) => item.state === "review"
    ).length
    const failed = fileBatchResults.value.filter(
      (item) => item.state === "failed"
    ).length
    successMessage.value = t("cameras.onboarding.fileBatchFinished", {
      successful,
      partial,
      review,
      failed
    })
    fileBatchCompleted.value = true
    fileBatchRows.value = []
    fileBatchName.value = ""
    if (changed) {
      emit("changed")
    }
  } finally {
    working.value = null
  }
}

async function runBatchImport(): Promise<void> {
  if (!canBatchImport.value) return

  clearMessages()
  working.value = "batch"
  batchResults.value = []

  let changed = false
  try {
    for (const candidate of batchCandidates.value) {
      setBatchResult(
        candidate,
        "running",
        t("cameras.onboarding.inspectingBatch")
      )

      const host = candidate.host
      if (!host) {
        setBatchResult(
          candidate,
          "failed",
          t("cameras.onboarding.noHost")
        )
        continue
      }

      const override = batchCredential(candidate.id)
      const credentials = {
        host,
        port: candidate.port ?? 80,
        username:
          override.username.trim() || batchUsername.value.trim(),
        password: override.password || batchPassword.value
      }

      let importedCameraIds: string[] = []
      try {
        const inspected = await inspectOnvif(credentials)

        if (inspected.identity.state !== "new_device") {
          const message =
            inspected.identity.state === "identity_conflict"
              ? t("cameras.onboarding.identityConflictReview")
              : inspected.identity.state ===
                  "probable_match_requires_confirmation"
                ? t("cameras.onboarding.weakIdentityReview")
                : t("cameras.onboarding.existingReview")
          setBatchResult(candidate, "review", message)
          continue
        }

        const profileTokens = inspected.profiles
          .filter((profile) => profile.stream_uri_available)
          .map((profile) => profile.token)
        if (!profileTokens.length) {
          setBatchResult(
            candidate,
            "failed",
            t("cameras.onboarding.noProfiles")
          )
          continue
        }

        const imported = await importOnvif({
          ...credentials,
          name: batchDeviceName(candidate, inspected),
          location: null,
          storage_label: null,
          profile_tokens: profileTokens,
          discovery_candidate_id: candidate.id
        })
        importedCameraIds = imported.cameras.map(
          (camera) => camera.id
        )
        changed = true

        await applyBatchDefaults(importedCameraIds, {
          timeSync: true
        })

        setBatchResult(
          candidate,
          "success",
          t("cameras.onboarding.batchImported", { count: importedCameraIds.length }),
          importedCameraIds
        )
      } catch (caught) {
        setBatchResult(
          candidate,
          importedCameraIds.length ? "partial" : "failed",
          importedCameraIds.length
            ? t("cameras.onboarding.batchPartial", { error: errorMessage(caught) })
            : errorMessage(caught),
          importedCameraIds
        )
      }
    }

    const successful = batchResults.value.filter(
      (item) => item.state === "success"
    ).length
    const partial = batchResults.value.filter(
      (item) => item.state === "partial"
    ).length
    const review = batchResults.value.filter(
      (item) => item.state === "review"
    ).length
    successMessage.value = t("cameras.onboarding.batchFinished", {
      successful,
      partial,
      review
    })
    batchPassword.value = ""
    for (const override of Object.values(batchOverrides.value)) {
      override.password = ""
    }
    if (changed) {
      emit("changed")
    }
  } finally {
    working.value = null
  }
}
function batchStateLabel(value: BatchResultState): string {
  const key = `cameras.onboarding.batchState.${value}`
  return te(key) ? t(key) : value
}

function discoveryStateLabel(value: string): string {
  const key = `cameras.onboarding.discoveryState.${value.toLowerCase()}`
  return te(key) ? t(key) : value
}

</script>

<template>
  <section class="panel onboarding-panel">
    <div class="panel__header onboarding-panel__header">
      <div>
        <p class="eyebrow">{{ t("cameras.onboarding.title") }}</p>
        <h2>{{ t("cameras.onboarding.addCameraOrDevice") }}</h2>
      </div>
      <button class="button button--ghost" type="button" @click="emit('close')">
        {{ t("cameras.onboarding.close") }}
      </button>
    </div>

    <div class="segmented-tabs" role="tablist" :aria-label="t('cameras.onboarding.modeAria')">
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'onvif'"
        :class="{ 'segmented-tabs__item--active': mode === 'onvif' }"
        class="segmented-tabs__item"
        @click="mode = 'onvif'; clearMessages()"
      >
        ONVIF
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'rtsp'"
        :class="{ 'segmented-tabs__item--active': mode === 'rtsp' }"
        class="segmented-tabs__item"
        @click="mode = 'rtsp'; clearMessages()"
      >
        {{ t("cameras.onboarding.manualRtsp") }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'batch_file'"
        :class="{ 'segmented-tabs__item--active': mode === 'batch_file' }"
        class="segmented-tabs__item"
        @click="mode = 'batch_file'; clearMessages(); loadBatchDefaults()"
      >
        {{ t("cameras.onboarding.batchFile") }}
      </button>
    </div>

    <p v-if="requestError" class="notice notice--error" role="alert">
      {{ requestError }}
    </p>
    <p v-if="successMessage" class="notice notice--success" role="status">
      {{ successMessage }}
    </p>

    <div v-if="mode === 'onvif'" class="onboarding-grid">
      <div class="onboarding-step">
        <div class="step-heading">
          <span>1</span>
          <div>
            <strong>{{ t("cameras.onboarding.findDevice") }}</strong>
            <p>{{ t("cameras.onboarding.findHint") }}</p>
          </div>
        </div>

        <button
          class="button button--secondary"
          type="button"
          :disabled="working !== null"
          @click="runDiscovery"
        >
          {{ working === "discover" ? t("cameras.onboarding.discovering") : t("cameras.onboarding.discoverDevices") }}
        </button>

        <div
          v-if="discovery && discovery.candidates.length"
          class="candidate-list"
        >
          <button
            v-for="candidate in discovery.candidates"
            :key="candidate.id"
            type="button"
            class="candidate-card"
            :class="{
              'candidate-card--selected': selectedCandidateId === candidate.id
            }"
            :disabled="!candidate.host"
            @click="useCandidate(candidate)"
          >
            <strong>{{ candidate.host || t("cameras.onboarding.addressUnavailable") }}</strong>
            <span>
              {{ candidate.port ? t("cameras.onboarding.portValue", { port: candidate.port }) : t("cameras.onboarding.defaultPort") }}
              · {{ discoveryStateLabel(candidate.state) }}
            </span>
          </button>
        </div>
        <p
          v-else-if="discovery"
          class="field-hint onboarding-hint"
        >
          {{ t("cameras.onboarding.noOnvifDevices") }}
        </p>

        <div
          v-if="discovery && discovery.candidates.length"
          class="onboarding-step"
        >
          <div class="step-heading">
            <span>B</span>
            <div>
              <strong>{{ t("cameras.onboarding.batchOnboarding") }}</strong>
              <p>
                {{ t("cameras.onboarding.batchHint") }}
              </p>
            </div>
          </div>

          <div class="profile-list">
            <div
              v-for="candidate in discovery.candidates"
              :key="`batch-${candidate.id}`"
              class="probe-card"
            >
              <label class="check-row">
                <input
                  v-model="batchSelectedIds"
                  type="checkbox"
                  :value="candidate.id"
                  :disabled="!candidate.host || working !== null"
                />
                <span>
                  <strong>{{ candidateName(candidate) }}</strong>
                  · {{ candidate.host || t("cameras.onboarding.addressUnavailable") }}
                </span>
              </label>

              <div
                v-if="batchSelectedIds.includes(candidate.id)"
                class="form-grid"
              >
                <label class="field">
                  <span>{{ t("cameras.onboarding.usernameOverride") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
                  <input
                    v-model="batchCredential(candidate.id).username"
                    autocomplete="off"
                    :placeholder="t('cameras.onboarding.useSharedUsername')"
                  />
                </label>
                <label class="field">
                  <span>{{ t("cameras.onboarding.passwordOverride") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
                  <input
                    v-model="batchCredential(candidate.id).password"
                    type="password"
                    autocomplete="new-password"
                    :placeholder="t('cameras.onboarding.useSharedPassword')"
                  />
                </label>
              </div>

              <p
                v-if="batchResultMap.get(candidate.id)"
                class="field-hint"
              >
                <strong>
                  {{ batchStateLabel(batchResultMap.get(candidate.id)?.state || "pending") }}
                </strong>
                · {{ batchResultMap.get(candidate.id)?.message }}
              </p>
            </div>
          </div>

          <div class="form-grid form-grid--three">
            <label class="field">
              <span>{{ t("cameras.onboarding.sharedUsername") }}</span>
              <input
                v-model="batchUsername"
                autocomplete="username"
              />
            </label>
            <label class="field">
              <span>{{ t("cameras.onboarding.sharedPassword") }}</span>
              <input
                v-model="batchPassword"
                type="password"
                autocomplete="new-password"
              />
            </label>
            <label class="field">
              <span>{{ t("cameras.onboarding.nameTemplate") }}</span>
              <input
                v-model="batchNameTemplate"
                placeholder="{name}"
              />
              <small>{{ t("cameras.onboarding.nameTemplateHint", { name: "{name}", host: "{host}" }) }}</small>
            </label>
          </div>

          <div class="form-grid form-grid--three">
            <label class="field">
              <span>{{ t("cameras.onboarding.cameraGroup") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
              <select v-model="batchGroupId">
                <option value="">{{ t("cameras.onboarding.noGroup") }}</option>
                <option
                  v-for="group in batchGroups"
                  :key="group.id"
                  :value="group.id"
                >
                  {{ group.name }}
                </option>
              </select>
            </label>
            <label class="field">
              <span>{{ t("cameras.onboarding.recordingDefault") }}</span>
              <select v-model="batchRecordingMode">
                <option value="continuous">{{ t("cameras.onboarding.continuous") }}</option>
                <option value="events">{{ t("cameras.onboarding.eventsOnly") }}</option>
                <option value="off">{{ t("cameras.onboarding.off") }}</option>
              </select>
            </label>
            <label class="field">
              <span>{{ t("cameras.onboarding.storageTarget") }}</span>
              <select
                v-model="batchStorageTargetId"
                :disabled="!auth.hasPermission('storage.manage')"
              >
                <option value="">{{ t("cameras.onboarding.systemDefault") }}</option>
                <option
                  v-for="target in batchStorageTargets"
                  :key="target.id"
                  :value="target.id"
                >
                  {{ target.name }}
                </option>
              </select>
            </label>
          </div>

          <div class="form-grid form-grid--three">
            <label class="field">
              <span>{{ t("cameras.onboarding.timeSyncDefault") }}</span>
              <select v-model="batchTimeSyncMode">
                <option value="monitor">{{ t("cameras.onboarding.monitorOnly") }}</option>
                <option value="manage_ntp">{{ t("cameras.onboarding.manageNtp") }}</option>
                <option value="ignore">{{ t("cameras.onboarding.ignore") }}</option>
              </select>
            </label>
          </div>

          <div class="onboarding-actions">
            <span class="field-hint">
              {{ t("cameras.onboarding.devicesSelected", { count: batchSelectedIds.length }) }}
            </span>
            <button
              class="button button--primary"
              type="button"
              :disabled="!canBatchImport"
              @click="runBatchImport"
            >
              {{ working === "batch" ? t("cameras.onboarding.batchImporting") : t("cameras.onboarding.importSelectedDevices") }}
            </button>
          </div>
        </div>

        <div class="form-grid form-grid--three">
          <label class="field field--grow">
            <span>{{ t("cameras.onboarding.hostOrIp") }}</span>
            <input
              v-model="onvifHost"
              placeholder="192.168.1.50"
              autocomplete="off"
              required
            />
          </label>
          <label class="field">
            <span>{{ t("cameras.onboarding.port") }}</span>
            <input
              v-model.number="onvifPort"
              type="number"
              min="1"
              max="65535"
              inputmode="numeric"
            />
          </label>
          <label class="field">
            <span>{{ t("cameras.onboarding.username") }}</span>
            <input v-model="onvifUsername" autocomplete="username" />
          </label>
        </div>

        <label class="field">
          <span>{{ t("cameras.onboarding.password") }}</span>
          <input
            v-model="onvifPassword"
            type="password"
            autocomplete="current-password"
          />
        </label>

        <button
          class="button button--primary"
          type="button"
          :disabled="working !== null || !onvifHost.trim()"
          @click="inspectDevice"
        >
          {{ working === "inspect" ? t("cameras.onboarding.inspecting") : t("cameras.onboarding.testInspect") }}
        </button>
      </div>

      <div class="onboarding-step">
        <div class="step-heading">
          <span>2</span>
          <div>
            <strong>{{ t("cameras.onboarding.chooseProfiles") }}</strong>
            <p>{{ t("cameras.onboarding.profilesHint") }}</p>
          </div>
        </div>

        <div v-if="inspection" class="inspection-card">
          <div class="device-summary">
            <strong>
              {{ inspection.device.manufacturer || t("cameras.onboarding.onvifDevice") }}
              {{ inspection.device.model || "" }}
            </strong>
            <span v-if="inspection.device.serial_number">
              S/N {{ inspection.device.serial_number }}
            </span>
          </div>

          <p
            v-if="inspection.identity.state === 'new_device'"
            class="notice notice--success"
            role="status"
          >
            {{ t("cameras.onboarding.newIdentity") }}
          </p>
          <p
            v-else-if="inspection.identity.state === 'same_device'"
            class="notice notice--success"
            role="status"
          >
            {{ t("cameras.onboarding.existingIdentityPrefix") }}
            <strong>
              {{ inspection.identity.matched_device_name || inspection.identity.matched_device_id }}
            </strong>{{ t("cameras.onboarding.existingIdentitySuffix") }}
          </p>
          <div
            v-else-if="
              inspection.identity.state ===
              'probable_match_requires_confirmation'
            "
            class="notice"
            role="status"
          >
            <strong>{{ t("cameras.onboarding.identityConfirmation") }}</strong>
            {{ t("cameras.onboarding.endpointBelongsPrefix") }}
            <strong>
              {{ inspection.identity.matched_device_name || inspection.identity.matched_device_id }}
            </strong>{{ t("cameras.onboarding.endpointBelongsSuffix") }}
            <label class="check-row">
              <input v-model="confirmExistingIdentity" type="checkbox" />
              <span>{{ t("cameras.onboarding.confirmSameDevice") }}</span>
            </label>
          </div>
          <p
            v-else
            class="notice notice--error"
            role="alert"
          >
            <strong>{{ t("cameras.onboarding.identityConflict") }}</strong>
            {{ t("cameras.onboarding.identityConflictHint") }}
          </p>

          <div class="profile-list">
            <label
              v-for="profile in inspection.profiles"
              :key="profile.token"
              class="profile-option"
              :class="{ 'profile-option--disabled': !profile.stream_uri_available }"
            >
              <input
                v-model="selectedProfiles"
                type="checkbox"
                :value="profile.token"
                :disabled="!profile.stream_uri_available"
              />
              <span>
                <strong>{{ profile.name }}</strong>
                <small>{{ profileSummary(profile) }}</small>
              </span>
            </label>
          </div>
        </div>

        <div v-else class="step-empty">
          {{ t("cameras.onboarding.testDeviceHint") }}
        </div>
      </div>

      <div class="onboarding-step onboarding-step--full">
        <div class="step-heading">
          <span>3</span>
          <div>
            <strong>{{ t("cameras.onboarding.importIntoDeviceCenter") }}</strong>
            <p>
              {{ t("cameras.onboarding.importHint") }}
            </p>
          </div>
        </div>

        <div class="form-grid form-grid--three">
          <label class="field">
            <span>{{ t("cameras.name") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
            <input v-model="onvifName" :placeholder="t('cameras.onboarding.frontEntrance')" />
          </label>
          <label class="field">
            <span>{{ t("cameras.location") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
            <input v-model="onvifLocation" :placeholder="t('cameras.onboarding.groundFloor')" />
          </label>
          <label class="field">
            <span>{{ t("cameras.storageLabel") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
            <input v-model="onvifStorageLabel" placeholder="entrance" />
          </label>
        </div>

        <div class="onboarding-actions">
          <span class="field-hint">
            {{ t("cameras.onboarding.profilesSelected", { count: selectedProfiles.length }) }}
          </span>
          <button
            class="button button--primary"
            type="button"
            :disabled="!canImport"
            @click="importDevice"
          >
            {{ importActionLabel }}
          </button>
        </div>
      </div>
    </div>

    <div v-else-if="mode === 'batch_file'" class="onboarding-grid">
      <div class="onboarding-step onboarding-step--full">
        <div class="step-heading">
          <span>1</span>
          <div>
            <strong>{{ t("cameras.onboarding.batchFileTitle") }}</strong>
            <p>{{ t("cameras.onboarding.batchFileHint") }}</p>
          </div>
        </div>

        <div class="onboarding-actions">
          <button
            class="button button--secondary"
            type="button"
            :disabled="working !== null"
            @click="downloadBatchTemplate"
          >
            {{ t("cameras.onboarding.downloadCsvTemplate") }}
          </button>
          <label class="field field--grow">
            <span>{{ t("cameras.onboarding.chooseCsvFile") }}</span>
            <input
              type="file"
              accept=".csv,text/csv"
              :disabled="working !== null"
              @change="handleBatchFile"
            />
          </label>
        </div>

        <p class="field-hint">
          {{ t("cameras.onboarding.csvColumns") }}
        </p>
        <p v-if="fileBatchName" class="field-hint">
          {{
            t("cameras.onboarding.csvLoaded", {
              file: fileBatchName,
              total: fileBatchRows.length,
              valid: fileBatchReadyCount,
              invalid: fileBatchInvalidCount
            })
          }}
        </p>

        <div v-if="fileBatchRows.length" class="profile-list">
          <article
            v-for="row in fileBatchRows"
            :key="row.line"
            class="probe-card"
          >
            <div class="device-summary">
              <strong>
                {{ t("cameras.onboarding.csvLine", { line: row.line }) }}
                · {{ row.kind?.toUpperCase() || "?" }}
              </strong>
              <span>{{ row.name || row.host || "—" }}</span>
            </div>
            <p
              v-if="row.errors.length"
              class="notice notice--error"
            >
              {{ row.errors.join(" · ") }}
            </p>
            <p v-else class="field-hint">
              {{ t("cameras.onboarding.csvReady") }}
            </p>
          </article>
        </div>
      </div>

      <div class="onboarding-step onboarding-step--full">
        <div class="step-heading">
          <span>2</span>
          <div>
            <strong>{{ t("cameras.onboarding.batchDefaults") }}</strong>
            <p>{{ t("cameras.onboarding.batchDefaultsHint") }}</p>
          </div>
        </div>

        <div class="form-grid form-grid--three">
          <label class="field">
            <span>{{ t("cameras.onboarding.cameraGroup") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
            <select v-model="batchGroupId">
              <option value="">{{ t("cameras.onboarding.noGroup") }}</option>
              <option
                v-for="group in batchGroups"
                :key="group.id"
                :value="group.id"
              >
                {{ group.name }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>{{ t("cameras.onboarding.recordingDefault") }}</span>
            <select v-model="batchRecordingMode">
              <option value="continuous">{{ t("cameras.onboarding.continuous") }}</option>
              <option value="events">{{ t("cameras.onboarding.eventsOnly") }}</option>
              <option value="off">{{ t("cameras.onboarding.off") }}</option>
            </select>
          </label>
          <label class="field">
            <span>{{ t("cameras.onboarding.storageTarget") }}</span>
            <select
              v-model="batchStorageTargetId"
              :disabled="!auth.hasPermission('storage.manage')"
            >
              <option value="">{{ t("cameras.onboarding.systemDefault") }}</option>
              <option
                v-for="target in batchStorageTargets"
                :key="target.id"
                :value="target.id"
              >
                {{ target.name }}
              </option>
            </select>
          </label>
        </div>

        <div class="form-grid form-grid--three">
          <label class="field">
            <span>{{ t("cameras.onboarding.timeSyncDefault") }}</span>
            <select v-model="batchTimeSyncMode">
              <option value="monitor">{{ t("cameras.onboarding.monitorOnly") }}</option>
              <option value="manage_ntp">{{ t("cameras.onboarding.manageNtp") }}</option>
              <option value="ignore">{{ t("cameras.onboarding.ignore") }}</option>
            </select>
          </label>
        </div>
      </div>

      <div class="onboarding-step onboarding-step--full">
        <div class="step-heading">
          <span>3</span>
          <div>
            <strong>{{ t("cameras.onboarding.batchFileImport") }}</strong>
            <p>{{ t("cameras.onboarding.batchFileImportHint") }}</p>
          </div>
        </div>

        <div class="onboarding-actions">
          <span class="field-hint">
            {{ t("cameras.onboarding.csvReadyCount", { count: fileBatchReadyCount }) }}
          </span>
          <button
            class="button button--primary"
            type="button"
            :disabled="!canFileBatchImport"
            @click="runFileBatchImport"
          >
            {{
              working === "file-batch"
                ? t("cameras.onboarding.fileBatchImporting")
                : t("cameras.onboarding.importCsvRows", {
                    count: fileBatchReadyCount
                  })
            }}
          </button>
        </div>

        <div v-if="fileBatchResults.length" class="profile-list">
          <article
            v-for="result in fileBatchResults"
            :key="result.line"
            class="probe-card"
          >
            <div class="device-summary">
              <strong>
                {{ t("cameras.onboarding.csvLine", { line: result.line }) }}
                · {{ result.label }}
              </strong>
              <span>{{ batchStateLabel(result.state) }}</span>
            </div>
            <p>{{ result.message }}</p>
          </article>
        </div>
      </div>
    </div>

    <div v-else class="onboarding-grid">
      <div class="onboarding-step">
        <div class="step-heading">
          <span>1</span>
          <div>
            <strong>{{ t("cameras.onboarding.describeCamera") }}</strong>
            <p>{{ t("cameras.onboarding.manualHint") }}</p>
          </div>
        </div>

        <label class="field">
          <span>{{ t("cameras.onboarding.cameraName") }}</span>
          <input v-model="manualName" :placeholder="t('cameras.onboarding.garage')" required />
        </label>

        <div class="form-grid">
          <label class="field">
            <span>{{ t("cameras.location") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
            <input v-model="manualLocation" />
          </label>
          <label class="field">
            <span>{{ t("cameras.storageLabel") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
            <input v-model="manualStorageLabel" />
          </label>
        </div>
      </div>

      <div class="onboarding-step">
        <div class="step-heading">
          <span>2</span>
          <div>
            <strong>{{ t("cameras.onboarding.configureStreams") }}</strong>
            <p>{{ t("cameras.onboarding.zlmHint") }}</p>
          </div>
        </div>

        <label class="field">
          <span>{{ t("cameras.onboarding.primaryStreamName") }}</span>
          <input v-model="primaryName" required />
        </label>
        <label class="field">
          <span>{{ t("cameras.onboarding.primaryRtspUrl") }}</span>
          <input
            v-model="primaryUrl"
            type="password"
            autocomplete="off"
            placeholder="rtsp://user:password@camera/stream"
            required
          />
        </label>

        <label class="check-row">
          <input v-model="secondaryEnabled" type="checkbox" />
          <span>{{ t("cameras.onboarding.addSecondary") }}</span>
        </label>

        <template v-if="secondaryEnabled">
          <label class="field">
            <span>{{ t("cameras.onboarding.secondaryStreamName") }}</span>
            <input v-model="secondaryName" required />
          </label>
          <label class="field">
            <span>{{ t("cameras.onboarding.secondaryRtspUrl") }}</span>
            <input
              v-model="secondaryUrl"
              type="password"
              autocomplete="off"
              required
            />
          </label>
        </template>
      </div>

      <div class="onboarding-step onboarding-step--full">
        <div class="step-heading">
          <span>3</span>
          <div>
            <strong>{{ t("cameras.onboarding.verifyBeforeCreating") }}</strong>
            <p>
              {{ t("cameras.onboarding.verifyHint") }}
            </p>
          </div>
        </div>

        <div v-if="manualProbe" class="probe-results">
          <article
            v-for="stream in manualProbe.streams"
            :key="stream.role"
            class="probe-card"
          >
            <div>
              <strong>{{ stream.name }}</strong>
              <span>{{ stream.role }}</span>
            </div>
            <p>
              {{ t("cameras.onboarding.video") }}
              <strong>{{ stream.video?.codec || t("cameras.onboarding.notDetected") }}</strong>
              <template v-if="stream.video?.width && stream.video?.height">
                · {{ stream.video.width }}×{{ stream.video.height }}
              </template>
            </p>
            <p>
              {{ t("cameras.onboarding.audio") }}
              <strong>{{ stream.audio?.codec || t("cameras.onboarding.none") }}</strong>
            </p>
          </article>
        </div>

        <div class="onboarding-actions">
          <button
            class="button button--secondary"
            type="button"
            :disabled="
              working !== null ||
              !manualName.trim() ||
              !primaryUrl.trim()
            "
            @click="testRtsp"
          >
            {{ working === "test" ? t("cameras.onboarding.testing") : t("cameras.onboarding.testStreams") }}
          </button>
          <button
            class="button button--primary"
            type="button"
            :disabled="!canCreateManual"
            @click="createRtsp"
          >
            {{ working === "create" ? t("cameras.onboarding.creating") : t("cameras.onboarding.createCamera") }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
