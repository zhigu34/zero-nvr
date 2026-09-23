<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref
} from "vue"

import {
  listCameras,
  type CameraSummary
} from "../api/cameras"
import { errorMessage } from "../api/client"
import {
  createRetentionPolicy,
  createStorageTarget,
  deleteRetentionPolicy,
  deleteStorageTarget,
  listRetentionPolicies,
  listStorageTargets,
  switchRecordingTarget,
  testStorageTarget,
  updateRetentionPolicy,
  updateStorageTarget,
  type RetentionPolicy,
  type RetentionPolicyCreate,
  type StorageTarget
} from "../api/storage"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type StorageTab = "targets" | "retention"
type TargetFormType = "local" | "rclone"
type ArchiveProvider = "custom" | "openlist_webdav"

const auth = useAuthStore()
const tab = ref<StorageTab>("targets")
const targets = ref<StorageTarget[]>([])
const policies = ref<RetentionPolicy[]>([])
const cameras = ref<CameraSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const targetPanelOpen = ref(false)
const policyPanelOpen = ref(false)
const editingTarget = ref<StorageTarget | null>(null)
const editingPolicy = ref<RetentionPolicy | null>(null)
const targetSaving = ref(false)
const policySaving = ref(false)
const testingTargetId = ref<string | null>(null)
const testResults = ref<Record<string, string>>({})

const switchSource = ref<StorageTarget | null>(null)
const switchDestinationId = ref("")
const switchSaving = ref(false)

const targetForm = reactive({
  type: "local" as TargetFormType,
  name: "",
  path: "/recordings",
  defaultRecording: false,
  warningPercent: 80,
  highPercent: 85,
  criticalPercent: 95,
  remote: "",
  basePath: "zero-nvr",
  defaultArchive: false,
  archiveProvider: "custom" as ArchiveProvider,
  rcloneConfig: "",
  openlistUrl: "",
  openlistUsername: "",
  openlistPassword: ""
})

const policyForm = reactive({
  name: "Default retention",
  scopeType: "GLOBAL" as "GLOBAL" | "CAMERA" | "CAMERA_GROUP",
  scopeId: "",
  ordinaryDays: 14,
  eventDays: 30,
  manualDays: 90,
  mode: "BEST_EFFORT" as "BEST_EFFORT" | "HARD",
  requireArchive: true,
  enabled: true
})

const localTargets = computed(() =>
  targets.value.filter(
    (item) =>
      item.type === "local" &&
      item.role === "recording"
  )
)

const archiveTargets = computed(() =>
  targets.value.filter(
    (item) =>
      item.type === "rclone" &&
      item.role === "archive"
  )
)

const enabledPolicyCount = computed(() =>
  policies.value.filter((item) => item.enabled).length
)


const switchDestinations = computed(() =>
  localTargets.value.filter(
    (item) =>
      item.enabled &&
      item.id !== switchSource.value?.id
  )
)

function formatBytes(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—"
  const units = ["B", "KB", "MB", "GB", "TB", "PB"]
  let index = 0
  let amount = value
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  const digits = amount >= 100 || index === 0 ? 0 : amount >= 10 ? 1 : 2
  return `${amount.toFixed(digits)} ${units[index]}`
}

function targetDetail(target: StorageTarget): string {
  if (target.type === "local") {
    const path = target.config.path
    return typeof path === "string" ? path : "Local path"
  }

  const remote = target.config.remote
  const basePath = target.config.base_path
  const remoteText = typeof remote === "string" ? remote : "rclone"
  const baseText =
    typeof basePath === "string" && basePath
      ? `:${basePath}`
      : ":"
  return `${remoteText}${baseText}`
}

function targetWatermarks(target: StorageTarget): string | null {
  if (target.type !== "local") return null
  const warning =
    typeof target.config.warning_used_percent === "number"
      ? target.config.warning_used_percent
      : 80
  const high =
    typeof target.config.high_used_percent === "number"
      ? target.config.high_used_percent
      : 85
  const critical =
    typeof target.config.critical_used_percent === "number"
      ? target.config.critical_used_percent
      : 95
  return `Watermarks ${warning}% / ${high}% / ${critical}%`
}

function targetIsDefault(target: StorageTarget): boolean {
  return target.type === "local"
    ? target.config.default_recording === true
    : target.config.default_archive === true
}

function cameraName(cameraId: string | null): string {
  if (!cameraId) return "All cameras"
  return cameras.value.find((item) => item.id === cameraId)?.name ??
    "Unknown camera"
}

function scopeLabel(policy: RetentionPolicy): string {
  if (policy.scope_type === "GLOBAL") return "All cameras"
  if (policy.scope_type === "CAMERA") return cameraName(policy.scope_id)
  return "Camera group"
}

async function refresh(): Promise<void> {
  if (!auth.hasPermission("storage.manage")) return

  loading.value = true
  error.value = null
  try {
    const [targetItems, retentionItems, cameraItems] =
      await Promise.all([
        listStorageTargets(),
        listRetentionPolicies(),
        auth.hasPermission("camera.view")
          ? listCameras()
          : Promise.resolve([])
      ])
    targets.value = targetItems
    policies.value = retentionItems
    cameras.value = cameraItems
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function resetTargetForm(type: TargetFormType = "local"): void {
  targetForm.type = type
  targetForm.name = ""
  targetForm.path = "/recordings"
  targetForm.defaultRecording = false
  targetForm.warningPercent = 80
  targetForm.highPercent = 85
  targetForm.criticalPercent = 95
  targetForm.remote = ""
  targetForm.basePath = "zero-nvr"
  targetForm.defaultArchive = false
  targetForm.archiveProvider = "custom"
  targetForm.rcloneConfig = ""
  targetForm.openlistUrl = ""
  targetForm.openlistUsername = ""
  targetForm.openlistPassword = ""
}

function openTargetPanel(type: TargetFormType = "local"): void {
  editingTarget.value = null
  switchSource.value = null
  resetTargetForm(type)
  targetPanelOpen.value = true
  policyPanelOpen.value = false
  notice.value = null
}

function openEditTarget(target: StorageTarget): void {
  switchSource.value = null
  editingTarget.value = target
  targetForm.type = target.type
  targetForm.name = target.name
  targetForm.rcloneConfig = ""
  targetForm.openlistUrl = ""
  targetForm.openlistUsername = ""
  targetForm.openlistPassword = ""

  if (target.type === "local") {
    targetForm.path =
      typeof target.config.path === "string"
        ? target.config.path
        : "/recordings"
    targetForm.defaultRecording =
      target.config.default_recording === true
    targetForm.warningPercent =
      typeof target.config.warning_used_percent === "number"
        ? target.config.warning_used_percent
        : 80
    targetForm.highPercent =
      typeof target.config.high_used_percent === "number"
        ? target.config.high_used_percent
        : 85
    targetForm.criticalPercent =
      typeof target.config.critical_used_percent === "number"
        ? target.config.critical_used_percent
        : 95
    targetForm.remote = ""
    targetForm.basePath = "zero-nvr"
    targetForm.defaultArchive = false
  } else {
    targetForm.path = "/recordings"
    targetForm.defaultRecording = false
    targetForm.remote =
      typeof target.config.remote === "string"
        ? target.config.remote
        : ""
    targetForm.basePath =
      typeof target.config.base_path === "string"
        ? target.config.base_path
        : "zero-nvr"
    targetForm.defaultArchive =
      target.config.default_archive === true
    targetForm.archiveProvider =
      target.config.provider === "openlist_webdav"
        ? "openlist_webdav"
        : "custom"
  }

  targetPanelOpen.value = true
  policyPanelOpen.value = false
  notice.value = null
}

function handleArchiveProviderChange(): void {
  if (
    targetForm.archiveProvider === "openlist_webdav" &&
    !targetForm.remote.trim()
  ) {
    targetForm.remote = "openlist"
  }
}

function openListCredentials(
  required: boolean
): {
  url: string
  username: string
  password: string
} | null {
  const url = targetForm.openlistUrl.trim()
  const username = targetForm.openlistUsername.trim()
  const password = targetForm.openlistPassword
  const hasAny = Boolean(url || username || password)

  if (!required && !hasAny) return null
  if (!url || !username || !password) {
    throw new Error(
      "OpenList WebDAV URL, username, and password are all required when replacing credentials."
    )
  }
  return { url, username, password }
}

function openSwitchPanel(target: StorageTarget): void {
  switchSource.value = target
  switchDestinationId.value =
    switchDestinations.value[0]?.id ?? ""
  targetPanelOpen.value = false
  editingTarget.value = null
  policyPanelOpen.value = false
  notice.value = null
  error.value = null
}

async function runRecordingTargetSwitch(): Promise<void> {
  const source = switchSource.value
  const destination = switchDestinations.value.find(
    (item) => item.id === switchDestinationId.value
  )
  if (!source || !destination) return

  if (
    !window.confirm(
      `Switch future recording writes from "${source.name}" to "${destination.name}"? Historical footage remains bound to "${source.name}" and is not moved.`
    )
  ) {
    return
  }

  switchSaving.value = true
  error.value = null
  try {
    const result = await switchRecordingTarget(
      source.id,
      destination.id
    )
    notice.value =
      `Recording writes switched to ${destination.name}. ` +
      `${result.affected_camera_ids.length} camera runtime(s) queued for recorder reconfiguration; historical footage remains on ${source.name}.`
    switchSource.value = null
    switchDestinationId.value = ""
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    switchSaving.value = false
  }
}

async function saveTarget(): Promise<void> {
  targetSaving.value = true
  error.value = null

  try {
    const name = targetForm.name.trim()

    if (editingTarget.value) {
      if (targetForm.type === "local") {
        await updateStorageTarget(editingTarget.value.id, {
          name,
          config: {
            path: targetForm.path.trim(),
            default_recording: targetForm.defaultRecording,
            warning_used_percent: Number(targetForm.warningPercent),
            high_used_percent: Number(targetForm.highPercent),
            critical_used_percent: Number(targetForm.criticalPercent)
          }
        })
      } else {
        const changes: Record<string, unknown> = {
          name,
          config: {
            remote: targetForm.remote.trim(),
            base_path: targetForm.basePath.trim(),
            default_archive: targetForm.defaultArchive,
            provider: targetForm.archiveProvider
          }
        }
        if (
          targetForm.archiveProvider ===
          "openlist_webdav"
        ) {
          const credentials = openListCredentials(false)
          changes.rclone_config_action = credentials
            ? "replace"
            : "keep"
          if (credentials) {
            changes.openlist_webdav = credentials
          }
        } else {
          changes.rclone_config_action = (
            targetForm.rcloneConfig.trim()
              ? "replace"
              : "keep"
          )
          if (targetForm.rcloneConfig.trim()) {
            changes.rclone_config =
              targetForm.rcloneConfig
          }
        }
        await updateStorageTarget(
          editingTarget.value.id,
          changes
        )
      }
      notice.value = "Storage target updated."
    } else if (targetForm.type === "local") {
      await createStorageTarget({
        type: "local",
        role: "recording",
        name,
        enabled: true,
        config: {
          path: targetForm.path.trim(),
          default_recording: targetForm.defaultRecording,
          warning_used_percent: Number(targetForm.warningPercent),
          high_used_percent: Number(targetForm.highPercent),
          critical_used_percent: Number(targetForm.criticalPercent)
        }
      })
      notice.value = "Storage target created."
    } else {
      const config = {
        remote: targetForm.remote.trim(),
        base_path: targetForm.basePath.trim(),
        default_archive: targetForm.defaultArchive,
        provider: targetForm.archiveProvider
      }
      if (
        targetForm.archiveProvider ===
        "openlist_webdav"
      ) {
        const credentials = openListCredentials(true)
        if (!credentials) {
          throw new Error(
            "OpenList WebDAV credentials are required."
          )
        }
        await createStorageTarget({
          type: "rclone",
          role: "archive",
          name,
          enabled: true,
          config,
          openlist_webdav: credentials
        })
      } else {
        await createStorageTarget({
          type: "rclone",
          role: "archive",
          name,
          enabled: true,
          config,
          rclone_config: targetForm.rcloneConfig
        })
      }
      notice.value = "Storage target created."
    }

    editingTarget.value = null
    targetPanelOpen.value = false
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    targetSaving.value = false
  }
}

async function runTargetTest(target: StorageTarget): Promise<void> {
  testingTargetId.value = target.id
  error.value = null
  try {
    const result = await testStorageTarget(target.id)
    testResults.value = {
      ...testResults.value,
      [target.id]:
        result.used_percent !== null &&
        result.capacity_level
          ? `${result.capacity_level.toUpperCase()} · ${result.used_percent.toFixed(
              1
            )}% used · ${formatBytes(result.free_bytes)} free`
          : result.free_bytes !== null
            ? `Ready · ${formatBytes(result.free_bytes)} free`
            : "Ready · read/write/delete verified"
    }
  } catch (caught) {
    error.value = errorMessage(caught)
    testResults.value = {
      ...testResults.value,
      [target.id]: "Test failed"
    }
  } finally {
    testingTargetId.value = null
  }
}

async function toggleTarget(target: StorageTarget): Promise<void> {
  try {
    await updateStorageTarget(target.id, {
      enabled: !target.enabled
    })
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function removeTarget(target: StorageTarget): Promise<void> {
  if (!window.confirm(`Delete storage target "${target.name}"?`)) {
    return
  }
  try {
    await deleteStorageTarget(target.id)
    notice.value = "Storage target deleted."
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function resetPolicyForm(): void {
  policyForm.name = "Default retention"
  policyForm.scopeType = "GLOBAL"
  policyForm.scopeId = ""
  policyForm.ordinaryDays = 14
  policyForm.eventDays = 30
  policyForm.manualDays = 90
  policyForm.mode = "BEST_EFFORT"
  policyForm.requireArchive = true
  policyForm.enabled = true
}

function openPolicyPanel(): void {
  switchSource.value = null
  editingPolicy.value = null
  resetPolicyForm()
  policyPanelOpen.value = true
  targetPanelOpen.value = false
  notice.value = null
}

function openEditPolicy(policy: RetentionPolicy): void {
  editingPolicy.value = policy
  policyForm.name = policy.name
  policyForm.scopeType = policy.scope_type
  policyForm.scopeId = policy.scope_id ?? ""
  policyForm.ordinaryDays = policy.ordinary_keep_days
  policyForm.eventDays = policy.event_keep_days
  policyForm.manualDays = policy.manual_keep_days
  policyForm.mode = policy.mode
  policyForm.requireArchive =
    policy.require_archive_before_delete
  policyForm.enabled = policy.enabled
  policyPanelOpen.value = true
  targetPanelOpen.value = false
  notice.value = null
}

async function savePolicy(): Promise<void> {
  policySaving.value = true
  error.value = null
  const body: RetentionPolicyCreate = {
    name: policyForm.name.trim(),
    scope_type: policyForm.scopeType,
    scope_id:
      policyForm.scopeType === "CAMERA" ||
      policyForm.scopeType === "CAMERA_GROUP"
        ? policyForm.scopeId || null
        : null,
    ordinary_keep_days: Number(policyForm.ordinaryDays),
    event_keep_days: Number(policyForm.eventDays),
    manual_keep_days: Number(policyForm.manualDays),
    mode: policyForm.mode,
    require_archive_before_delete: policyForm.requireArchive,
    enabled: policyForm.enabled
  }

  try {
    if (editingPolicy.value) {
      await updateRetentionPolicy(
        editingPolicy.value.id,
        body
      )
      notice.value = "Retention policy updated."
    } else {
      await createRetentionPolicy(body)
      notice.value = "Retention policy created."
    }
    editingPolicy.value = null
    policyPanelOpen.value = false
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    policySaving.value = false
  }
}

async function togglePolicy(policy: RetentionPolicy): Promise<void> {
  try {
    await updateRetentionPolicy(policy.id, {
      enabled: !policy.enabled
    })
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function removePolicy(policy: RetentionPolicy): Promise<void> {
  if (!window.confirm(`Delete retention policy "${policy.name}"?`)) {
    return
  }
  try {
    await deleteRetentionPolicy(policy.id)
    notice.value = "Retention policy deleted."
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function handleRefreshEvent(): void {
  void refresh()
}

onMounted(() => {
  void refresh()
  window.addEventListener("zero-nvr:refresh", handleRefreshEvent)
})

onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", handleRefreshEvent)
})
</script>

<template>
  <section class="storage-workspace">
    <header class="storage-header">
      <div>
        <strong>Storage</strong>
        <span>
          Local recording, remote archive and retention lifecycle.
        </span>
      </div>

      <button
        class="button button--ghost"
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        <UiIcon name="refresh" :size="15" />
        Refresh
      </button>
    </header>

    <div class="storage-summary">
      <article>
        <UiIcon name="drive" :size="19" />
        <div>
          <span>Recording targets</span>
          <strong>{{ localTargets.length }}</strong>
        </div>
      </article>
      <article>
        <UiIcon name="cloud" :size="19" />
        <div>
          <span>Archive targets</span>
          <strong>{{ archiveTargets.length }}</strong>
        </div>
      </article>
      <article>
        <UiIcon name="shield" :size="19" />
        <div>
          <span>Active retention policies</span>
          <strong>{{ enabledPolicyCount }}</strong>
        </div>
      </article>
    </div>

    <div
      v-if="error"
      class="events-error"
    >
      <UiIcon name="warning" :size="16" />
      <span>{{ error }}</span>
    </div>

    <div
      v-if="notice"
      class="storage-notice"
    >
      <UiIcon name="check" :size="15" />
      <span>{{ notice }}</span>
    </div>

    <div class="storage-tabs">
      <button
        type="button"
        :class="{ 'storage-tab--active': tab === 'targets' }"
        @click="tab = 'targets'"
      >
        Storage targets
      </button>
      <button
        type="button"
        :class="{ 'storage-tab--active': tab === 'retention' }"
        @click="tab = 'retention'"
      >
        Retention
      </button>
    </div>

    <div class="storage-layout">
      <div class="storage-main">
        <template v-if="tab === 'targets'">
          <div class="storage-section-header">
            <div>
              <strong>Storage targets</strong>
              <span>
                Cameras always record locally first; archive copies are asynchronous.
              </span>
            </div>
            <div class="storage-section-actions">
              <button
                class="button button--ghost"
                type="button"
                @click="openTargetPanel('rclone')"
              >
                <UiIcon name="cloud" :size="14" />
                Add archive
              </button>
              <button
                class="button button--primary"
                type="button"
                @click="openTargetPanel('local')"
              >
                <UiIcon name="plus" :size="14" />
                Add local
              </button>
            </div>
          </div>

          <div v-if="!targets.length && !loading" class="storage-empty">
            <UiIcon name="storage" :size="28" />
            <strong>No storage targets</strong>
            <span>Add a local recording target to start storing footage.</span>
          </div>

          <div v-else class="storage-target-list">
            <article
              v-for="target in targets"
              :key="target.id"
              class="storage-target-card"
            >
              <div class="storage-target-card__icon">
                <UiIcon
                  :name="target.type === 'local' ? 'drive' : 'cloud'"
                  :size="20"
                />
              </div>

              <div class="storage-target-card__main">
                <div class="storage-target-card__title">
                  <strong>{{ target.name }}</strong>
                  <span
                    class="status-pill"
                    :class="{
                      'status-pill--ok': target.enabled,
                      'status-pill--muted': !target.enabled
                    }"
                  >
                    {{ target.enabled ? "Enabled" : "Disabled" }}
                  </span>
                  <span
                    v-if="targetIsDefault(target)"
                    class="status-pill"
                  >
                    Default
                  </span>
                </div>
                <span class="storage-target-card__path">
                  {{ targetDetail(target) }}
                </span>
                <span
                  v-if="targetWatermarks(target)"
                  class="storage-target-card__test"
                >
                  {{ targetWatermarks(target) }}
                </span>
                <span
                  v-if="testResults[target.id]"
                  class="storage-target-card__test"
                >
                  {{ testResults[target.id] }}
                </span>
                <span
                  v-else-if="target.type === 'rclone'"
                  class="storage-target-card__test"
                >
                  {{
                    target.credentials_configured
                      ? "Credentials configured"
                      : "Credentials missing"
                  }}
                </span>
              </div>

              <div class="storage-target-card__actions">
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  :disabled="testingTargetId === target.id"
                  @click="runTargetTest(target)"
                >
                  <UiIcon name="activity" :size="14" />
                  {{
                    testingTargetId === target.id
                      ? "Testing…"
                      : "Test"
                  }}
                </button>
                <button
                  v-if="
                    target.type === 'local' &&
                    target.role === 'recording'
                  "
                  class="button button--ghost button--compact"
                  type="button"
                  :disabled="
                    !localTargets.some(
                      (item) =>
                        item.enabled &&
                        item.id !== target.id
                    )
                  "
                  title="Switch future recording writes to another local target"
                  @click="openSwitchPanel(target)"
                >
                  <UiIcon name="next" :size="14" />
                  Switch writes
                </button>
                <button
                  class="icon-button"
                  type="button"
                  title="Edit target"
                  @click="openEditTarget(target)"
                >
                  <UiIcon name="settings" :size="15" />
                </button>
                <button
                  class="icon-button"
                  type="button"
                  :title="target.enabled ? 'Disable' : 'Enable'"
                  @click="toggleTarget(target)"
                >
                  <UiIcon
                    :name="target.enabled ? 'pause' : 'play'"
                    :size="15"
                  />
                </button>
                <button
                  class="icon-button icon-button--danger"
                  type="button"
                  title="Delete target"
                  @click="removeTarget(target)"
                >
                  <UiIcon name="trash" :size="15" />
                </button>
              </div>
            </article>
          </div>
        </template>

        <template v-else>
          <div class="storage-section-header">
            <div>
              <strong>Retention policies</strong>
              <span>
                Preserve event/manual footage longer while ordinary footage rotates.
              </span>
            </div>
            <button
              class="button button--primary"
              type="button"
              @click="openPolicyPanel"
            >
              <UiIcon name="plus" :size="14" />
              Add policy
            </button>
          </div>

          <div v-if="!policies.length && !loading" class="storage-empty">
            <UiIcon name="shield" :size="28" />
            <strong>No retention policies</strong>
            <span>Create a global policy or override a single camera.</span>
          </div>

          <div v-else class="retention-table-wrap">
            <table class="retention-table">
              <thead>
                <tr>
                  <th>Policy</th>
                  <th>Scope</th>
                  <th>Ordinary</th>
                  <th>Event</th>
                  <th>Manual</th>
                  <th>Archive</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="policy in policies"
                  :key="policy.id"
                >
                  <td>
                    <strong>{{ policy.name }}</strong>
                    <small>{{ policy.mode === "HARD" ? "Hard limit" : "Best effort" }}</small>
                  </td>
                  <td>{{ scopeLabel(policy) }}</td>
                  <td>{{ policy.ordinary_keep_days }}d</td>
                  <td>{{ policy.event_keep_days }}d</td>
                  <td>{{ policy.manual_keep_days }}d</td>
                  <td>
                    {{
                      policy.require_archive_before_delete
                        ? "Required"
                        : "Optional"
                    }}
                  </td>
                  <td>
                    <span
                      class="status-pill"
                      :class="{
                        'status-pill--ok': policy.enabled,
                        'status-pill--muted': !policy.enabled
                      }"
                    >
                      {{ policy.enabled ? "Enabled" : "Disabled" }}
                    </span>
                  </td>
                  <td class="retention-table__actions">
                    <button
                      class="icon-button"
                      type="button"
                      title="Edit policy"
                      @click="openEditPolicy(policy)"
                    >
                      <UiIcon name="settings" :size="14" />
                    </button>
                    <button
                      class="icon-button"
                      type="button"
                      :title="policy.enabled ? 'Disable' : 'Enable'"
                      @click="togglePolicy(policy)"
                    >
                      <UiIcon
                        :name="policy.enabled ? 'pause' : 'play'"
                        :size="14"
                      />
                    </button>
                    <button
                      class="icon-button icon-button--danger"
                      type="button"
                      title="Delete policy"
                      @click="removePolicy(policy)"
                    >
                      <UiIcon name="trash" :size="14" />
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>

      <aside
        v-if="switchSource"
        class="storage-editor"
      >
        <header class="storage-editor__header">
          <div>
            <strong>Switch recording writes</strong>
            <span>Safe local target routing change</span>
          </div>
          <button
            class="icon-button"
            type="button"
            title="Close"
            @click="switchSource = null; switchDestinationId = ''"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <form
          class="storage-editor__form"
          @submit.prevent="runRecordingTargetSwitch"
        >
          <div class="storage-switch-summary">
            <span>Current target</span>
            <strong>{{ switchSource.name }}</strong>
            <small>{{ targetDetail(switchSource) }}</small>
          </div>

          <label>
            <span>New recording target</span>
            <select
              v-model="switchDestinationId"
              required
            >
              <option value="" disabled>
                Select a local target
              </option>
              <option
                v-for="target in switchDestinations"
                :key="target.id"
                :value="target.id"
              >
                {{ target.name }} · {{ targetDetail(target) }}
              </option>
            </select>
          </label>

          <div class="storage-switch-note">
            <UiIcon name="shield" :size="15" />
            <span>
              Only future write routing changes. Existing RecordingLocations
              stay attached to the current target, so playback and retention
              continue using their original path. The recorder is reconfigured
              at the switch boundary without cloud hot-recording fallback.
            </span>
          </div>

          <div class="storage-editor__actions">
            <button
              class="button button--ghost"
              type="button"
              @click="switchSource = null; switchDestinationId = ''"
            >
              Cancel
            </button>
            <button
              class="button button--primary"
              type="submit"
              :disabled="
                switchSaving ||
                !switchDestinationId
              "
            >
              {{ switchSaving ? "Switching…" : "Switch writes" }}
            </button>
          </div>
        </form>
      </aside>

      <aside
        v-if="targetPanelOpen"
        class="storage-editor"
      >
        <header class="storage-editor__header">
          <div>
            <strong>
              {{
                editingTarget
                  ? targetForm.type === "local"
                    ? "Edit local storage"
                    : "Edit archive storage"
                  : targetForm.type === "local"
                    ? "Add local storage"
                    : "Add archive storage"
              }}
            </strong>
            <span>
              {{
                targetForm.type === "local"
                  ? "Recording destination"
                  : "rclone remote archive"
              }}
            </span>
          </div>
          <button
            class="icon-button"
            type="button"
            title="Close"
            @click="targetPanelOpen = false; editingTarget = null"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <form class="storage-editor__form" @submit.prevent="saveTarget">
          <label>
            <span>Name</span>
            <input
              v-model="targetForm.name"
              required
              maxlength="128"
              placeholder="Primary recordings"
            />
          </label>

          <template v-if="targetForm.type === 'local'">
            <label>
              <span>Container path</span>
              <input
                v-model="targetForm.path"
                required
                :readonly="Boolean(editingTarget)"
                placeholder="/recordings"
              />
              <small v-if="editingTarget">
                The recording root is the StorageTarget identity. Create a
                second local target and use Switch writes to change future
                recording placement without breaking historical locations.
              </small>
            </label>
            <div class="storage-watermarks-grid">
              <label>
                <span>Warning %</span>
                <input
                  v-model.number="targetForm.warningPercent"
                  type="number"
                  min="1"
                  max="97"
                  required
                />
              </label>
              <label>
                <span>High %</span>
                <input
                  v-model.number="targetForm.highPercent"
                  type="number"
                  min="2"
                  max="98"
                  required
                />
              </label>
              <label>
                <span>Critical %</span>
                <input
                  v-model.number="targetForm.criticalPercent"
                  type="number"
                  min="3"
                  max="99"
                  required
                />
              </label>
            </div>
            <small>
              High/critical enables pressure retention; critical blocks new
              recording writes until space is reclaimed.
            </small>
            <label class="storage-check">
              <input
                v-model="targetForm.defaultRecording"
                type="checkbox"
              />
              <span>Use as default recording target</span>
            </label>
          </template>

          <template v-else>
            <label>
              <span>Archive provider</span>
              <select
                v-model="targetForm.archiveProvider"
                :disabled="Boolean(editingTarget)"
                @change="handleArchiveProviderChange"
              >
                <option value="custom">
                  Generic rclone config
                </option>
                <option value="openlist_webdav">
                  OpenList (WebDAV)
                </option>
              </select>
              <small v-if="editingTarget">
                Provider type is fixed after creation. Create another
                archive target to change provider type.
              </small>
            </label>
            <label>
              <span>rclone remote name</span>
              <input
                v-model="targetForm.remote"
                required
                :readonly="
                  Boolean(editingTarget) &&
                  targetForm.archiveProvider ===
                    'openlist_webdav'
                "
                placeholder="archive"
              />
            </label>
            <label>
              <span>Base path</span>
              <input
                v-model="targetForm.basePath"
                placeholder="zero-nvr"
              />
            </label>
            <template
              v-if="
                targetForm.archiveProvider ===
                'openlist_webdav'
              "
            >
              <label>
                <span>OpenList WebDAV URL</span>
                <input
                  v-model="targetForm.openlistUrl"
                  :required="!editingTarget"
                  placeholder="https://openlist.example.com/dav/"
                  autocomplete="off"
                />
                <small>
                  Use the OpenList WebDAV endpoint, normally ending in
                  /dav/. HTTPS is recommended outside trusted networks.
                </small>
              </label>
              <label>
                <span>OpenList username</span>
                <input
                  v-model="targetForm.openlistUsername"
                  :required="!editingTarget"
                  autocomplete="off"
                />
              </label>
              <label>
                <span>OpenList password</span>
                <input
                  v-model="targetForm.openlistPassword"
                  :required="!editingTarget"
                  type="password"
                  autocomplete="new-password"
                />
                <small>
                  {{
                    editingTarget
                      ? "Leave all three OpenList credential fields blank to keep the existing encrypted credentials."
                      : "The backend obscures the password for rclone, then stores the complete rclone config encrypted."
                  }}
                </small>
              </label>
            </template>
            <label v-else>
              <span>rclone config</span>
              <textarea
                v-model="targetForm.rcloneConfig"
                :required="!editingTarget"
                rows="9"
                spellcheck="false"
                placeholder="[archive]&#10;type = s3&#10;..."
              />
              <small>
                {{
                  editingTarget
                    ? "Leave blank to keep the existing encrypted credentials; enter a new config only to replace them."
                    : "Stored encrypted; never returned to the browser."
                }}
              </small>
            </label>
            <label class="storage-check">
              <input
                v-model="targetForm.defaultArchive"
                type="checkbox"
              />
              <span>Use as default archive target</span>
            </label>
          </template>

          <div class="storage-editor__actions">
            <button
              class="button button--ghost"
              type="button"
              @click="targetPanelOpen = false; editingTarget = null"
            >
              Cancel
            </button>
            <button
              class="button button--primary"
              type="submit"
              :disabled="targetSaving"
            >
              {{
                targetSaving
                  ? "Saving…"
                  : editingTarget
                    ? "Save target"
                    : "Create target"
              }}
            </button>
          </div>
        </form>
      </aside>

      <aside
        v-if="policyPanelOpen"
        class="storage-editor"
      >
        <header class="storage-editor__header">
          <div>
            <strong>
              {{
                editingPolicy
                  ? "Edit retention policy"
                  : "Add retention policy"
              }}
            </strong>
            <span>Recording lifecycle rules</span>
          </div>
          <button
            class="icon-button"
            type="button"
            title="Close"
            @click="policyPanelOpen = false; editingPolicy = null"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <form class="storage-editor__form" @submit.prevent="savePolicy">
          <label>
            <span>Name</span>
            <input
              v-model="policyForm.name"
              required
              maxlength="128"
            />
          </label>

          <label>
            <span>Scope</span>
            <select v-model="policyForm.scopeType">
              <option value="GLOBAL">All cameras</option>
              <option value="CAMERA">Single camera</option>
              <option
                v-if="
                  editingPolicy?.scope_type === 'CAMERA_GROUP'
                "
                value="CAMERA_GROUP"
              >
                Existing camera group
              </option>
            </select>
          </label>

          <label v-if="policyForm.scopeType === 'CAMERA'">
            <span>Camera</span>
            <select v-model="policyForm.scopeId" required>
              <option value="" disabled>Select a camera</option>
              <option
                v-for="camera in cameras"
                :key="camera.id"
                :value="camera.id"
              >
                {{ camera.name }}
              </option>
            </select>
          </label>

          <label
            v-if="policyForm.scopeType === 'CAMERA_GROUP'"
          >
            <span>Camera group</span>
            <input
              :value="policyForm.scopeId"
              readonly
            />
            <small>
              Existing group scope is preserved. Group selection is managed
              from Cameras → Groups.
            </small>
          </label>

          <div class="retention-days-grid">
            <label>
              <span>Ordinary days</span>
              <input
                v-model.number="policyForm.ordinaryDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
            <label>
              <span>Event days</span>
              <input
                v-model.number="policyForm.eventDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
            <label>
              <span>Manual days</span>
              <input
                v-model.number="policyForm.manualDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
          </div>

          <label>
            <span>Policy mode</span>
            <select v-model="policyForm.mode">
              <option value="BEST_EFFORT">Best effort</option>
              <option value="HARD">Hard limit</option>
            </select>
          </label>

          <label class="storage-check">
            <input
              v-model="policyForm.requireArchive"
              type="checkbox"
            />
            <span>Require archive before local deletion</span>
          </label>

          <div class="storage-editor__actions">
            <button
              class="button button--ghost"
              type="button"
              @click="policyPanelOpen = false; editingPolicy = null"
            >
              Cancel
            </button>
            <button
              class="button button--primary"
              type="submit"
              :disabled="policySaving"
            >
              {{
                policySaving
                  ? "Saving…"
                  : editingPolicy
                    ? "Save policy"
                    : "Create policy"
              }}
            </button>
          </div>
        </form>
      </aside>
    </div>
  </section>
</template>
