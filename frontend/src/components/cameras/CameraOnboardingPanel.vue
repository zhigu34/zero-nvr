<script setup lang="ts">
import { computed, ref } from "vue"

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
  close: []
}>()

const auth = useAuthStore()

type Mode = "onvif" | "rtsp"
type WorkingAction =
  | "discover"
  | "inspect"
  | "import"
  | "batch"
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
const primaryName = ref("Main stream")
const primaryUrl = ref("")
const secondaryEnabled = ref(false)
const secondaryName = ref("Sub stream")
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

const identity = computed(() => inspection.value?.identity ?? null)
const identityRequiresConfirmation = computed(
  () => identity.value?.state === "probable_match_requires_confirmation"
)
const identityConflict = computed(
  () => identity.value?.state === "identity_conflict"
)
const importActionLabel = computed(() => {
  if (working.value === "import") return "Importing…"
  if (identity.value?.state === "same_device") return "Refresh existing device"
  if (identityRequiresConfirmation.value) return "Confirm & refresh device"
  return "Import device"
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
    successMessage.value = "Camera created and credentials stored server-side."
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
        ? "Existing ONVIF device refreshed after identity review. Camera identity and history were preserved while endpoint, credentials and stream URIs were updated."
        : "ONVIF device imported. Stream credentials remain in the zero-nvr secret store."
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
  return parts.filter(Boolean).join(" · ") || "Profile details unavailable"
}

function candidateName(candidate: DiscoveryCandidate): string {
  const discoveredName = candidate.display_info.name
  if (
    typeof discoveredName === "string" &&
    discoveredName.trim()
  ) {
    return discoveredName.trim()
  }
  return candidate.host || "ONVIF device"
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
    "ONVIF device"
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
    throw new Error("Selected camera group is no longer available.")
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
        "Inspecting device identity and media profiles…"
      )

      const host = candidate.host
      if (!host) {
        setBatchResult(
          candidate,
          "failed",
          "Candidate has no usable host address."
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
              ? "Identity conflict requires manual resolution."
              : inspected.identity.state ===
                  "probable_match_requires_confirmation"
                ? "Weak identity match requires explicit single-device confirmation."
                : "Existing device detected; review it individually before changing defaults."
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
            "No usable RTSP profiles were reported."
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

        for (const camera of imported.cameras) {
          await updateCamera(camera.id, {
            time_sync_mode: batchTimeSyncMode.value
          })
          await putRecordingPolicy(camera.id, batchPolicy())
        }
        await applyBatchGroup(importedCameraIds)

        setBatchResult(
          candidate,
          "success",
          `Imported ${importedCameraIds.length} camera channel(s) and applied batch defaults.`,
          importedCameraIds
        )
      } catch (caught) {
        setBatchResult(
          candidate,
          importedCameraIds.length ? "partial" : "failed",
          importedCameraIds.length
            ? `Device was imported, but one or more defaults failed: ${errorMessage(caught)}`
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
    successMessage.value =
      `Batch onboarding finished: ${successful} complete, ${partial} partial, ${review} require review.`
    batchPassword.value = ""
    for (const override of Object.values(batchOverrides.value)) {
      override.password = ""
    }
    if (changed) {
      emit("created")
    }
  } finally {
    working.value = null
  }
}
</script>

<template>
  <section class="panel onboarding-panel">
    <div class="panel__header onboarding-panel__header">
      <div>
        <p class="eyebrow">Camera onboarding</p>
        <h2>Add a camera or device</h2>
      </div>
      <button class="button button--ghost" type="button" @click="emit('close')">
        Close
      </button>
    </div>

    <div class="segmented-tabs" role="tablist" aria-label="Camera onboarding mode">
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
        Manual RTSP
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
            <strong>Find or enter the device</strong>
            <p>WS-Discovery stages candidates only. Nothing is created yet.</p>
          </div>
        </div>

        <button
          class="button button--secondary"
          type="button"
          :disabled="working !== null"
          @click="runDiscovery"
        >
          {{ working === "discover" ? "Discovering…" : "Discover ONVIF devices" }}
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
            <strong>{{ candidate.host || "Address unavailable" }}</strong>
            <span>
              {{ candidate.port ? `port ${candidate.port}` : "default port" }}
              · {{ candidate.state }}
            </span>
          </button>
        </div>
        <p
          v-else-if="discovery"
          class="field-hint onboarding-hint"
        >
          No ONVIF devices were discovered. Manual host entry remains available.
        </p>

        <div
          v-if="discovery && discovery.candidates.length"
          class="onboarding-step"
        >
          <div class="step-heading">
            <span>B</span>
            <div>
              <strong>Batch onboarding</strong>
              <p>
                Select newly discovered devices, share default credentials,
                then apply group, recording/storage and time-sync defaults.
                Existing or ambiguous identities are left for manual review.
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
                  · {{ candidate.host || "address unavailable" }}
                </span>
              </label>

              <div
                v-if="batchSelectedIds.includes(candidate.id)"
                class="form-grid"
              >
                <label class="field">
                  <span>Username override <small>optional</small></span>
                  <input
                    v-model="batchCredential(candidate.id).username"
                    autocomplete="off"
                    placeholder="Use shared username"
                  />
                </label>
                <label class="field">
                  <span>Password override <small>optional</small></span>
                  <input
                    v-model="batchCredential(candidate.id).password"
                    type="password"
                    autocomplete="new-password"
                    placeholder="Use shared password"
                  />
                </label>
              </div>

              <p
                v-if="batchResultMap.get(candidate.id)"
                class="field-hint"
              >
                <strong>
                  {{ batchResultMap.get(candidate.id)?.state }}
                </strong>
                · {{ batchResultMap.get(candidate.id)?.message }}
              </p>
            </div>
          </div>

          <div class="form-grid form-grid--three">
            <label class="field">
              <span>Shared username</span>
              <input
                v-model="batchUsername"
                autocomplete="username"
              />
            </label>
            <label class="field">
              <span>Shared password</span>
              <input
                v-model="batchPassword"
                type="password"
                autocomplete="new-password"
              />
            </label>
            <label class="field">
              <span>Name template</span>
              <input
                v-model="batchNameTemplate"
                placeholder="{name}"
              />
              <small>Supports {name} and {host}.</small>
            </label>
          </div>

          <div class="form-grid form-grid--three">
            <label class="field">
              <span>Camera group <small>optional</small></span>
              <select v-model="batchGroupId">
                <option value="">No group</option>
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
              <span>Recording default</span>
              <select v-model="batchRecordingMode">
                <option value="continuous">Continuous</option>
                <option value="events">Events only</option>
                <option value="off">Off</option>
              </select>
            </label>
            <label class="field">
              <span>Storage target</span>
              <select
                v-model="batchStorageTargetId"
                :disabled="!auth.hasPermission('storage.manage')"
              >
                <option value="">System default</option>
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
              <span>Time sync default</span>
              <select v-model="batchTimeSyncMode">
                <option value="monitor">Monitor only</option>
                <option value="manage_ntp">Manage NTP</option>
                <option value="ignore">Ignore</option>
              </select>
            </label>
          </div>

          <div class="onboarding-actions">
            <span class="field-hint">
              {{ batchSelectedIds.length }} device(s) selected
            </span>
            <button
              class="button button--primary"
              type="button"
              :disabled="!canBatchImport"
              @click="runBatchImport"
            >
              {{ working === "batch" ? "Batch importing…" : "Import selected devices" }}
            </button>
          </div>
        </div>

        <div class="form-grid form-grid--three">
          <label class="field field--grow">
            <span>Host or IP</span>
            <input
              v-model="onvifHost"
              placeholder="192.168.1.50"
              autocomplete="off"
              required
            />
          </label>
          <label class="field">
            <span>Port</span>
            <input
              v-model.number="onvifPort"
              type="number"
              min="1"
              max="65535"
              inputmode="numeric"
            />
          </label>
          <label class="field">
            <span>Username</span>
            <input v-model="onvifUsername" autocomplete="username" />
          </label>
        </div>

        <label class="field">
          <span>Password</span>
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
          {{ working === "inspect" ? "Inspecting…" : "Test & inspect" }}
        </button>
      </div>

      <div class="onboarding-step">
        <div class="step-heading">
          <span>2</span>
          <div>
            <strong>Choose stream profiles</strong>
            <p>zero-nvr validates ONVIF first; ZLM verifies actual media later.</p>
          </div>
        </div>

        <div v-if="inspection" class="inspection-card">
          <div class="device-summary">
            <strong>
              {{ inspection.device.manufacturer || "ONVIF device" }}
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
            New device identity. No existing ONVIF device matches the stable
            identity or endpoint.
          </p>
          <p
            v-else-if="inspection.identity.state === 'same_device'"
            class="notice notice--success"
            role="status"
          >
            Existing device matched by stable identity:
            <strong>
              {{ inspection.identity.matched_device_name || inspection.identity.matched_device_id }}
            </strong>.
            Import will refresh that device rather than create a duplicate.
          </p>
          <div
            v-else-if="
              inspection.identity.state ===
              'probable_match_requires_confirmation'
            "
            class="notice"
            role="status"
          >
            <strong>Identity confirmation required.</strong>
            This endpoint already belongs to
            <strong>
              {{ inspection.identity.matched_device_name || inspection.identity.matched_device_id }}
            </strong>,
            but the device did not provide a strong stable identity. zero-nvr
            will not merge it automatically.
            <label class="check-row">
              <input v-model="confirmExistingIdentity" type="checkbox" />
              <span>I confirm this is the same physical device.</span>
            </label>
          </div>
          <p
            v-else
            class="notice notice--error"
            role="alert"
          >
            <strong>Identity conflict.</strong>
            Stable identity and endpoint evidence point to different or
            duplicate existing devices. Import is disabled until the existing
            device records are resolved.
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
          Test a device to load its media profiles and capabilities.
        </div>
      </div>

      <div class="onboarding-step onboarding-step--full">
        <div class="step-heading">
          <span>3</span>
          <div>
            <strong>Import into Device Center</strong>
            <p>
              One multi-channel device can produce multiple Camera records while
              preserving stable Device identity.
            </p>
          </div>
        </div>

        <div class="form-grid form-grid--three">
          <label class="field">
            <span>Name <small>optional</small></span>
            <input v-model="onvifName" placeholder="Front entrance" />
          </label>
          <label class="field">
            <span>Location <small>optional</small></span>
            <input v-model="onvifLocation" placeholder="Ground floor" />
          </label>
          <label class="field">
            <span>Storage label <small>optional</small></span>
            <input v-model="onvifStorageLabel" placeholder="entrance" />
          </label>
        </div>

        <div class="onboarding-actions">
          <span class="field-hint">
            {{ selectedProfiles.length }} profile(s) selected
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

    <div v-else class="onboarding-grid">
      <div class="onboarding-step">
        <div class="step-heading">
          <span>1</span>
          <div>
            <strong>Describe the camera</strong>
            <p>Manual RTSP is first-class when ONVIF is unavailable.</p>
          </div>
        </div>

        <label class="field">
          <span>Camera name</span>
          <input v-model="manualName" placeholder="Garage" required />
        </label>

        <div class="form-grid">
          <label class="field">
            <span>Location <small>optional</small></span>
            <input v-model="manualLocation" />
          </label>
          <label class="field">
            <span>Storage label <small>optional</small></span>
            <input v-model="manualStorageLabel" />
          </label>
        </div>
      </div>

      <div class="onboarding-step">
        <div class="step-heading">
          <span>2</span>
          <div>
            <strong>Configure streams</strong>
            <p>ZLMediaKit performs the actual source pull and probe.</p>
          </div>
        </div>

        <label class="field">
          <span>Primary stream name</span>
          <input v-model="primaryName" required />
        </label>
        <label class="field">
          <span>Primary RTSP URL</span>
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
          <span>Add a secondary / preview stream</span>
        </label>

        <template v-if="secondaryEnabled">
          <label class="field">
            <span>Secondary stream name</span>
            <input v-model="secondaryName" required />
          </label>
          <label class="field">
            <span>Secondary RTSP URL</span>
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
            <strong>Verify before creating</strong>
            <p>
              Testing opens only temporary ZLM proxies and does not persist a Camera.
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
              Video:
              <strong>{{ stream.video?.codec || "not detected" }}</strong>
              <template v-if="stream.video?.width && stream.video?.height">
                · {{ stream.video.width }}×{{ stream.video.height }}
              </template>
            </p>
            <p>
              Audio:
              <strong>{{ stream.audio?.codec || "none" }}</strong>
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
            {{ working === "test" ? "Testing…" : "Test streams" }}
          </button>
          <button
            class="button button--primary"
            type="button"
            :disabled="!canCreateManual"
            @click="createRtsp"
          >
            {{ working === "create" ? "Creating…" : "Create camera" }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
