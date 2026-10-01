<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"

import {
  getCamera,
  probeCamera,
  type CameraDetail,
  type CameraFormFactor,
  type CameraSummary
} from "../../api/cameras"
import { ApiClientError, errorMessage } from "../../api/client"
import {
  createRecordingTrigger,
  getRecordingPolicy,
  listRecordingTriggers,
  stopRecordingTrigger,
  type RecordingPolicy,
  type RecordingTrigger
} from "../../api/recordings"
import {
  listRetentionPolicies,
  listStorageTargets,
  type RetentionPolicy,
  type StorageTarget
} from "../../api/storage"
import { useAuthStore } from "../../stores/auth"
import DrawerDialog from "../ui/DrawerDialog.vue"
import StatusPill from "../ui/StatusPill.vue"
import CameraDeviceGlyph from "./CameraDeviceGlyph.vue"
import LiveCameraTile from "../live/LiveCameraTile.vue"
import UiIcon from "../ui/UiIcon.vue"

import CameraDetailGeneralTab from "./detail/CameraDetailGeneralTab.vue"
import CameraDetailStreamsTab from "./detail/CameraDetailStreamsTab.vue"
import CameraDetailRecordingTab from "./detail/CameraDetailRecordingTab.vue"
import { useAsyncResource } from "../../composables/useAsyncResource"

type DetailTab = "general" | "streams" | "recording"

const props = defineProps<{
  camera: CameraSummary
  cameras?: CameraSummary[]
}>()

const emit = defineEmits<{
  close: []
  changed: []
  navigate: [camera: CameraSummary]
  openPtz: [camera: CameraSummary]
}>()

const router = useRouter()
const auth = useAuthStore()
const { loading, error, run } = useAsyncResource()
const { t, te } = useI18n({ useScope: "global" })

const formFactorOptions: Array<{ value: CameraFormFactor; label: string }> = [
  { value: "unknown", label: "未指定 (Default)" },
  { value: "bullet", label: "枪机 (Bullet)" },
  { value: "dome", label: "半球 (Dome)" },
  { value: "turret", label: "海螺 / 炮塔 (Turret)" },
  { value: "ptz", label: "云台 (PTZ)" },
  { value: "doorbell", label: "门铃 (Doorbell)" },
  { value: "indoor", label: "室内桌面机 (Indoor)" },
  { value: "panoramic", label: "全景 / 鱼眼 (Panoramic)" }
]

function formFactorLabel(val?: CameraFormFactor | string | null): string {
  return formFactorOptions.find((o) => o.value === val)?.label || "未指定"
}

const tab = ref<DetailTab>("general")
const detail = ref<CameraDetail | null>(null)
const policy = ref<RecordingPolicy | null>(null)
const localTargets = ref<StorageTarget[]>([])
const retentionPolicies = ref<RetentionPolicy[]>([])
const notice = ref<string | null>(null)

// Navigation across cameras
const navigationCameras = computed(() =>
  props.cameras && props.cameras.length > 1 ? props.cameras : [props.camera]
)
const selectedNavigationIndex = computed(() =>
  navigationCameras.value.findIndex((c) => c.id === props.camera.id)
)
const previousCamera = computed(() =>
  selectedNavigationIndex.value > 0 ? navigationCameras.value[selectedNavigationIndex.value - 1] : null
)
const nextCamera = computed(() =>
  selectedNavigationIndex.value >= 0 && selectedNavigationIndex.value < navigationCameras.value.length - 1
    ? navigationCameras.value[selectedNavigationIndex.value + 1]
    : null
)

function navigateTo(target: CameraSummary | null): void {
  if (!target || probing.value) return
  emit("navigate", target)
}

function handleKeyboardNav(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null
  if (target?.closest("input, textarea, select, button, [contenteditable='true']")) return
  if (event.key === "Escape") {
    event.preventDefault()
    emit("close")
    return
  }
  if (event.key === "ArrowLeft" && previousCamera.value) {
    event.preventDefault()
    navigateTo(previousCamera.value)
  } else if (event.key === "ArrowRight" && nextCamera.value) {
    event.preventDefault()
    navigateTo(nextCamera.value)
  }
}

// Probe state
const probing = ref(false)

// Live Streaming state (Powered by LiveCameraTile, same engine as LiveView)
const previewPlaying = ref(false)

function startPreview(): void {
  if (!props.camera.enabled) return
  previewPlaying.value = true
}

function stopPreview(): void {
  previewPlaying.value = false
}

function formatTime(val?: string | null): string {
  if (!val) return "-"
  const d = new Date(val)
  return Number.isNaN(d.getTime()) ? val : d.toLocaleString()
}

const videoSummary = computed(() => {
  const codec = detail.value?.video_codec || props.camera.video_codec
  const width = detail.value?.width || props.camera.width
  const height = detail.value?.height || props.camera.height
  const fps = detail.value?.fps || props.camera.fps

  const parts: string[] = []
  if (codec) parts.push(codec.toUpperCase())
  if (width && height) {
    let res = `${width}×${height}`
    if (width >= 3840) res = "4K (" + res + ")"
    else if (width >= 2560) res = "2K (" + res + ")"
    else if (width >= 1920) res = "1080P (" + res + ")"
    else if (width >= 1280) res = "720P (" + res + ")"
    parts.push(res)
  }
  if (fps) parts.push(`${Math.round(fps)} FPS`)
  return parts.length ? parts.join(" · ") : "尚未获取视频规格"
})

const heroHealthClass = computed(() => {
  if (!detail.value?.enabled) return "disabled"
  if (detail.value?.maintenance) return "maintenance"
  if (detail.value?.connectivity_status === "offline") return "offline"
  if (detail.value?.connectivity_status === "online") return "online"
  return "unknown"
})

// Manual Recording state on quick action bar
const manualRecordingBusy = ref(false)
const activeManualTrigger = ref<RecordingTrigger | null>(null)

const isRecording = computed(() => {
  return Boolean(
    activeManualTrigger.value ||
    policy.value?.runtime?.recording
  )
})

function jumpToLive(): void {
  void router.push({ path: "/live", query: { camera: props.camera.id } })
}

function jumpToPlayback(): void {
  void router.push({ path: "/playback", query: { camera: props.camera.id } })
}

const canConfigure = computed(() => auth.hasPermission("camera.configure"))

function runtimeLabel(value: string): string {
  if (value === "prebuffer") return t("cameras.detail.runtime.prebuffering")
  if (value === "persistent") return t("cameras.detail.runtime.recording")
  return t("cameras.detail.runtime.idle")
}

async function load(): Promise<void> {
  await run(async () => {
    const [cameraValue, targetValues, retentionValues] =
      await Promise.all([
        getCamera(props.camera.id),
        auth.hasPermission("storage.manage")
          ? listStorageTargets()
          : Promise.resolve([]),
        auth.hasPermission("storage.manage")
          ? listRetentionPolicies()
          : Promise.resolve([])
      ])

    detail.value = cameraValue
    localTargets.value = targetValues.filter(
      (item) =>
        item.type === "local" &&
        item.role === "recording" &&
        item.enabled
    )
    retentionPolicies.value = retentionValues.filter(
      (item) => item.enabled
    )

    try {
      policy.value = await getRecordingPolicy(props.camera.id)
    } catch (caught) {
      if (
        caught instanceof ApiClientError &&
        caught.code === "recording_policy_not_configured"
      ) {
        policy.value = null
      } else {
        throw caught
      }
    }
  })
}

async function loadManualTrigger(): Promise<void> {
  if (!props.camera?.id) return
  try {
    const triggers = await listRecordingTriggers(props.camera.id)
    const active = triggers.find(
      (tr) => tr.type.toUpperCase() === "MANUAL" && tr.state === "ACTIVE" && !tr.planned_end_at
    )
    activeManualTrigger.value = active ?? null
  } catch {
    activeManualTrigger.value = null
  }
}

async function handleStartManual(): Promise<void> {
  if (!canConfigure.value || manualRecordingBusy.value) return
  manualRecordingBusy.value = true
  error.value = null
  notice.value = null
  try {
    const trigger = await createRecordingTrigger(
      props.camera.id,
      "抽屉头部快捷发起手动保全录像"
    )
    activeManualTrigger.value = trigger
    notice.value = "手动录像已启动，已提升 10 秒前置预录并写入保全存储区"
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    manualRecordingBusy.value = false
  }
}

async function handleStopManual(): Promise<void> {
  if (!canConfigure.value || manualRecordingBusy.value || !activeManualTrigger.value) return
  manualRecordingBusy.value = true
  error.value = null
  notice.value = null
  try {
    await stopRecordingTrigger(activeManualTrigger.value.id)
    activeManualTrigger.value = null
    notice.value = "手动录像已停止，录像切片已归档入库"
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    manualRecordingBusy.value = false
  }
}

async function handleProbeCamera(): Promise<void> {
  if (!props.camera?.id || probing.value) return
  probing.value = true
  error.value = null
  notice.value = null
  try {
    const res = await probeCamera(props.camera.id)
    if (res.video_codec || (res.width && res.height)) {
      notice.value = `检测完成: 编码 ${(res.video_codec || "h264").toUpperCase()} · ${res.width || 0}×${res.height || 0} · ${res.fps || 0} FPS`
    } else {
      notice.value = "探测成功，未检测到有效视频轨道"
    }
    await load()
    emit("changed")
  } catch (caught) {
    error.value = `探测失败: ${errorMessage(caught)}`
  } finally {
    probing.value = false
  }
}

watch(
  () => props.camera.id,
  () => {
    stopPreview()
    void load()
    void loadManualTrigger()
  }
)

onMounted(() => {
  window.addEventListener("keydown", handleKeyboardNav)
  void load()
  void loadManualTrigger()
})

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleKeyboardNav)
  stopPreview()
})
</script>

<template>
  <DrawerDialog
    backdrop-class="camera-detail-drawer-backdrop"
    @dismiss="emit('close')"
  >
    <aside class="camera-detail-drawer">
      <header class="camera-detail-header">
        <div class="camera-detail-header__main">
          <h2>{{ detail?.name || camera.name }}</h2>
          <span class="camera-ip font-mono">{{ detail?.ip || camera.ip || "IP未分配" }}</span>
        </div>

        <div class="camera-detail-header__actions">
          <div v-if="navigationCameras.length > 1" class="camera-nav-controls">
            <button
              type="button"
              class="camera-nav-btn nav-step-btn"
              :disabled="!previousCamera"
              title="切换上一台摄像机 (← 快捷键)"
              @click="navigateTo(previousCamera)"
            >
              <UiIcon name="chevron-left" :size="16" />
            </button>
            <span class="camera-nav-indicator font-mono">
              {{ selectedNavigationIndex + 1 }} / {{ navigationCameras.length }}
            </span>
            <button
              type="button"
              class="camera-nav-btn nav-step-btn"
              :disabled="!nextCamera"
              title="切换下一台摄像机 (→ 快捷键)"
              @click="navigateTo(nextCamera)"
            >
              <UiIcon name="chevron-right" :size="16" />
            </button>
          </div>

          <button
            type="button"
            class="camera-detail-close"
            :title="t('cameras.detail.closeHint')"
            @click="emit('close')"
          >
            <UiIcon name="x" :size="18" />
          </button>
        </div>
      </header>

      <!-- Hero Card: 设备形态徽标与状态概览 -->
      <section class="camera-hero-card device-hero-card" :class="`camera-hero-card--${heroHealthClass}`">
        <div class="camera-hero-visual">
          <CameraDeviceGlyph
            :form-factor="detail?.form_factor || camera.form_factor || 'unknown'"
            :size="64"
            class="camera-hero-glyph"
          />
          <div class="camera-hero-meta">
            <div class="camera-hero-title-row">
              <strong class="camera-hero-title">{{ detail?.name || camera.name }}</strong>
              <span class="camera-hero-badge" :class="`camera-hero-badge--${heroHealthClass}`">
                <span class="status-dot"></span>
                {{
                  !detail?.enabled
                    ? '已停用'
                    : detail?.maintenance
                      ? '维护模式'
                      : detail?.connectivity_status === 'online'
                        ? '健康在线'
                        : '离线'
                }}
              </span>
            </div>
            <div class="camera-hero-sub">
              <span>{{ detail?.manufacturer || camera.manufacturer || '通用摄像机' }}</span>
              <span v-if="detail?.model || camera.model">· {{ detail?.model || camera.model }}</span>
              <span>· {{ formFactorLabel(detail?.form_factor || camera.form_factor) }}</span>
            </div>
          </div>
        </div>

        <div class="camera-hero-specs">
          <dl class="specs-grid font-mono">
            <div>
              <dt>接入类型</dt>
              <dd class="uppercase">{{ detail?.adapter_type || camera.adapter_type || 'RTSP' }}</dd>
            </div>
            <div>
              <dt>当前规格</dt>
              <dd>{{ videoSummary }}</dd>
            </div>
            <div>
              <dt>最近在线</dt>
              <dd>{{ formatTime(detail?.last_online_at || camera.last_online_at) }}</dd>
            </div>
            <div>
              <dt>录像状态</dt>
              <dd :class="isRecording ? 'text-red-400 font-semibold' : 'text-gray-400'">
                {{ isRecording ? '正在录像' : '空闲待命' }}
              </dd>
            </div>
          </dl>
        </div>
      </section>

      <!-- Real-time Live Preview Stage -->
      <section class="preview-stage-card">
        <div class="preview-stage-header">
          <div>
            <strong>实时画面预览</strong>
            <span>与实时监控同源，基于 WebRTC (WHEP) 毫秒级低延迟与 HLS 自动回退</span>
          </div>
          <div v-if="camera.enabled" class="preview-live-controls">
            <button
              type="button"
              class="preview-toggle-btn"
              :class="{ 'preview-toggle-btn--active': previewPlaying }"
              :title="previewPlaying ? '暂停实时画面以节省带宽' : '播放实时画面'"
              @click="previewPlaying = !previewPlaying"
            >
              <span class="live-dot" :class="{ 'animate-pulse': previewPlaying, 'live-dot--paused': !previewPlaying }"></span>
              <span>{{ previewPlaying ? '正在直播' : '未播放' }}</span>
            </button>
          </div>
        </div>

        <div class="preview-stage-box" :class="{ 'preview-stage-box--idle': !previewPlaying }">
          <template v-if="camera.enabled">
            <LiveCameraTile
              v-if="previewPlaying"
              :camera="detail || camera"
              quality="low"
              :allow-high-quality="true"
              :playback-enabled="true"
              :audio-enabled="false"
              @playback-change="(_id, enabled) => previewPlaying = enabled"
            />

            <!-- Center Play/Pause Overlay Button -->
            <div
              class="preview-center-overlay"
              :class="{ 'preview-center-overlay--active': !previewPlaying }"
              @click="!previewPlaying && startPreview()"
            >
              <button
                type="button"
                class="preview-center-btn"
                :class="{ 'preview-center-btn--pause': previewPlaying }"
                :title="previewPlaying ? '暂停实时画面' : '播放实时画面'"
                @click.stop="previewPlaying = !previewPlaying"
              >
                <span class="preview-center-icon"><UiIcon :name="previewPlaying ? 'pause' : 'play'" :size="26" /></span>
              </button>
              <div class="preview-center-label">
                <strong>{{ previewPlaying ? '暂停实时画面' : '播放实时画面' }}</strong>
                <small>{{ previewPlaying ? '点击暂停以节省网络带宽' : '基于 WebRTC (WHEP) / HLS 极速拉流' }}</small>
              </div>
            </div>
          </template>

          <div v-else class="preview-empty-state">
            <UiIcon name="camera" :size="32" class="text-gray-500 mb-2" />
            <strong>摄像机已禁用</strong>
            <span>启用设备后才能拉取实时画面</span>
          </div>
        </div>
      </section>

      <!-- Quick Operations Action Bar -->
      <section class="quick-actions-bar">
        <button
          v-if="camera.ptz_capable"
          type="button"
          class="quick-action-btn quick-action-btn--ptz"
          title="打开 PTZ 摇杆控制台"
          @click="emit('openPtz', camera)"
        >
          <UiIcon name="activity" :size="13" />
          <span>PTZ 控制</span>
        </button>

        <button
          type="button"
          class="quick-action-btn quick-action-btn--probe"
          :disabled="probing"
          title="测试探测机位 RTSP 码流参数并回填分辨率与编码"
          @click="handleProbeCamera"
        >
          <UiIcon name="search" :size="13" :class="{ 'animate-spin': probing }" />
          <span>{{ probing ? '检测中...' : '连接检测 (Probe)' }}</span>
        </button>

        <button
          v-if="!isRecording"
          type="button"
          class="quick-action-btn quick-action-btn--record"
          :disabled="!canConfigure || manualRecordingBusy"
          title="立即发起保全录像"
          @click="handleStartManual"
        >
          <UiIcon name="play" :size="13" />
          <span>启动录像</span>
        </button>
        <button
          v-else
          type="button"
          class="quick-action-btn quick-action-btn--stop"
          :disabled="!canConfigure || manualRecordingBusy"
          title="停止当前录像并归档"
          @click="handleStopManual"
        >
          <UiIcon name="pause" :size="13" />
          <span>停止录像</span>
        </button>

        <button
          type="button"
          class="quick-action-btn"
          title="直达多画面实时监控"
          @click="jumpToLive"
        >
          <UiIcon name="activity" :size="13" />
          <span>实时监控</span>
        </button>

        <button
          type="button"
          class="quick-action-btn"
          title="直达该机位时光回放 (Time-Lapse)"
          @click="jumpToPlayback"
        >
          <UiIcon name="refresh" :size="13" />
          <span>时光回放</span>
        </button>
      </section>

      <div class="camera-detail-status">
        <StatusPill :variant="detail?.enabled ? 'ok' : 'muted'">
          {{
            detail?.retired_at
              ? t("cameras.retired")
              : detail?.enabled
                ? t("cameras.enabled")
                : t("cameras.disabled")
          }}
        </StatusPill>
        <span>{{ detail?.adapter_type || "manual" }}</span>
        <span v-if="policy?.runtime">
          {{
            policy.runtime.recording
              ? t("cameras.detail.recording")
              : runtimeLabel(policy.runtime.desired_mode)
          }}
        </span>
      </div>

      <!-- Tab Navigation -->
      <nav class="camera-detail-tabs">
        <button
          type="button"
          :class="{ 'camera-detail-tab--active': tab === 'general' }"
          @click="tab = 'general'"
        >
          {{ t("cameras.detail.general") }}
        </button>
        <button
          type="button"
          :class="{ 'camera-detail-tab--active': tab === 'streams' }"
          @click="tab = 'streams'"
        >
          {{ t("cameras.detail.streams") }}
        </button>
        <button
          type="button"
          :class="{ 'camera-detail-tab--active': tab === 'recording' }"
          @click="tab = 'recording'"
        >
          {{ t("cameras.detail.recording") }}
        </button>
      </nav>

      <!-- Alert Banners -->
      <div v-if="error" class="camera-detail-message camera-detail-message--error">
        {{ error }}
      </div>
      <div v-if="notice" class="camera-detail-message camera-detail-message--ok">
        {{ notice }}
      </div>

      <!-- Loading State -->
      <div v-if="loading" class="camera-detail-loading">
        <UiIcon name="refresh" :size="18" />
        {{ t("cameras.detail.loadingCamera") }}
      </div>

      <!-- Tab Contents (Decomposed Subcomponents) -->
      <template v-else-if="detail">
        <CameraDetailGeneralTab
          v-if="tab === 'general'"
          :camera="detail"
          :can-configure="canConfigure"
          @updated="detail = $event"
          @changed="emit('changed')"
          @notice="notice = $event"
          @error="error = $event"
        />

        <CameraDetailStreamsTab
          v-else-if="tab === 'streams'"
          :camera="detail"
          :can-configure="canConfigure"
          @updated="detail = $event"
          @changed="emit('changed')"
          @notice="notice = $event"
          @error="error = $event"
        />

        <CameraDetailRecordingTab
          v-else-if="tab === 'recording'"
          :camera="detail"
          :can-configure="canConfigure"
          :local-targets="localTargets"
          :retention-policies="retentionPolicies"
          @changed="emit('changed')"
          @notice="notice = $event"
          @error="error = $event"
        />
      </template>
    </aside>
  </DrawerDialog>
</template>

<style scoped>
/* UniFi Protect Camera Detail Drawer & Backdrop */
.camera-detail-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  justify-content: flex-end;
}

.camera-detail-drawer {
  position: relative;
  width: min(540px, 96vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--uf-border);
  background: var(--uf-bg-panel);
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.4);
  padding: 24px;
  overflow-y: auto;
  gap: 16px;
}

.camera-detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.camera-detail-header__main h2 {
  font-size: 18px;
  font-weight: 700;
  color: var(--uf-text-primary);
  margin: 0;
}

.camera-ip {
  display: inline-block;
  font-size: 11px;
  color: var(--uf-text-muted);
  margin-top: 2px;
}

.camera-detail-header__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.camera-nav-controls {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  border-radius: 7px;
  padding: 2px 4px;
}

.camera-nav-btn {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  display: grid;
  place-items: center;
  background: transparent;
  border: none;
  color: var(--uf-text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.camera-nav-btn:hover:not(:disabled) {
  background: var(--uf-bg-card);
  color: var(--uf-text-primary);
}

.camera-nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.camera-nav-indicator {
  font-size: 11px;
  color: var(--uf-text-muted);
  padding: 0 4px;
  user-select: none;
}

.camera-detail-close {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: transparent;
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.camera-detail-close:hover {
  background: var(--uf-bg-card);
  color: var(--uf-text-primary);
}

/* Hero Card */
.camera-hero-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border-radius: 12px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
  transition: border-color 0.2s ease;
}

.camera-hero-visual {
  display: flex;
  align-items: center;
  gap: 14px;
}

.camera-hero-glyph {
  flex-shrink: 0;
  padding: 8px;
  border-radius: 10px;
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
}

.camera-hero-meta {
  flex: 1;
  min-width: 0;
}

.camera-hero-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.camera-hero-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--uf-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.camera-hero-sub {
  font-size: 11px;
  color: var(--uf-text-muted);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.camera-hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 9999px;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
}

.camera-hero-badge--online {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.camera-hero-badge--offline {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.camera-hero-badge--disabled {
  background: rgba(156, 163, 175, 0.15);
  color: #9ca3af;
}

.camera-hero-badge--maintenance {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.camera-hero-specs {
  border-top: 1px solid var(--uf-border);
  padding-top: 10px;
}

.specs-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin: 0;
}

.specs-grid dt {
  font-size: 10px;
  color: var(--uf-text-muted);
}

.specs-grid dd {
  font-size: 11px;
  color: var(--uf-text-secondary);
  margin: 1px 0 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Real-time Live Preview Stage Card */
.preview-stage-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
}

.preview-stage-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.preview-stage-header strong {
  font-size: 12px;
  font-weight: 600;
  color: var(--uf-text-primary);
  display: block;
}

.preview-stage-header span {
  font-size: 10px;
  color: var(--uf-text-muted);
  display: block;
}

.preview-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 8px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
  color: var(--uf-text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.preview-toggle-btn:hover {
  background: var(--uf-bg-card);
  color: var(--uf-text-primary);
}

.preview-toggle-btn--active {
  border-color: rgba(16, 185, 129, 0.4);
  color: #10b981;
  background: rgba(16, 185, 129, 0.1);
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.live-dot--paused {
  background: #6b7280;
}

.preview-stage-box {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: 8px;
  background: #000000;
  border: 1px solid var(--uf-border);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-stage-box--idle {
  background: radial-gradient(circle at center, #141824 0%, #06070a 100%);
}

.preview-stage-box :deep(.live-tile) {
  width: 100%;
  height: 100%;
  border: none;
}

.preview-center-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(2px);
  z-index: 10;
  transition: all 0.2s ease;
  pointer-events: none;
}

.preview-stage-box--idle .preview-center-overlay {
  background: transparent;
  backdrop-filter: none;
  pointer-events: auto;
  cursor: pointer;
}

.preview-stage-box:not(.preview-stage-box--idle) .preview-center-overlay {
  opacity: 0;
  background: rgba(0, 0, 0, 0.45);
}

.preview-stage-box:not(.preview-stage-box--idle):hover .preview-center-overlay {
  opacity: 1;
}

.preview-center-btn {
  pointer-events: auto;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 2px solid var(--uf-accent);
  background: var(--uf-accent-soft);
  color: var(--uf-accent);
  display: grid;
  place-items: center;
  font-size: 20px;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

.preview-center-btn:hover {
  transform: scale(1.1);
  background: var(--uf-accent);
  color: var(--text-on-accent);
  box-shadow: 0 0 20px var(--uf-accent-glow);
}

.preview-center-btn--pause {
  border-color: rgba(255, 255, 255, 0.5);
  background: rgba(0, 0, 0, 0.6);
  color: #ffffff;
}

.preview-center-btn--pause:hover {
  border-color: #ef4444;
  background: #ef4444;
  color: #ffffff;
  box-shadow: 0 0 20px rgba(239, 68, 68, 0.4);
}

.preview-center-icon {
  display: inline-block;
  line-height: 1;
  margin-left: 2px;
}

.preview-center-btn--pause .preview-center-icon {
  margin-left: 0;
}

.preview-center-label {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  text-align: center;
  pointer-events: none;
}

.preview-center-label strong {
  font-size: 13px;
  font-weight: 700;
  color: #ffffff;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.7);
}

.preview-center-label small {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.75);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.7);
}

.preview-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 16px;
  color: var(--uf-text-muted);
  text-align: center;
}

.preview-empty-state strong {
  font-size: 12px;
  color: var(--uf-text-primary);
}

.preview-empty-state span {
  margin-top: 2px;
  font-size: 11px;
}

/* Quick Operations Bar */
.quick-actions-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.quick-action-btn {
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 8px;
  border-radius: 7px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
  color: var(--uf-text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.quick-action-btn:hover:not(:disabled) {
  background: var(--uf-bg-card);
  color: var(--uf-text-primary);
  border-color: var(--uf-text-muted);
}

.quick-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.quick-action-btn--ptz {
  border-color: rgba(59, 130, 246, 0.4);
  color: #3b82f6;
  background: rgba(59, 130, 246, 0.08);
}

.quick-action-btn--ptz:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.16);
  color: #60a5fa;
}

.quick-action-btn--record {
  border-color: rgba(239, 68, 68, 0.4);
  color: #ef4444;
  background: rgba(239, 68, 68, 0.08);
}

.quick-action-btn--record:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.16);
  color: #f87171;
}

.quick-action-btn--stop {
  border-color: rgba(245, 158, 11, 0.4);
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
}

.quick-action-btn--stop:hover:not(:disabled) {
  background: rgba(245, 158, 11, 0.16);
  color: #fbbf24;
}

/* Status & Tabs */
.camera-detail-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--uf-text-muted);
}

.status-pill {
  padding: 2px 8px;
  border-radius: 9999px;
  font-size: 10px;
  font-weight: 600;
}

.status-pill--ok {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.status-pill--muted {
  background: rgba(156, 163, 175, 0.15);
  color: #9ca3af;
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.camera-detail-tabs {
  display: flex;
  border-bottom: 1px solid var(--uf-border);
  gap: 16px;
  margin-top: 4px;
}

.camera-detail-tabs button {
  position: relative;
  background: transparent;
  border: none;
  padding: 8px 4px 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--uf-text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.camera-detail-tabs button:hover {
  color: var(--uf-text-primary);
}

.camera-detail-tabs button::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: transparent;
  transition: background 0.15s ease;
}

.camera-detail-tabs .camera-detail-tab--active {
  color: var(--uf-accent);
}

.camera-detail-tabs .camera-detail-tab--active::after {
  background: var(--uf-accent);
}

/* Alert messages */
.camera-detail-message {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
}

.camera-detail-message--error {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #ef4444;
}

.camera-detail-message--ok {
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #10b981;
}

.camera-detail-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px;
  color: var(--uf-text-muted);
  font-size: 13px;
}
</style>
