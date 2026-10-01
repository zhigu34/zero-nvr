<script setup lang="ts">
import { computed, ref, watch } from "vue"
import CameraOnboardingBatchFile from "./CameraOnboardingBatchFile.vue"
import CameraOnboardingInspection from "./CameraOnboardingInspection.vue"
import CameraOnboardingConnection from "./CameraOnboardingConnection.vue"
import CameraOnboardingDiscovery from "./CameraOnboardingDiscovery.vue"
import CameraOnboardingBatchStep from "./CameraOnboardingBatchStep.vue"
import CameraOnboardingManualFlow from "./CameraOnboardingManualFlow.vue"
import {
  type BatchCredentialOverride,
  type BatchResult,
  type BatchResultState,
  type BatchTimeSyncMode,
  type FileBatchResult,
  type FileImportKind,
  type FileImportRow,
  type OnboardingMode as Mode,
  type OnboardingWorkingAction as WorkingAction
} from "./onboarding"
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
import { ApiClientError, errorMessage } from "../../api/client"
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


const props = withDefaults(
  defineProps<{
    initialMode?: Mode
  }>(),
  {
    initialMode: "onvif"
  }
)

const mode = ref<Mode>(props.initialMode)
watch(() => props.initialMode, (val) => {
  if (val) mode.value = val
})
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

const batchSelectedIds = ref<string[]>([])
const batchUsername = ref("")
const batchPassword = ref("")
const batchNameTemplate = ref("{name}")
const batchGroupId = ref("")
const batchRecordingMode = ref<"continuous" | "events" | "off">(
  "continuous"
)
const batchStorageTargetId = ref("")
const batchTimeSyncMode = ref<BatchTimeSyncMode>("monitor")
const batchGroups = ref<CameraGroup[]>([])
const batchStorageTargets = ref<StorageTarget[]>([])
const batchOverrides = ref<Record<string, BatchCredentialOverride>>({})
const batchResults = ref<BatchResult[]>([])

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


const fileBatchReadyCount = computed(
  () => fileBatchRows.value.filter((row) => !row.errors.length).length
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

/**
 * Parse a CSV the operator picked.
 *
 * The batch-file component owns the file input (and clears it after every pick,
 * so the same file can be re-selected), so this receives the `File` itself.
 */
async function handleBatchFile(file: File): Promise<void> {
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
    try {
      await putRecordingPolicy(cameraId, batchPolicy())
    } catch (err: unknown) {
      if (!(err instanceof ApiClientError && err.details?.policy_persisted)) {
        throw err
      }
    }
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

        <CameraOnboardingDiscovery
          :discovery="discovery"
          :selected-candidate-id="selectedCandidateId"
          :working="working"
          @discover="runDiscovery"
          @use-candidate="useCandidate"
        />

        <CameraOnboardingBatchStep
          v-if="discovery && discovery.candidates.length"
          :discovery="discovery"
          v-model:batch-selected-ids="batchSelectedIds"
          v-model:batch-name-template="batchNameTemplate"
          v-model:batch-username="batchUsername"
          v-model:batch-password="batchPassword"
          v-model:batch-group-id="batchGroupId"
          v-model:batch-recording-mode="batchRecordingMode"
          v-model:batch-storage-target-id="batchStorageTargetId"
          v-model:batch-time-sync-mode="batchTimeSyncMode"
          :batch-groups="batchGroups"
          :batch-storage-targets="batchStorageTargets"
          :batch-results="batchResults"
          :can-manage-storage="auth.hasPermission('storage.manage')"
          :working="working"
          :batch-credential="batchCredential"
          :candidate-name="candidateName"
          :batch-state-label="batchStateLabel"
          @run="runBatchImport"
        />

        <CameraOnboardingConnection
          v-model:onvif-host="onvifHost"
          v-model:onvif-port="onvifPort"
          v-model:onvif-username="onvifUsername"
          v-model:onvif-password="onvifPassword"
          :working="working"
          @inspect="inspectDevice"
        />
      </div>

      <CameraOnboardingInspection
        :inspection="inspection"
        v-model:confirm-existing-identity="confirmExistingIdentity"
        v-model:selected-profiles="selectedProfiles"
      />

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

    <CameraOnboardingBatchFile
      v-else-if="mode == 'batch_file'"
      v-model:batch-group-id="batchGroupId"
      v-model:batch-recording-mode="batchRecordingMode"
      v-model:batch-storage-target-id="batchStorageTargetId"
      v-model:batch-time-sync-mode="batchTimeSyncMode"
      :batch-groups="batchGroups"
      :batch-storage-targets="batchStorageTargets"
      :file-batch-name="fileBatchName"
      :file-batch-rows="fileBatchRows"
      :file-batch-results="fileBatchResults"
      :can-file-batch-import="canFileBatchImport"
      :can-manage-storage="auth.hasPermission('storage.manage')"
      :working="working"
      :batch-state-label="batchStateLabel"
      @download-template="downloadBatchTemplate"
      @file-selected="handleBatchFile"
      @run="runFileBatchImport"
    />

    <CameraOnboardingManualFlow
      v-else
      v-model:manual-name="manualName"
      v-model:manual-location="manualLocation"
      v-model:manual-storage-label="manualStorageLabel"
      v-model:primary-name="primaryName"
      v-model:primary-url="primaryUrl"
      v-model:secondary-enabled="secondaryEnabled"
      v-model:secondary-name="secondaryName"
      v-model:secondary-url="secondaryUrl"
      :manual-probe="manualProbe"
      :working="working"
      :can-create-manual="canCreateManual"
      @test="testRtsp"
      @create="createRtsp"
    />
  </section>
</template>
