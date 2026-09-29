<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref
} from "vue"
import { useI18n } from "vue-i18n"

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
  type StorageTarget,
  type StorageTargetTest
} from "../api/storage"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type StorageTab = "targets" | "retention"
type TargetFormType = "local" | "rclone"
type ArchiveProvider = "custom" | "openlist_webdav"

const auth = useAuthStore()
const { t, te } = useI18n({ useScope: "global" })
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
const targetMetrics = ref<Record<string, StorageTargetTest>>({})

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
  name: t("storage.defaultRetention"),
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

function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—"
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
    return typeof path === "string" ? path : t("storage.localPath")
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

function getWatermarkPercent(target: StorageTarget, type: "warning" | "high" | "critical"): number {
  if (target.type !== "local") {
    return type === "warning" ? 80 : type === "high" ? 85 : 95
  }
  if (type === "warning") {
    return typeof target.config.warning_used_percent === "number"
      ? target.config.warning_used_percent
      : 80
  }
  if (type === "high") {
    return typeof target.config.high_used_percent === "number"
      ? target.config.high_used_percent
      : 85
  }
  return typeof target.config.critical_used_percent === "number"
    ? target.config.critical_used_percent
    : 95
}

function targetWatermarks(target: StorageTarget): string | null {
  if (target.type !== "local") return null
  const warning = getWatermarkPercent(target, "warning")
  const high = getWatermarkPercent(target, "high")
  const critical = getWatermarkPercent(target, "critical")
  return t("storage.watermarks", { warning, high, critical })
}

function getLocalTargetStatusBadge(target: StorageTarget): { text: string; badgeClass: string } {
  if (!target.enabled) {
    return { text: t("storage.disabled"), badgeClass: "status-badge--disabled" }
  }
  const metric = targetMetrics.value[target.id]
  if (!metric || metric.used_percent === null || metric.used_percent === undefined) {
    return { text: "在线就绪", badgeClass: "status-badge--normal" }
  }
  const percent = metric.used_percent.toFixed(0)
  if (metric.capacity_level === "critical") {
    return { text: `极值熔断 · ${percent}% 负载`, badgeClass: "status-badge--critical" }
  }
  if (metric.capacity_level === "high") {
    return { text: `高位清理 · ${percent}% 负载`, badgeClass: "status-badge--high" }
  }
  if (metric.capacity_level === "warning") {
    return { text: `警戒水位 · ${percent}% 负载`, badgeClass: "status-badge--warning" }
  }
  return { text: `健康 · ${percent}% 负载`, badgeClass: "status-badge--normal" }
}

function getLocalTargetBarColor(target: StorageTarget): string {
  const metric = targetMetrics.value[target.id]
  if (!metric) return "#2563eb"
  if (metric.capacity_level === "critical") return "#dc2626"
  if (metric.capacity_level === "high") return "#f87171"
  if (metric.capacity_level === "warning") return "#fbbf24"
  return "#2563eb"
}

function capacityLevelLabel(value: string): string {
  const key = `storage.capacity.${value.toLowerCase()}`
  return te(key) ? t(key) : value.toUpperCase()
}

function targetIsDefault(target: StorageTarget): boolean {
  return target.type === "local"
    ? target.config.default_recording === true
    : target.config.default_archive === true
}

function cameraName(cameraId: string | null): string {
  if (!cameraId) return t("storage.allCameras")
  return cameras.value.find((item) => item.id === cameraId)?.name ??
    t("storage.unknownCamera")
}

function scopeLabel(policy: RetentionPolicy): string {
  if (policy.scope_type === "GLOBAL") return t("storage.allCameras")
  if (policy.scope_type === "CAMERA") return cameraName(policy.scope_id)
  return t("storage.cameraGroup")
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

    // Background probe for target metrics so the progress bars and health badges show live real data
    targetItems.forEach((target) => {
      void testStorageTarget(target.id)
        .then((res) => {
          targetMetrics.value[target.id] = res
        })
        .catch(() => {
          // ignore background probe failures
        })
    })
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
      t("storage.openlistAllRequired")
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
      t("storage.switchConfirm", {
        source: source.name,
        destination: destination.name
      })
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
    notice.value = t("storage.switchSuccess", {
      destination: destination.name,
      count: result.affected_camera_ids.length,
      source: source.name
    })
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
      notice.value = t("storage.targetUpdated")
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
      notice.value = t("storage.targetCreated")
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
            t("storage.openlistCredentialsRequired")
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
      notice.value = t("storage.targetCreated")
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
    targetMetrics.value[target.id] = result
    testResults.value = {
      ...testResults.value,
      [target.id]:
        result.used_percent !== null &&
        result.used_percent !== undefined &&
        result.capacity_level
          ? t("storage.testCapacity", {
              level: capacityLevelLabel(result.capacity_level),
              used: result.used_percent.toFixed(1),
              free: formatBytes(result.free_bytes)
            })
          : result.free_bytes !== null
            ? t("storage.readyFree", {
                free: formatBytes(result.free_bytes)
              })
            : t("storage.readyVerified")
    }
  } catch (caught) {
    error.value = errorMessage(caught)
    testResults.value = {
      ...testResults.value,
      [target.id]: t("storage.testFailed")
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
  if (!window.confirm(t("storage.deleteTargetConfirm", { name: target.name }))) {
    return
  }
  try {
    await deleteStorageTarget(target.id)
    notice.value = t("storage.targetDeleted")
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function resetPolicyForm(): void {
  policyForm.name = t("storage.defaultRetention")
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
      notice.value = t("storage.policyUpdated")
    } else {
      await createRetentionPolicy(body)
      notice.value = t("storage.policyCreated")
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
  if (!window.confirm(t("storage.deletePolicyConfirm", { name: policy.name }))) {
    return
  }
  try {
    await deleteRetentionPolicy(policy.id)
    notice.value = t("storage.policyDeleted")
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
  <div class="unifi-storage-workspace">
    <!-- Top Header matching UniFi Protect Prototype #protect-storage -->
    <header class="unifi-storage-header">
      <div class="unifi-storage-header__title-group">
        <h2 class="unifi-storage-title">
          {{ t("storage.title") }} & WebDAV Tiering (存储分层、WebDAV 与自动留存)
        </h2>
        <p class="unifi-storage-subtitle">
          本地 NVMe 高速写入池 ➔ WebDAV 自动归档 ➔ 80%/85%/95% 高水位自动清理 ➔ 前端统一直连秒开
        </p>
      </div>

      <div class="unifi-storage-header__actions">
        <!-- Subtab Switcher -->
        <div class="unifi-subtabs-pill">
          <button
            type="button"
            class="unifi-subtab-btn"
            :class="{ 'unifi-subtab-btn--active': tab === 'targets' }"
            @click="tab = 'targets'"
          >
            {{ t("storage.storageTargets") }} (Targets)
          </button>
          <button
            type="button"
            class="unifi-subtab-btn"
            :class="{ 'unifi-subtab-btn--active': tab === 'retention' }"
            @click="tab = 'retention'"
          >
            {{ t("storage.retention") }} (Retention)
          </button>
        </div>

        <button
          class="unifi-btn unifi-btn--ghost"
          type="button"
          :disabled="loading"
          @click="refresh"
        >
          <UiIcon name="refresh" :size="14" />
          <span>{{ t("storage.refresh") }}</span>
        </button>
      </div>
    </header>

    <!-- Top 3 Metrics Summary Cards -->
    <div class="unifi-metrics-summary">
      <article class="unifi-metric-card">
        <div class="unifi-metric-icon-wrap unifi-metric-icon--blue">
          <UiIcon name="drive" :size="18" />
        </div>
        <div>
          <span class="unifi-metric-label">{{ t("storage.recordingTargets") }}</span>
          <strong class="unifi-metric-value">{{ localTargets.length }}</strong>
        </div>
      </article>

      <article class="unifi-metric-card">
        <div class="unifi-metric-icon-wrap unifi-metric-icon--cyan">
          <UiIcon name="cloud" :size="18" />
        </div>
        <div>
          <span class="unifi-metric-label">{{ t("storage.archiveTargets") }}</span>
          <strong class="unifi-metric-value">{{ archiveTargets.length }}</strong>
        </div>
      </article>

      <article class="unifi-metric-card">
        <div class="unifi-metric-icon-wrap unifi-metric-icon--emerald">
          <UiIcon name="shield" :size="18" />
        </div>
        <div>
          <span class="unifi-metric-label">{{ t("storage.activeRetentionPolicies") }}</span>
          <strong class="unifi-metric-value">{{ enabledPolicyCount }}</strong>
        </div>
      </article>
    </div>

    <!-- Error Notice Banner -->
    <div v-if="error" class="unifi-banner unifi-banner--danger">
      <UiIcon name="warning" :size="16" />
      <span>{{ error }}</span>
    </div>

    <!-- Success Notice Banner -->
    <div v-if="notice" class="unifi-banner unifi-banner--success">
      <UiIcon name="check" :size="15" />
      <span>{{ notice }}</span>
    </div>

    <!-- Subtab 1: Storage Targets -->
    <div v-if="tab === 'targets'" class="unifi-tab-content">
      <div class="unifi-section-bar">
        <div>
          <strong class="unifi-section-title">{{ t("storage.storageTargets") }}</strong>
          <span class="unifi-section-desc">{{ t("storage.targetsDescription") }}</span>
        </div>
        <div class="unifi-section-actions">
          <button
            class="unifi-btn unifi-btn--ghost"
            type="button"
            @click="openTargetPanel('rclone')"
          >
            <UiIcon name="cloud" :size="14" />
            <span>{{ t("storage.addArchive") }}</span>
          </button>
          <button
            class="unifi-btn unifi-btn--primary"
            type="button"
            @click="openTargetPanel('local')"
          >
            <UiIcon name="plus" :size="14" />
            <span>{{ t("storage.addLocal") }}</span>
          </button>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="!targets.length && !loading" class="unifi-empty-box">
        <UiIcon name="storage" :size="32" />
        <strong>{{ t("storage.noStorageTargets") }}</strong>
        <span>{{ t("storage.noStorageTargetsHint") }}</span>
      </div>

      <!-- Targets 2-Column Grid -->
      <div v-else class="unifi-targets-grid">
        <!-- 1. Local NVMe Recording Targets -->
        <article
          v-for="target in localTargets"
          :key="target.id"
          class="unifi-target-card"
        >
          <!-- Card Header -->
          <div class="unifi-card-header">
            <div class="unifi-card-title-group">
              <span
                class="unifi-status-dot"
                :class="target.enabled ? 'bg-emerald-400' : 'bg-gray-500'"
              />
              <span class="unifi-card-title">
                本地高速录像缓存池 ({{ target.name }})
              </span>
              <span
                v-if="targetIsDefault(target)"
                class="unifi-badge-pill unifi-badge-pill--blue"
              >
                {{ t("storage.default") }}
              </span>
            </div>

            <!-- Health Status Badge -->
            <span
              class="unifi-status-pill"
              :class="getLocalTargetStatusBadge(target).badgeClass"
            >
              {{ getLocalTargetStatusBadge(target).text }}
            </span>
          </div>

          <!-- Capacity Bar with 80% / 85% / 95% Watermark lines -->
          <div class="unifi-watermark-wrapper">
            <div class="unifi-watermark-bar-track">
              <!-- Used Bar -->
              <div
                class="unifi-watermark-bar-fill"
                :style="{
                  width: `${Math.min(100, Math.max(0, targetMetrics[target.id]?.used_percent ?? 0))}%`,
                  backgroundColor: getLocalTargetBarColor(target)
                }"
              />
              <!-- Watermark Vertical Markers -->
              <div
                class="unifi-watermark-marker unifi-watermark-marker--warning"
                :style="{ left: `${getWatermarkPercent(target, 'warning')}%` }"
                :title="`${getWatermarkPercent(target, 'warning')}% 警戒水位 (通知告警)`"
              />
              <div
                class="unifi-watermark-marker unifi-watermark-marker--high"
                :style="{ left: `${getWatermarkPercent(target, 'high')}%` }"
                :title="`${getWatermarkPercent(target, 'high')}% 高水位清理 (自动释放已归档切片)`"
              />
              <div
                class="unifi-watermark-marker unifi-watermark-marker--critical"
                :style="{ left: `${getWatermarkPercent(target, 'critical')}%` }"
                :title="`${getWatermarkPercent(target, 'critical')}% 极值水位 (紧急熔断降频)`"
              />
            </div>

            <div class="unifi-watermark-legend font-mono">
              <span class="text-gray-300">
                路径: {{ target.config.path || '/recordings' }} (NVMe SSD)
              </span>
              <span v-if="targetMetrics[target.id]?.total_bytes" class="text-gray-400">
                已用 {{ formatBytes(targetMetrics[target.id]?.used_bytes) }} / 总量 {{ formatBytes(targetMetrics[target.id]?.total_bytes) }} (剩余 {{ formatBytes(targetMetrics[target.id]?.free_bytes) }})
              </span>
              <span v-else class="text-gray-500">
                {{ targetWatermarks(target) || '等待测速诊断获取实时容量' }}
              </span>
            </div>
          </div>

          <!-- Watermarks Control Box (3 Columns) -->
          <div class="unifi-watermarks-box">
            <div class="unifi-watermarks-box__title">
              自动清理水位阈值设定 (Watermarks):
            </div>
            <div class="unifi-watermarks-box__grid font-mono">
              <div class="unifi-watermark-metric-cell">
                <span class="text-amber-400">警戒水位: {{ getWatermarkPercent(target, 'warning') }}%</span>
                <div class="unifi-watermark-metric-desc">开始通知告警</div>
              </div>
              <div class="unifi-watermark-metric-cell">
                <span class="text-red-400">高水位: {{ getWatermarkPercent(target, 'high') }}%</span>
                <div class="unifi-watermark-metric-desc">自动释放已归档切片</div>
              </div>
              <div class="unifi-watermark-metric-cell">
                <span class="text-red-500">极值水位: {{ getWatermarkPercent(target, 'critical') }}%</span>
                <div class="unifi-watermark-metric-desc">紧急熔断降频</div>
              </div>
            </div>
          </div>

          <!-- Test Result or Note -->
          <div v-if="testResults[target.id]" class="unifi-card-test-result font-mono">
            <UiIcon name="activity" :size="13" />
            <span>{{ testResults[target.id] }}</span>
          </div>

          <!-- Card Actions Footer -->
          <div class="unifi-card-footer">
            <span class="unifi-protect-status-text">
              写入保护状态：<span class="text-emerald-400 font-bold">加锁保护文件永久豁免清理</span>
            </span>

            <div class="unifi-card-footer__buttons">
              <!-- Diagnostics Button -->
              <button
                class="unifi-btn unifi-btn--compact unifi-btn--ghost"
                type="button"
                :disabled="testingTargetId === target.id"
                @click="runTargetTest(target)"
              >
                <UiIcon name="activity" :size="13" />
                <span>{{ testingTargetId === target.id ? t("storage.testing") : "诊断容量与健康" }}</span>
              </button>

              <!-- Switch Disk Button -->
              <button
                v-if="localTargets.some((item) => item.enabled && item.id !== target.id)"
                class="unifi-btn unifi-btn--compact unifi-btn--ghost"
                type="button"
                :title="t('storage.switchWritesTitle')"
                @click="openSwitchPanel(target)"
              >
                <UiIcon name="next" :size="13" />
                <span>更换本地磁盘</span>
              </button>

              <!-- Edit Target -->
              <button
                class="unifi-icon-btn"
                type="button"
                :title="t('storage.editTarget')"
                @click="openEditTarget(target)"
              >
                <UiIcon name="settings" :size="14" />
              </button>

              <!-- Enable/Disable -->
              <button
                class="unifi-icon-btn"
                type="button"
                :title="target.enabled ? t('storage.disable') : t('storage.enable')"
                @click="toggleTarget(target)"
              >
                <UiIcon :name="target.enabled ? 'pause' : 'play'" :size="14" />
              </button>

              <!-- Delete -->
              <button
                class="unifi-icon-btn unifi-icon-btn--danger"
                type="button"
                :title="t('storage.deleteTarget')"
                @click="removeTarget(target)"
              >
                <UiIcon name="trash" :size="14" />
              </button>
            </div>
          </div>
        </article>

        <!-- 2. WebDAV / Rclone Archive Targets -->
        <article
          v-for="target in archiveTargets"
          :key="target.id"
          class="unifi-target-card"
        >
          <!-- Card Header -->
          <div class="unifi-card-header">
            <div class="unifi-card-title-group">
              <span
                class="unifi-status-dot"
                :class="target.enabled ? 'bg-blue-400' : 'bg-gray-500'"
              />
              <span class="unifi-card-title">
                WebDAV 在线存储池 ({{ target.name }})
              </span>
              <span
                v-if="targetIsDefault(target)"
                class="unifi-badge-pill unifi-badge-pill--cyan"
              >
                {{ t("storage.default") }}
              </span>
            </div>

            <!-- Health Status Badge -->
            <span
              class="unifi-status-pill"
              :class="target.enabled ? 'status-badge--cyan' : 'status-badge--disabled'"
            >
              {{ target.enabled ? '在线热播 · 正常' : t("storage.disabled") }}
            </span>
          </div>

          <!-- Metadata Lines -->
          <div class="unifi-archive-meta font-mono">
            <div>
              服务协议:
              <span class="text-white">
                {{ target.config.provider === 'openlist_webdav' ? 'WebDAV (OpenList / Alist / NAS)' : '通用 Rclone 远端' }}
              </span>
            </div>
            <div>
              远端地址:
              <span class="text-blue-300">
                {{ targetDetail(target) }}
              </span>
            </div>
            <div>
              状态凭据:
              <span :class="target.credentials_configured ? 'text-emerald-400' : 'text-amber-400'">
                {{ target.credentials_configured ? '✓ 凭据已就绪 (SHA-256 校验完毕)' : '⚠ 未配置访问凭据' }}
              </span>
            </div>
          </div>

          <!-- UniFi Highlight Feature Callout -->
          <div class="unifi-callout-box">
            ✨ <b>前端无感等同于本地：</b>WebDAV 录像与本地录像汇聚在同一条连续时间轴上，拖拽洗带时由后端智能流式拉取（Byte Range），不需要手动“恢复/解冻”，体验与本地完全一致。
          </div>

          <!-- Test Result or Note -->
          <div v-if="testResults[target.id]" class="unifi-card-test-result font-mono">
            <UiIcon name="activity" :size="13" />
            <span>{{ testResults[target.id] }}</span>
          </div>

          <!-- Card Actions Footer -->
          <div class="unifi-card-footer">
            <div class="flex items-center space-x-2">
              <button
                class="unifi-btn unifi-btn--primary unifi-btn--compact"
                type="button"
                :disabled="testingTargetId === target.id"
                @click="runTargetTest(target)"
              >
                <UiIcon name="activity" :size="13" />
                <span>{{ testingTargetId === target.id ? t("storage.testing") : "测速与健康诊断" }}</span>
              </button>
            </div>

            <div class="unifi-card-footer__buttons">
              <!-- Edit Target -->
              <button
                class="unifi-btn unifi-btn--compact unifi-btn--ghost"
                type="button"
                @click="openEditTarget(target)"
              >
                <UiIcon name="settings" :size="13" />
                <span>配置参数</span>
              </button>

              <!-- Enable/Disable -->
              <button
                class="unifi-icon-btn"
                type="button"
                :title="target.enabled ? t('storage.disable') : t('storage.enable')"
                @click="toggleTarget(target)"
              >
                <UiIcon :name="target.enabled ? 'pause' : 'play'" :size="14" />
              </button>

              <!-- Delete -->
              <button
                class="unifi-icon-btn unifi-icon-btn--danger"
                type="button"
                :title="t('storage.deleteTarget')"
                @click="removeTarget(target)"
              >
                <UiIcon name="trash" :size="14" />
              </button>
            </div>
          </div>
        </article>
      </div>
    </div>

    <!-- Subtab 2: Retention Policies -->
    <div v-else class="unifi-tab-content">
      <div class="unifi-retention-container">
        <div class="unifi-retention-header">
          <div>
            <div class="unifi-retention-title">
              {{ t("storage.retentionPolicies") }} (Retention Policies)
            </div>
            <div class="unifi-retention-subtitle">
              按常规/事件/手动分类定义过期时间，必须在 WebDAV 备份成功后才允许物理清理
            </div>
          </div>
          <button
            class="unifi-btn unifi-btn--primary"
            type="button"
            @click="openPolicyPanel"
          >
            <UiIcon name="plus" :size="14" />
            <span>{{ t("storage.addPolicy") }}</span>
          </button>
        </div>

        <!-- Empty State -->
        <div v-if="!policies.length && !loading" class="unifi-empty-box">
          <UiIcon name="shield" :size="32" />
          <strong>{{ t("storage.noRetentionPolicies") }}</strong>
          <span>{{ t("storage.noRetentionPoliciesHint") }}</span>
        </div>

        <!-- Structured Retention Table matching Prototype #protect-storage -->
        <div v-else class="unifi-table-responsive">
          <table class="unifi-retention-table">
            <thead>
              <tr>
                <th>{{ t("storage.policy") }}</th>
                <th>{{ t("storage.scope") }}</th>
                <th>{{ t("storage.ordinary") }}</th>
                <th>{{ t("storage.event") }}</th>
                <th>{{ t("storage.manual") }}</th>
                <th>{{ t("storage.mode") || "清理模式" }}</th>
                <th>WebDAV 强制前置</th>
                <th>{{ t("storage.status") }}</th>
                <th class="text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="policy in policies" :key="policy.id">
                <!-- Name -->
                <td class="font-sans font-bold text-white">
                  <div>{{ policy.name }}</div>
                  <div class="text-[10px] text-gray-400 font-normal">
                    {{ policy.mode === "HARD" ? t("storage.hardLimit") : t("storage.bestEffort") }}
                  </div>
                </td>

                <!-- Scope -->
                <td>
                  <span
                    class="unifi-scope-pill"
                    :class="
                      policy.scope_type === 'GLOBAL'
                        ? 'unifi-scope-pill--blue'
                        : policy.scope_type === 'CAMERA'
                          ? 'unifi-scope-pill--purple'
                          : 'unifi-scope-pill--indigo'
                    "
                  >
                    {{ scopeLabel(policy) }}
                  </span>
                </td>

                <!-- Ordinary Keep Days -->
                <td class="font-mono text-white">
                  {{ t("storage.days", { count: policy.ordinary_keep_days }) }}
                </td>

                <!-- Event Keep Days -->
                <td class="font-mono text-white">
                  {{ t("storage.days", { count: policy.event_keep_days }) }}
                </td>

                <!-- Manual Keep Days -->
                <td class="font-mono text-white">
                  {{ t("storage.days", { count: policy.manual_keep_days }) }}
                </td>

                <!-- Mode -->
                <td class="font-sans">
                  <span
                    :class="
                      policy.mode === 'HARD'
                        ? 'text-amber-400 font-medium'
                        : 'text-emerald-400 font-medium'
                    "
                  >
                    {{
                      policy.mode === "HARD"
                        ? "HARD (严格按天强制清除)"
                        : "BEST_EFFORT (水位超限时清理)"
                    }}
                  </span>
                </td>

                <!-- Require Archive -->
                <td class="font-sans">
                  <span v-if="policy.require_archive_before_delete" class="text-emerald-400 font-medium">
                    ✓ 强制 (必须归档完才删)
                  </span>
                  <span v-else class="text-gray-400">
                    - 可选 (允许直删)
                  </span>
                </td>

                <!-- Status -->
                <td>
                  <span
                    class="unifi-status-badge"
                    :class="policy.enabled ? 'unifi-status-badge--normal' : 'unifi-status-badge--disabled'"
                  >
                    {{ policy.enabled ? t("storage.enabled") : t("storage.disabled") }}
                  </span>
                </td>

                <!-- Actions -->
                <td class="text-right">
                  <div class="flex items-center justify-end space-x-1">
                    <button
                      class="unifi-icon-btn"
                      type="button"
                      :title="t('storage.editPolicy')"
                      @click="openEditPolicy(policy)"
                    >
                      <UiIcon name="settings" :size="14" />
                    </button>
                    <button
                      class="unifi-icon-btn"
                      type="button"
                      :title="policy.enabled ? t('storage.disable') : t('storage.enable')"
                      @click="togglePolicy(policy)"
                    >
                      <UiIcon :name="policy.enabled ? 'pause' : 'play'" :size="14" />
                    </button>
                    <button
                      class="unifi-icon-btn unifi-icon-btn--danger"
                      type="button"
                      :title="t('storage.deletePolicy')"
                      @click="removePolicy(policy)"
                    >
                      <UiIcon name="trash" :size="14" />
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ================= MODALS / DRAWERS ================= -->

    <!-- 1. Switch Recording Target Drawer -->
    <div v-if="switchSource" class="unifi-drawer-backdrop" @click.self="switchSource = null; switchDestinationId = ''">
      <aside class="unifi-drawer">
        <header class="unifi-drawer__header">
          <div>
            <strong>{{ t("storage.switchRecordingWrites") }}</strong>
            <span>{{ t("storage.safeRoutingChange") }}</span>
          </div>
          <button
            class="unifi-icon-btn"
            type="button"
            :title="t('storage.close')"
            @click="switchSource = null; switchDestinationId = ''"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <form class="unifi-drawer__form" @submit.prevent="runRecordingTargetSwitch">
          <div class="unifi-switch-summary">
            <span>{{ t("storage.currentTarget") }}</span>
            <strong>{{ switchSource.name }}</strong>
            <small>{{ targetDetail(switchSource) }}</small>
          </div>

          <label class="unifi-form-group">
            <span>{{ t("storage.newRecordingTarget") }}</span>
            <select v-model="switchDestinationId" required>
              <option value="" disabled>
                {{ t("storage.selectLocalTarget") }}
              </option>
              <option
                v-for="targetItem in switchDestinations"
                :key="targetItem.id"
                :value="targetItem.id"
              >
                {{ targetItem.name }} · {{ targetDetail(targetItem) }}
              </option>
            </select>
          </label>

          <div class="unifi-switch-note">
            <UiIcon name="shield" :size="15" />
            <span>{{ t("storage.switchNote") }}</span>
          </div>

          <div class="unifi-drawer__actions">
            <button
              class="unifi-btn unifi-btn--ghost"
              type="button"
              @click="switchSource = null; switchDestinationId = ''"
            >
              {{ t("storage.cancel") }}
            </button>
            <button
              class="unifi-btn unifi-btn--primary"
              type="submit"
              :disabled="switchSaving || !switchDestinationId"
            >
              {{ switchSaving ? t("storage.switching") : t("storage.switchWrites") }}
            </button>
          </div>
        </form>
      </aside>
    </div>

    <!-- 2. Target Editor Drawer (Create / Edit) -->
    <div v-if="targetPanelOpen" class="unifi-drawer-backdrop" @click.self="targetPanelOpen = false; editingTarget = null">
      <aside class="unifi-drawer">
        <header class="unifi-drawer__header">
          <div>
            <strong>
              {{
                editingTarget
                  ? targetForm.type === "local"
                    ? t("storage.editLocalStorage")
                    : t("storage.editArchiveStorage")
                  : targetForm.type === "local"
                    ? t("storage.addLocalStorage")
                    : t("storage.addArchiveStorage")
              }}
            </strong>
            <span>
              {{
                targetForm.type === "local"
                  ? t("storage.recordingDestination")
                  : t("storage.rcloneRemoteArchive")
              }}
            </span>
          </div>
          <button
            class="unifi-icon-btn"
            type="button"
            :title="t('storage.close')"
            @click="targetPanelOpen = false; editingTarget = null"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <form class="unifi-drawer__form" @submit.prevent="saveTarget">
          <label class="unifi-form-group">
            <span>{{ t("storage.name") }}</span>
            <input
              v-model="targetForm.name"
              required
              maxlength="128"
              :placeholder="t('storage.primaryRecordings')"
            />
          </label>

          <template v-if="targetForm.type === 'local'">
            <label class="unifi-form-group">
              <span>{{ t("storage.containerPath") }}</span>
              <input
                v-model="targetForm.path"
                required
                :readonly="Boolean(editingTarget)"
                placeholder="/recordings"
              />
              <small v-if="editingTarget">
                {{ t("storage.recordingRootHint") }}
              </small>
            </label>

            <div class="unifi-watermark-inputs-grid">
              <label class="unifi-form-group">
                <span>{{ t("storage.warningPercent") }}</span>
                <input
                  v-model.number="targetForm.warningPercent"
                  type="number"
                  min="1"
                  max="97"
                  required
                />
              </label>
              <label class="unifi-form-group">
                <span>{{ t("storage.highPercent") }}</span>
                <input
                  v-model.number="targetForm.highPercent"
                  type="number"
                  min="2"
                  max="98"
                  required
                />
              </label>
              <label class="unifi-form-group">
                <span>{{ t("storage.criticalPercent") }}</span>
                <input
                  v-model.number="targetForm.criticalPercent"
                  type="number"
                  min="3"
                  max="99"
                  required
                />
              </label>
            </div>
            <small class="unifi-form-hint">
              {{ t("storage.pressureRetentionHint") }}
            </small>

            <label class="unifi-checkbox-row">
              <input
                v-model="targetForm.defaultRecording"
                type="checkbox"
              />
              <span>{{ t("storage.useDefaultRecordingTarget") }}</span>
            </label>
          </template>

          <template v-else>
            <label class="unifi-form-group">
              <span>{{ t("storage.archiveProvider") }}</span>
              <select
                v-model="targetForm.archiveProvider"
                :disabled="Boolean(editingTarget)"
                @change="handleArchiveProviderChange"
              >
                <option value="custom">
                  {{ t("storage.genericRcloneConfig") }}
                </option>
                <option value="openlist_webdav">
                  {{ t("storage.openlistWebdav") }}
                </option>
              </select>
              <small v-if="editingTarget">
                {{ t("storage.providerFixedHint") }}
              </small>
            </label>

            <label class="unifi-form-group">
              <span>{{ t("storage.rcloneRemoteName") }}</span>
              <input
                v-model="targetForm.remote"
                required
                :readonly="
                  Boolean(editingTarget) &&
                  targetForm.archiveProvider === 'openlist_webdav'
                "
                placeholder="archive"
              />
            </label>

            <label class="unifi-form-group">
              <span>{{ t("storage.basePath") }}</span>
              <input
                v-model="targetForm.basePath"
                placeholder="zero-nvr"
              />
            </label>

            <template v-if="targetForm.archiveProvider === 'openlist_webdav'">
              <label class="unifi-form-group">
                <span>{{ t("storage.openlistWebdavUrl") }}</span>
                <input
                  v-model="targetForm.openlistUrl"
                  :required="!editingTarget"
                  placeholder="https://openlist.example.com/dav/"
                  autocomplete="off"
                />
                <small>
                  {{ t("storage.openlistEndpointHint") }}
                </small>
              </label>

              <label class="unifi-form-group">
                <span>{{ t("storage.openlistUsername") }}</span>
                <input
                  v-model="targetForm.openlistUsername"
                  :required="!editingTarget"
                  autocomplete="off"
                />
              </label>

              <label class="unifi-form-group">
                <span>{{ t("storage.openlistPassword") }}</span>
                <input
                  v-model="targetForm.openlistPassword"
                  :required="!editingTarget"
                  type="password"
                  autocomplete="new-password"
                />
                <small>
                  {{
                    editingTarget
                      ? t("storage.openlistKeepCredentialsHint")
                      : t("storage.openlistStoreCredentialsHint")
                  }}
                </small>
              </label>
            </template>

            <label v-else class="unifi-form-group">
              <span>{{ t("storage.rcloneConfig") }}</span>
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
                    ? t("storage.rcloneKeepCredentialsHint")
                    : t("storage.encryptedNeverReturned")
                }}
              </small>
            </label>

            <label class="unifi-checkbox-row">
              <input
                v-model="targetForm.defaultArchive"
                type="checkbox"
              />
              <span>{{ t("storage.useDefaultArchiveTarget") }}</span>
            </label>
          </template>

          <div class="unifi-drawer__actions">
            <button
              class="unifi-btn unifi-btn--ghost"
              type="button"
              @click="targetPanelOpen = false; editingTarget = null"
            >
              {{ t("storage.cancel") }}
            </button>
            <button
              class="unifi-btn unifi-btn--primary"
              type="submit"
              :disabled="targetSaving"
            >
              {{
                targetSaving
                  ? t("storage.saving")
                  : editingTarget
                    ? t("storage.saveTarget")
                    : t("storage.createTarget")
              }}
            </button>
          </div>
        </form>
      </aside>
    </div>

    <!-- 3. Policy Editor Drawer (Create / Edit) -->
    <div v-if="policyPanelOpen" class="unifi-drawer-backdrop" @click.self="policyPanelOpen = false; editingPolicy = null">
      <aside class="unifi-drawer">
        <header class="unifi-drawer__header">
          <div>
            <strong>
              {{
                editingPolicy
                  ? t("storage.editRetentionPolicy")
                  : t("storage.addRetentionPolicy")
              }}
            </strong>
            <span>{{ t("storage.recordingLifecycleRules") }}</span>
          </div>
          <button
            class="unifi-icon-btn"
            type="button"
            :title="t('storage.close')"
            @click="policyPanelOpen = false; editingPolicy = null"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <form class="unifi-drawer__form" @submit.prevent="savePolicy">
          <label class="unifi-form-group">
            <span>{{ t("storage.name") }}</span>
            <input
              v-model="policyForm.name"
              required
              maxlength="128"
            />
          </label>

          <label class="unifi-form-group">
            <span>{{ t("storage.scope") }}</span>
            <select v-model="policyForm.scopeType">
              <option value="GLOBAL">{{ t("storage.allCameras") }}</option>
              <option value="CAMERA">{{ t("storage.singleCamera") }}</option>
              <option
                v-if="editingPolicy?.scope_type === 'CAMERA_GROUP'"
                value="CAMERA_GROUP"
              >
                {{ t("storage.existingCameraGroup") }}
              </option>
            </select>
          </label>

          <label v-if="policyForm.scopeType === 'CAMERA'" class="unifi-form-group">
            <span>{{ t("storage.camera") }}</span>
            <select v-model="policyForm.scopeId" required>
              <option value="" disabled>{{ t("storage.selectCamera") }}</option>
              <option
                v-for="camera in cameras"
                :key="camera.id"
                :value="camera.id"
              >
                {{ camera.name }}
              </option>
            </select>
          </label>

          <label v-if="policyForm.scopeType === 'CAMERA_GROUP'" class="unifi-form-group">
            <span>{{ t("storage.cameraGroup") }}</span>
            <input :value="policyForm.scopeId" readonly />
            <small>{{ t("storage.cameraGroupHint") }}</small>
          </label>

          <div class="unifi-retention-days-grid">
            <label class="unifi-form-group">
              <span>{{ t("storage.ordinaryDays") }}</span>
              <input
                v-model.number="policyForm.ordinaryDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
            <label class="unifi-form-group">
              <span>{{ t("storage.eventDays") }}</span>
              <input
                v-model.number="policyForm.eventDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
            <label class="unifi-form-group">
              <span>{{ t("storage.manualDays") }}</span>
              <input
                v-model.number="policyForm.manualDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
          </div>

          <label class="unifi-form-group">
            <span>{{ t("storage.policyMode") }}</span>
            <select v-model="policyForm.mode">
              <option value="BEST_EFFORT">{{ t("storage.bestEffort") }}</option>
              <option value="HARD">{{ t("storage.hardLimit") }}</option>
            </select>
          </label>

          <label class="unifi-checkbox-row">
            <input
              v-model="policyForm.requireArchive"
              type="checkbox"
            />
            <span>{{ t("storage.requireArchiveBeforeDeletion") }}</span>
          </label>

          <div class="unifi-drawer__actions">
            <button
              class="unifi-btn unifi-btn--ghost"
              type="button"
              @click="policyPanelOpen = false; editingPolicy = null"
            >
              {{ t("storage.cancel") }}
            </button>
            <button
              class="unifi-btn unifi-btn--primary"
              type="submit"
              :disabled="policySaving"
            >
              {{
                policySaving
                  ? t("storage.saving")
                  : editingPolicy
                    ? t("storage.savePolicy")
                    : t("storage.createPolicy")
              }}
            </button>
          </div>
        </form>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.unifi-storage-workspace {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
  min-height: 100%;
  background: #0c0e14;
  color: #f3f4f6;
}

/* Header */
.unifi-storage-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.unifi-storage-header__title-group {
  min-width: 0;
}

.unifi-storage-title {
  font-size: 20px;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: -0.01em;
  margin: 0;
}

.unifi-storage-subtitle {
  font-size: 12px;
  color: #9ca3af;
  margin: 4px 0 0;
  line-height: 1.4;
}

.unifi-storage-header__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* Subtabs Pill */
.unifi-subtabs-pill {
  display: inline-flex;
  padding: 3px;
  background: #141722;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  gap: 4px;
}

.unifi-subtab-btn {
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  border: 0;
  cursor: pointer;
  background: transparent;
  color: #9ca3af;
  transition: all 0.15s ease;
}

.unifi-subtab-btn:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.05);
}

.unifi-subtab-btn--active {
  background: #2563eb !important;
  color: #ffffff !important;
  box-shadow: 0 1px 3px rgba(37, 99, 235, 0.4);
}

/* Top 3 Metric Summary Cards */
.unifi-metrics-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.unifi-metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: #141722;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
}

.unifi-metric-icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
}

.unifi-metric-icon--blue {
  background: rgba(37, 99, 235, 0.15);
  color: #60a5fa;
}

.unifi-metric-icon--cyan {
  background: rgba(6, 182, 212, 0.15);
  color: #22d3ee;
}

.unifi-metric-icon--emerald {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
}

.unifi-metric-label {
  display: block;
  font-size: 11px;
  color: #9ca3af;
}

.unifi-metric-value {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: #ffffff;
  margin-top: 1px;
}

/* Banners */
.unifi-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 12px;
}

.unifi-banner--danger {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #f87171;
}

.unifi-banner--success {
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #34d399;
}

/* Section Bar */
.unifi-section-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.unifi-section-title {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: #ffffff;
}

.unifi-section-desc {
  display: block;
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
}

.unifi-section-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Targets 2-Column Grid */
.unifi-targets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 16px;
}

.unifi-target-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: #141722;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 20px;
}

/* Card Header */
.unifi-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.unifi-card-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.unifi-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.unifi-card-title {
  font-size: 14px;
  font-weight: 700;
  color: #ffffff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.unifi-badge-pill {
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 600;
}

.unifi-badge-pill--blue {
  background: rgba(37, 99, 235, 0.2);
  color: #93c5fd;
}

.unifi-badge-pill--cyan {
  background: rgba(6, 182, 212, 0.2);
  color: #67e8f9;
}

.unifi-status-pill {
  padding: 3px 9px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  font-family: monospace;
}

.status-badge--normal {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.status-badge--warning {
  background: rgba(245, 158, 11, 0.2);
  color: #fbbf24;
}

.status-badge--high {
  background: rgba(239, 68, 68, 0.2);
  color: #f87171;
}

.status-badge--critical {
  background: rgba(220, 38, 38, 0.35);
  color: #ef4444;
}

.status-badge--cyan {
  background: rgba(6, 182, 212, 0.2);
  color: #22d3ee;
}

.status-badge--disabled {
  background: rgba(255, 255, 255, 0.08);
  color: #9ca3af;
}

/* Watermark Progress Bar */
.unifi-watermark-wrapper {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.unifi-watermark-bar-track {
  position: relative;
  width: 100%;
  height: 12px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 9999px;
  overflow: hidden;
}

.unifi-watermark-bar-fill {
  height: 100%;
  border-radius: 9999px;
  transition: width 0.3s ease;
}

.unifi-watermark-marker {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  z-index: 5;
}

.unifi-watermark-marker--warning {
  background: #fbbf24;
}

.unifi-watermark-marker--high {
  background: #f87171;
}

.unifi-watermark-marker--critical {
  background: #dc2626;
}

.unifi-watermark-legend {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

/* Watermark Controls Box */
.unifi-watermarks-box {
  background: #0f121a;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.unifi-watermarks-box__title {
  font-size: 11px;
  font-weight: 700;
  color: #d1d5db;
}

.unifi-watermarks-box__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.unifi-watermark-metric-cell {
  background: rgba(255, 255, 255, 0.04);
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 11px;
}

.unifi-watermark-metric-desc {
  font-size: 10px;
  color: #6b7280;
  margin-top: 2px;
}

/* WebDAV Archive Meta */
.unifi-archive-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: #d1d5db;
}

.unifi-callout-box {
  font-size: 11px;
  line-height: 1.5;
  color: #93c5fd;
  background: rgba(37, 99, 235, 0.1);
  padding: 12px;
  border-radius: 12px;
  border: 1px solid rgba(37, 99, 235, 0.2);
}

.unifi-card-test-result {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #60a5fa;
  background: rgba(37, 99, 235, 0.08);
  padding: 6px 10px;
  border-radius: 8px;
}

/* Card Footer */
.unifi-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 12px;
  flex-wrap: wrap;
  gap: 8px;
}

.unifi-protect-status-text {
  font-size: 11px;
  color: #9ca3af;
}

.unifi-card-footer__buttons {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* Subtab 2: Retention Policies Table Card */
.unifi-retention-container {
  background: #141722;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.unifi-retention-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 14px;
}

.unifi-retention-title {
  font-size: 14px;
  font-weight: 700;
  color: #ffffff;
}

.unifi-retention-subtitle {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
}

.unifi-table-responsive {
  width: 100%;
  overflow-x: auto;
}

.unifi-retention-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 12px;
}

.unifi-retention-table th {
  padding: 10px 12px;
  color: #9ca3af;
  font-size: 10px;
  font-family: monospace;
  text-transform: uppercase;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.unifi-retention-table td {
  padding: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.unifi-retention-table tr:hover td {
  background: rgba(255, 255, 255, 0.02);
}

.unifi-scope-pill {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  font-family: monospace;
  font-weight: 700;
}

.unifi-scope-pill--blue {
  background: rgba(37, 99, 235, 0.2);
  color: #93c5fd;
}

.unifi-scope-pill--purple {
  background: rgba(168, 85, 247, 0.2);
  color: #d8b4fe;
}

.unifi-scope-pill--indigo {
  background: rgba(99, 102, 241, 0.2);
  color: #c7d2fe;
}

.unifi-status-badge {
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 600;
}

.unifi-status-badge--normal {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.unifi-status-badge--disabled {
  background: rgba(255, 255, 255, 0.08);
  color: #9ca3af;
}

/* Empty State Box */
.unifi-empty-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 48px 24px;
  background: #141722;
  border: 1px dashed rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  color: #9ca3af;
}

.unifi-empty-box strong {
  color: #ffffff;
  font-size: 14px;
}

.unifi-empty-box span {
  font-size: 12px;
}

/* Buttons */
.unifi-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  border: 0;
  cursor: pointer;
  transition: all 0.15s ease;
}

.unifi-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.unifi-btn--primary {
  background: #2563eb;
  color: #ffffff;
}

.unifi-btn--primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.unifi-btn--ghost {
  background: rgba(255, 255, 255, 0.06);
  color: #e5e7eb;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.unifi-btn--ghost:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.unifi-btn--compact {
  padding: 5px 10px;
  font-size: 11px;
}

.unifi-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 0;
  background: rgba(255, 255, 255, 0.06);
  color: #9ca3af;
  cursor: pointer;
  transition: all 0.15s ease;
}

.unifi-icon-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.unifi-icon-btn--danger:hover {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

/* Drawers & Modals */
.unifi-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  display: flex;
  justify-content: flex-end;
}

.unifi-drawer {
  width: 420px;
  max-width: 90vw;
  height: 100%;
  background: #141722;
  border-left: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  animation: slideDrawer 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideDrawer {
  from {
    transform: translateX(100%);
  }
  to {
    transform: translateX(0);
  }
}

.unifi-drawer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.unifi-drawer__header strong {
  display: block;
  font-size: 14px;
  color: #ffffff;
}

.unifi-drawer__header span {
  display: block;
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
}

.unifi-drawer__form {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.unifi-form-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.unifi-form-group span {
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.unifi-form-group input:not([type="checkbox"]),
.unifi-form-group select,
.unifi-form-group textarea {
  width: 100%;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: #0d1017;
  color: #ffffff;
  font-size: 12px;
  outline: none;
  transition: border-color 0.15s ease;
}

.unifi-form-group input:focus,
.unifi-form-group select:focus,
.unifi-form-group textarea:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2);
}

.unifi-form-group small,
.unifi-form-hint {
  font-size: 10px;
  color: #6b7280;
  margin-top: 2px;
}

.unifi-watermark-inputs-grid,
.unifi-retention-days-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.unifi-checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #e5e7eb;
  cursor: pointer;
  margin-top: 4px;
}

.unifi-checkbox-row input {
  width: 16px;
  height: 16px;
  accent-color: #2563eb;
}

.unifi-drawer__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 10px;
  margin-top: auto;
}

/* Switch Summary */
.unifi-switch-summary {
  background: #0d1017;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.unifi-switch-summary span {
  display: block;
  font-size: 10px;
  color: #9ca3af;
  text-transform: uppercase;
}

.unifi-switch-summary strong {
  display: block;
  font-size: 13px;
  color: #ffffff;
  margin-top: 2px;
}

.unifi-switch-summary small {
  display: block;
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
}

.unifi-switch-note {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  background: rgba(37, 99, 235, 0.1);
  border: 1px solid rgba(37, 99, 235, 0.2);
  border-radius: 8px;
  font-size: 11px;
  color: #93c5fd;
  line-height: 1.4;
}

@media (max-width: 768px) {
  .unifi-metrics-summary {
    grid-template-columns: 1fr;
  }
  .unifi-targets-grid {
    grid-template-columns: 1fr;
  }
}
</style>
