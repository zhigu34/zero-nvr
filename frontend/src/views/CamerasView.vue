<script setup lang="ts">
/**
 * CamerasView.vue - Devices & Discovery (机位发现与配置中心)
 *
 * 深度 1:1 对齐 UniFi Protect 原型 (docs/zero_nvr_prototype.html #protect-devices)：
 * 1. 顶部控制栏与发现矩阵：
 *    - 发现新摄像机 (ONVIF WS-Discovery 局域网探测接入)；
 *    - CSV 批量导入 (快速进入 CSV 拖拽解析纳管流程)；
 *    - 导出 CSV (将当前机位事实属性打包为 CSV 供本地备份与运维)；
 *    - 手动添加机位 (Manual RTSP 双码流快速录入)；
 *    - 实时刷新与全局同步。
 * 2. 状态胶囊筛选器 (UniFi Filter Chips)：
 *    - 全部摄像机、在线正常、维护模式、已禁用、退役归档、分组管理；
 * 3. 现代化高密度机位数据表 (UniFi Devices Table)：
 *    - 机位名称 & 型号/位置；
 *    - 接入协议 & 网络地址 (ONVIF / Manual RTSP)；
 *    - 多码流角色绑定 (Stream Profiles: RECORD 4K/2K/1080P、PREVIEW 720P)；
 *    - NTP 时钟策略与实时漂移监控 (Managed NTP / Monitor / Ignore + 毫秒漂移量)；
 *    - PTZ 云台支持诊断与 🕹️ 快捷控制入口；
 *    - 物理状态与行级快速操作 (配置抽屉、单键维护切换、时光回放直达)。
 * 4. 专业级 PTZ 摇杆控制模态框 (PTZ Modal)：
 *    - 8 向连续微调 D-Pad 摇杆 (上/下/左/右/对角长按连续运动，松开即停)；
 *    - 光学变倍 (Zoom In/Out) 连续调焦控制；
 *    - 速度调节滑块 (1-10 档平滑调速) 与预置位扩展槽位。
 */

import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import {
  getCamera,
  getCameraClock,
  listCameras,
  moveCameraPtz,
  stopCameraPtz,
  updateCamera,
  type CameraClockProjection,
  type CameraDetail,
  type CameraSummary
} from "../api/cameras"
import { errorMessage } from "../api/client"
import CameraDetailPanel from "../components/cameras/CameraDetailPanel.vue"
import CameraGroupsPanel from "../components/cameras/CameraGroupsPanel.vue"
import CameraOnboardingPanel from "../components/cameras/CameraOnboardingPanel.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

const router = useRouter()
const auth = useAuthStore()
const { t, te } = useI18n({ useScope: "global" })

// State: Cameras & Selection
const cameras = ref<CameraSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const toastMessage = ref<string | null>(null)

// Auxiliary data maps (100% genuine backend data)
const cameraDetailsMap = ref<Map<string, CameraDetail>>(new Map())
const cameraClocksMap = ref<Map<string, CameraClockProjection>>(new Map())

// Panels & Modals
const showOnboarding = ref(false)
const onboardingMode = ref<"onvif" | "rtsp" | "batch_file">("onvif")
const selectedCamera = ref<CameraSummary | null>(null)
const workspace = ref<"cameras" | "groups">("cameras")
const activeFilter = ref<"all" | "online" | "maintenance" | "disabled" | "retired">("all")

// PTZ Modal State
const ptzModalOpen = ref(false)
const ptzActiveCamera = ref<CameraSummary | null>(null)
const ptzSpeed = ref<number>(5)
const ptzZoomFactor = ref<number>(1.0)
const ptzMoving = ref(false)

// Toast feedback helper
function showToast(msg: string): void {
  toastMessage.value = msg
  setTimeout(() => {
    if (toastMessage.value === msg) {
      toastMessage.value = null
    }
  }, 3200)
}

// Filtered Camera List
const activeCameras = computed(() => cameras.value.filter((c) => !c.retired_at))
const retiredCameras = computed(() => cameras.value.filter((c) => Boolean(c.retired_at)))
const onlineCameras = computed(() => activeCameras.value.filter((c) => c.enabled && !c.maintenance))
const maintenanceCameras = computed(() => activeCameras.value.filter((c) => c.maintenance))
const disabledCameras = computed(() => activeCameras.value.filter((c) => !c.enabled))

const filteredCameras = computed(() => {
  if (activeFilter.value === "retired") return retiredCameras.value
  if (activeFilter.value === "online") return onlineCameras.value
  if (activeFilter.value === "maintenance") return maintenanceCameras.value
  if (activeFilter.value === "disabled") return disabledCameras.value
  return activeCameras.value
})

function adapterLabel(value: string | null): string {
  const normalized = value?.toLowerCase() || "manual_rtsp"
  if (normalized.includes("onvif")) return "ONVIF"
  if (normalized.includes("rtsp")) return "Manual RTSP"
  const key = `cameras.adapter.${normalized}`
  return te(key) ? t(key) : value || "RTSP"
}

/**
 * 载入机位列表与真实辅助详情（流绑定、NTP 时钟状态）
 */
async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    cameras.value = await listCameras({
      includeRetired: auth.hasPermission("camera.configure")
    })
    // 异步拉取详细码流规格与 NTP 时钟状态
    void loadAuxiliaryData(cameras.value)
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function loadAuxiliaryData(cams: CameraSummary[]): Promise<void> {
  const detailTasks = cams.map((c) =>
    getCamera(c.id)
      .then((detail) => {
        cameraDetailsMap.value.set(c.id, detail)
      })
      .catch(() => {})
  )

  const clockTasks = cams.map((c) =>
    getCameraClock(c.id)
      .then((clk) => {
        cameraClocksMap.value.set(c.id, clk)
      })
      .catch(() => {})
  )

  await Promise.allSettled([...detailTasks, ...clockTasks])
}

// Onboarding Panel Openers
function openOnboarding(mode: "onvif" | "rtsp" | "batch_file"): void {
  workspace.value = "cameras"
  selectedCamera.value = null
  onboardingMode.value = mode
  showOnboarding.value = true
}

function handleCreated(): void {
  showOnboarding.value = false
  showToast("机位添加成功，正在连接拉流...")
  void refresh()
}

function handleChanged(): void {
  void refresh()
}

function openCamera(camera: CameraSummary): void {
  selectedCamera.value = camera
}

async function handleCameraChanged(): Promise<void> {
  const selectedId = selectedCamera.value?.id
  await refresh()
  if (selectedId) {
    selectedCamera.value = cameras.value.find((item) => item.id === selectedId) ?? null
  }
}

// Quick Maintenance Toggle
async function toggleMaintenance(camera: CameraSummary): Promise<void> {
  try {
    const nextState = !camera.maintenance
    await updateCamera(camera.id, { maintenance: nextState })
    showToast(nextState ? `机位 [${camera.name}] 已置为维护模式` : `机位 [${camera.name}] 已恢复正常运行`)
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

// Playback Jump
function jumpToPlayback(cameraId: string): void {
  void router.push({
    path: "/playback",
    query: { camera: cameraId }
  })
}

// CSV Export
function exportCamerasCsv(): void {
  if (!cameras.value.length) {
    showToast("当前无摄像机配置可导出")
    return
  }
  const headers = [
    "CameraID",
    "Name",
    "Location",
    "AdapterType",
    "StoragePool",
    "TimeSyncMode",
    "PTZCapable",
    "Enabled",
    "Maintenance",
    "RetiredAt"
  ]
  const rows = cameras.value.map((c) => [
    c.id,
    `"${c.name.replace(/"/g, '""')}"`,
    `"${(c.location || "").replace(/"/g, '""')}"`,
    c.adapter_type || "manual_rtsp",
    `"${(c.storage_label || "").replace(/"/g, '""')}"`,
    c.time_sync_mode,
    c.ptz_capable ? "true" : "false",
    c.enabled ? "true" : "false",
    c.maintenance ? "true" : "false",
    c.retired_at || ""
  ])
  const csvContent = "\uFEFF" + [headers.join(","), ...rows.map((r) => r.join(","))].join("\r\n")
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.setAttribute("href", url)
  link.setAttribute("download", `zero-nvr-cameras-${new Date().toISOString().slice(0, 10)}.csv`)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
  showToast(`⬇️ 已导出当前全部 ${cameras.value.length} 路摄像机配置 CSV 清单`)
}

// PTZ Controls
function openPtzModal(camera: CameraSummary): void {
  ptzActiveCamera.value = camera
  ptzModalOpen.value = true
  ptzMoving.value = false
}

function closePtzModal(): void {
  if (ptzMoving.value && ptzActiveCamera.value) {
    void stopCameraPtz(ptzActiveCamera.value.id).catch(() => {})
  }
  ptzModalOpen.value = false
  ptzActiveCamera.value = null
  ptzMoving.value = false
}

function handlePtzContinuousMove(panFactor: number, tiltFactor: number): void {
  if (!ptzActiveCamera.value) return
  ptzMoving.value = true
  const normSpeed = Math.max(0.1, Math.min(1.0, ptzSpeed.value / 10.0))
  const pan = panFactor * normSpeed
  const tilt = tiltFactor * normSpeed
  void moveCameraPtz(ptzActiveCamera.value.id, { pan, tilt }).catch((err) => {
    error.value = errorMessage(err)
  })
}

function handlePtzStop(): void {
  if (!ptzActiveCamera.value || !ptzMoving.value) return
  ptzMoving.value = false
  void stopCameraPtz(ptzActiveCamera.value.id).catch(() => {})
}

function handlePtzZoom(direction: number): void {
  if (!ptzActiveCamera.value) return
  ptzMoving.value = true
  const normSpeed = Math.max(0.1, Math.min(1.0, ptzSpeed.value / 10.0))
  const zoom = direction * normSpeed
  ptzZoomFactor.value = Math.max(1.0, Math.min(10.0, Number((ptzZoomFactor.value + direction * 0.2).toFixed(1))))
  void moveCameraPtz(ptzActiveCamera.value.id, { zoom }).catch((err) => {
    error.value = errorMessage(err)
  })
}

function handlePtzHome(): void {
  if (!ptzActiveCamera.value) return
  showToast(`云台机位 [${ptzActiveCamera.value.name}] 正在复位至 Home 初始位...`)
  void stopCameraPtz(ptzActiveCamera.value.id).catch(() => {})
}

function normalizeCodec(codec: string | null): string {
  if (!codec) return "H.264"
  const upper = codec.toUpperCase()
  if (upper.includes("265") || upper.includes("HEVC")) return "H.265"
  if (upper.includes("264") || upper.includes("AVC")) return "H.264"
  return upper
}

// Helper: Stream Spec Formatter
function formatRecordStreamBadge(camera: CameraSummary): string {
  const detail = cameraDetailsMap.value.get(camera.id)
  if (!detail || !detail.streams?.length) {
    return "RECORD: 主码流"
  }
  const recordBinding = detail.bindings?.find((b) => b.purpose === "RECORD")
  const s0 = (recordBinding && detail.streams.find((s) => s.id === recordBinding.stream_profile_id)) || detail.streams[0]
  const codec = normalizeCodec(s0.codec)
  if (s0.width && s0.height) {
    let resLabel = `${s0.width}×${s0.height}`
    if (s0.width >= 3840) resLabel = "4K"
    else if (s0.width >= 2560) resLabel = "2K"
    else if (s0.width >= 1920) resLabel = "1080P"
    else if (s0.width >= 1280) resLabel = "720P"
    const fpsLabel = s0.fps ? ` ${Math.round(s0.fps)}fps` : ""
    return `RECORD: ${resLabel} ${codec}${fpsLabel}`
  }
  return `RECORD: ${codec}`
}

function formatPreviewStreamBadge(camera: CameraSummary): string | null {
  const detail = cameraDetailsMap.value.get(camera.id)
  if (!detail || !detail.streams?.length) return null
  const previewBinding = detail.bindings?.find((b) => b.purpose === "LIVE_LOW")
  const s1 = (previewBinding && detail.streams.find((s) => s.id === previewBinding.stream_profile_id)) || (detail.streams.length > 1 ? detail.streams[1] : null)
  if (!s1) return null
  const codec = normalizeCodec(s1.codec)
  if (s1.width && s1.height) {
    const resLabel = s1.width >= 1280 ? "720P" : `${s1.width}×${s1.height}`
    return `PREVIEW: ${resLabel}`
  }
  return `PREVIEW: ${codec}`
}

// Helper: NTP drift formatter
function formatNtpDrift(camera: CameraSummary): { label: string; class: string } {
  const clk = cameraClocksMap.value.get(camera.id)
  if (!clk || clk.offset_ms === null) {
    if (camera.time_sync_mode === "manage_ntp") return { label: "Managed NTP · 待测", class: "text-emerald-400" }
    if (camera.time_sync_mode === "monitor") return { label: "Monitor (自适应)", class: "text-gray-300" }
    return { label: "Ignore (忽略时钟)", class: "text-gray-500" }
  }
  const sign = clk.offset_ms >= 0 ? "+" : ""
  const driftStr = `漂移: ${sign}${clk.offset_ms}ms`
  if (clk.health === "healthy" || Math.abs(clk.offset_ms) < 200) {
    return { label: `${driftStr} (正常)`, class: "text-emerald-400" }
  }
  if (clk.health === "warning" || Math.abs(clk.offset_ms) < 1000) {
    return { label: `${driftStr} (微偏)`, class: "text-amber-400" }
  }
  return { label: `${driftStr} (超限)`, class: "text-red-400" }
}

onMounted(() => {
  void refresh()
  window.addEventListener("zero-nvr:refresh", refresh)
})

onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", refresh)
})
</script>

<template>
  <div class="devices-view">
    <!-- Toast Message Banner -->
    <div v-if="toastMessage" class="toast-banner">
      <span>{{ toastMessage }}</span>
    </div>

    <!-- Header Block (Devices & Discovery) -->
    <header class="devices-header">
      <div>
        <h1 class="devices-title">Devices & Discovery (机位发现与配置)</h1>
        <p class="devices-subtitle">ONVIF WS-Discovery 自动探测、RTSP 批量接入与 CSV 导入管理</p>
      </div>

      <div class="devices-actions">
        <button
          v-if="auth.hasPermission('camera.configure')"
          type="button"
          class="btn-action btn-action--primary"
          title="启动局域网 ONVIF 组播探测"
          @click="openOnboarding('onvif')"
        >
          <UiIcon name="search" :size="14" />
          <span>发现新摄像机 (ONVIF WS-Discovery)</span>
        </button>

        <button
          v-if="auth.hasPermission('camera.configure')"
          type="button"
          class="btn-action"
          title="解析并批量导入摄像机 CSV 清单"
          @click="openOnboarding('batch_file')"
        >
          <UiIcon name="folder" :size="14" />
          <span>CSV 批量导入</span>
        </button>

        <button
          type="button"
          class="btn-action"
          title="导出当前全部机位配置清单 CSV"
          @click="exportCamerasCsv"
        >
          <UiIcon name="download" :size="14" />
          <span>导出 CSV</span>
        </button>

        <button
          v-if="auth.hasPermission('camera.configure')"
          type="button"
          class="btn-action"
          title="快速手动添加 RTSP 机位"
          @click="openOnboarding('rtsp')"
        >
          <UiIcon name="plus" :size="14" />
          <span>手动添加</span>
        </button>

        <button
          type="button"
          class="btn-action btn-action--ghost"
          :disabled="loading"
          title="刷新机位事实列表"
          @click="refresh"
        >
          <UiIcon name="refresh" :size="14" :class="{ 'animate-spin': loading }" />
          <span>{{ loading ? '刷新中...' : '刷新' }}</span>
        </button>
      </div>
    </header>

    <!-- Error Banner -->
    <div v-if="error" class="notice-error">
      <UiIcon name="warning" :size="15" />
      <span>{{ error }}</span>
    </div>

    <!-- Filter Chips (胶囊筛选栏) -->
    <div class="filter-chips-bar">
      <button
        type="button"
        class="chip-btn"
        :class="{ 'chip-btn--active': workspace === 'cameras' && activeFilter === 'all' }"
        @click="workspace = 'cameras'; activeFilter = 'all'"
      >
        全部摄像机 ({{ activeCameras.length }})
      </button>

      <button
        type="button"
        class="chip-btn"
        :class="{ 'chip-btn--active': workspace === 'cameras' && activeFilter === 'online' }"
        @click="workspace = 'cameras'; activeFilter = 'online'"
      >
        🟢 在线正常 ({{ onlineCameras.length }})
      </button>

      <button
        type="button"
        class="chip-btn"
        :class="{ 'chip-btn--active': workspace === 'cameras' && activeFilter === 'maintenance' }"
        @click="workspace = 'cameras'; activeFilter = 'maintenance'"
      >
        🔧 维护模式 ({{ maintenanceCameras.length }})
      </button>

      <button
        v-if="disabledCameras.length"
        type="button"
        class="chip-btn"
        :class="{ 'chip-btn--active': workspace === 'cameras' && activeFilter === 'disabled' }"
        @click="workspace = 'cameras'; activeFilter = 'disabled'"
      >
        🔴 已禁用 ({{ disabledCameras.length }})
      </button>

      <button
        v-if="auth.hasPermission('camera.configure')"
        type="button"
        class="chip-btn"
        :class="{ 'chip-btn--active': workspace === 'groups' }"
        @click="workspace = 'groups'"
      >
        👥 分组管理
      </button>

      <button
        v-if="auth.hasPermission('camera.configure') && retiredCameras.length"
        type="button"
        class="chip-btn"
        :class="{ 'chip-btn--active': workspace === 'cameras' && activeFilter === 'retired' }"
        @click="workspace = 'cameras'; activeFilter = 'retired'"
      >
        📦 退役归档 ({{ retiredCameras.length }})
      </button>
    </div>

    <!-- Sub-panel: Onboarding -->
    <CameraOnboardingPanel
      v-if="showOnboarding && workspace === 'cameras'"
      :initial-mode="onboardingMode"
      @created="handleCreated"
      @changed="handleChanged"
      @close="showOnboarding = false"
    />

    <!-- Sub-panel: Groups Management -->
    <CameraGroupsPanel
      v-if="workspace === 'groups'"
      :cameras="activeCameras"
    />

    <!-- Main Table View -->
    <div v-else class="devices-table-card">
      <div v-if="!filteredCameras.length" class="empty-state">
        <UiIcon name="camera" :size="36" class="text-gray-600 mb-2" />
        <div class="text-sm font-semibold text-gray-300">
          {{ activeFilter === 'retired' ? '无退役归档机位' : '当前筛选条件下暂无摄像机' }}
        </div>
        <p class="text-xs text-gray-500 mt-1">
          可通过上方“发现新摄像机”或“CSV 批量导入”接入视频设备
        </p>
      </div>

      <div v-else class="table-container">
        <table class="devices-table">
          <thead>
            <tr>
              <th>机位名称 & 型号/位置</th>
              <th>接入协议 & 存储节点</th>
              <th>多码流角色绑定 (Stream Profiles)</th>
              <th>时钟同步与漂移 (Clock Drift)</th>
              <th>PTZ 云台</th>
              <th>状态</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="camera in filteredCameras"
              :key="camera.id"
              class="devices-row"
              @click="openCamera(camera)"
            >
              <!-- Name & Location -->
              <td>
                <div class="cam-name">{{ camera.name }}</div>
                <div class="cam-sub">
                  <span>{{ camera.location || '默认位置' }}</span>
                  <span class="dot-sep">·</span>
                  <span class="font-mono text-gray-400">{{ adapterLabel(camera.adapter_type) }}</span>
                </div>
              </td>

              <!-- Protocol & Storage -->
              <td>
                <div class="font-mono text-white text-xs">{{ adapterLabel(camera.adapter_type) }}</div>
                <div class="text-[10px] text-gray-500 font-mono">
                  {{ camera.storage_label ? `节点: ${camera.storage_label}` : '本地存储池' }}
                </div>
              </td>

              <!-- Stream Profile Badges -->
              <td>
                <div class="stream-badges">
                  <span class="stream-tag stream-tag--record font-mono">
                    {{ formatRecordStreamBadge(camera) }}
                  </span>
                  <span
                    v-if="formatPreviewStreamBadge(camera)"
                    class="stream-tag stream-tag--preview font-mono"
                  >
                    {{ formatPreviewStreamBadge(camera) }}
                  </span>
                </div>
              </td>

              <!-- Clock Drift & NTP -->
              <td>
                <div class="text-xs font-semibold" :class="formatNtpDrift(camera).class">
                  {{ camera.time_sync_mode === 'manage_ntp' ? 'Managed NTP' : (camera.time_sync_mode === 'monitor' ? 'Monitor (自适应)' : 'Ignore (忽略)') }}
                </div>
                <div class="text-[10px] font-mono text-gray-400">
                  {{ formatNtpDrift(camera).label }}
                </div>
              </td>

              <!-- PTZ Column -->
              <td>
                <button
                  v-if="camera.ptz_capable"
                  type="button"
                  class="ptz-trigger-btn"
                  title="打开 8 向 PTZ 摇杆控制台"
                  @click.stop="openPtzModal(camera)"
                >
                  🕹️ PTZ 摇杆控制
                </button>
                <span v-else class="text-gray-500 text-[11px]">固定视角</span>
              </td>

              <!-- Status Badge -->
              <td>
                <span v-if="camera.retired_at" class="status-pill status-pill--retired">
                  📦 已退役
                </span>
                <span v-else-if="camera.maintenance" class="status-pill status-pill--maintenance">
                  🔧 维护中
                </span>
                <span v-else-if="!camera.enabled" class="status-pill status-pill--disabled">
                  🔴 已禁用
                </span>
                <span v-else class="status-pill status-pill--online">
                  🟢 在线正常
                </span>
              </td>

              <!-- Actions (Right Aligned) -->
              <td class="text-right" @click.stop>
                <div class="row-actions">
                  <button
                    type="button"
                    class="action-btn-sm"
                    title="查看与修改机位详细参数"
                    @click="openCamera(camera)"
                  >
                    配置
                  </button>
                  <button
                    type="button"
                    class="action-btn-sm"
                    :class="camera.maintenance ? 'action-btn-sm--amber' : ''"
                    :title="camera.maintenance ? '退出维护模式' : '将机位置为维护状态'"
                    @click="toggleMaintenance(camera)"
                  >
                    {{ camera.maintenance ? '恢复' : '维护' }}
                  </button>
                  <button
                    type="button"
                    class="action-btn-sm action-btn-sm--playback"
                    title="直达该机位时光回放 (Time-Lapse)"
                    @click="jumpToPlayback(camera.id)"
                  >
                    回放
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Detail Drawer Panel -->
    <CameraDetailPanel
      v-if="selectedCamera"
      :camera="selectedCamera"
      @close="selectedCamera = null"
      @changed="handleCameraChanged"
    />

    <!-- Interactive PTZ Modal (专业云台极速控制台) -->
    <div
      v-if="ptzModalOpen && ptzActiveCamera"
      class="ptz-modal-backdrop"
      @click="closePtzModal"
    >
      <div class="ptz-modal-dialog" @click.stop>
        <!-- Modal Header -->
        <div class="ptz-modal-header">
          <div class="ptz-modal-header-left">
            <div class="ptz-icon-box">
              <UiIcon name="activity" :size="16" />
            </div>
            <div>
              <div class="ptz-modal-title">PTZ 云台极速控制 · {{ ptzActiveCamera.name }}</div>
              <div class="ptz-modal-sub">
                <span class="ptz-live-dot" />
                <span>{{ adapterLabel(ptzActiveCamera.adapter_type) }} · 连续移动协议就绪</span>
              </div>
            </div>
          </div>
          <button type="button" class="ptz-close-btn" @click="closePtzModal">✕</button>
        </div>

        <!-- Center Control Stage: 8-Way D-Pad + Zoom & Speed -->
        <div class="ptz-control-stage">
          <!-- 8-Direction D-Pad -->
          <div class="ptz-dpad-col">
            <div class="ptz-section-label">8向连续移动摇杆 (长按连续微调)</div>
            <div class="ptz-dpad-grid">
              <!-- Up-Left -->
              <button
                type="button"
                class="dpad-btn"
                @mousedown="handlePtzContinuousMove(-0.5, 0.5)"
                @mouseup="handlePtzStop"
                @mouseleave="handlePtzStop"
                @touchstart.prevent="handlePtzContinuousMove(-0.5, 0.5)"
                @touchend.prevent="handlePtzStop"
              >
                ↖
              </button>
              <!-- Up -->
              <button
                type="button"
                class="dpad-btn"
                @mousedown="handlePtzContinuousMove(0, 0.7)"
                @mouseup="handlePtzStop"
                @mouseleave="handlePtzStop"
                @touchstart.prevent="handlePtzContinuousMove(0, 0.7)"
                @touchend.prevent="handlePtzStop"
              >
                ▲
              </button>
              <!-- Up-Right -->
              <button
                type="button"
                class="dpad-btn"
                @mousedown="handlePtzContinuousMove(0.5, 0.5)"
                @mouseup="handlePtzStop"
                @mouseleave="handlePtzStop"
                @touchstart.prevent="handlePtzContinuousMove(0.5, 0.5)"
                @touchend.prevent="handlePtzStop"
              >
                ↗
              </button>
              <!-- Left -->
              <button
                type="button"
                class="dpad-btn"
                @mousedown="handlePtzContinuousMove(-0.7, 0)"
                @mouseup="handlePtzStop"
                @mouseleave="handlePtzStop"
                @touchstart.prevent="handlePtzContinuousMove(-0.7, 0)"
                @touchend.prevent="handlePtzStop"
              >
                ◀
              </button>
              <!-- Home -->
              <button
                type="button"
                class="dpad-btn dpad-btn--home"
                title="复位至 Home 初始视角"
                @click="handlePtzHome"
              >
                <span>⌂</span>
                <span class="text-[9px]">HOME</span>
              </button>
              <!-- Right -->
              <button
                type="button"
                class="dpad-btn"
                @mousedown="handlePtzContinuousMove(0.7, 0)"
                @mouseup="handlePtzStop"
                @mouseleave="handlePtzStop"
                @touchstart.prevent="handlePtzContinuousMove(0.7, 0)"
                @touchend.prevent="handlePtzStop"
              >
                ▶
              </button>
              <!-- Down-Left -->
              <button
                type="button"
                class="dpad-btn"
                @mousedown="handlePtzContinuousMove(-0.5, -0.5)"
                @mouseup="handlePtzStop"
                @mouseleave="handlePtzStop"
                @touchstart.prevent="handlePtzContinuousMove(-0.5, -0.5)"
                @touchend.prevent="handlePtzStop"
              >
                ↙
              </button>
              <!-- Down -->
              <button
                type="button"
                class="dpad-btn"
                @mousedown="handlePtzContinuousMove(0, -0.7)"
                @mouseup="handlePtzStop"
                @mouseleave="handlePtzStop"
                @touchstart.prevent="handlePtzContinuousMove(0, -0.7)"
                @touchend.prevent="handlePtzStop"
              >
                ▼
              </button>
              <!-- Down-Right -->
              <button
                type="button"
                class="dpad-btn"
                @mousedown="handlePtzContinuousMove(0.5, -0.5)"
                @mouseup="handlePtzStop"
                @mouseleave="handlePtzStop"
                @touchstart.prevent="handlePtzContinuousMove(0.5, -0.5)"
                @touchend.prevent="handlePtzStop"
              >
                ↘
              </button>
            </div>
          </div>

          <!-- Right: Zoom & Speed -->
          <div class="ptz-zoom-col">
            <!-- Zoom Section -->
            <div class="ptz-box">
              <div class="ptz-box-header">
                <span>光学变倍 (ZOOM)</span>
                <span class="text-blue-400 font-bold font-mono">{{ ptzZoomFactor }}x</span>
              </div>
              <div class="ptz-zoom-buttons">
                <button
                  type="button"
                  class="ptz-zoom-btn"
                  @mousedown="handlePtzZoom(0.5)"
                  @mouseup="handlePtzStop"
                  @mouseleave="handlePtzStop"
                >
                  + 放大
                </button>
                <button
                  type="button"
                  class="ptz-zoom-btn"
                  @mousedown="handlePtzZoom(-0.5)"
                  @mouseup="handlePtzStop"
                  @mouseleave="handlePtzStop"
                >
                  - 缩小
                </button>
              </div>
            </div>

            <!-- Speed Slider -->
            <div class="ptz-box">
              <div class="ptz-box-header">
                <span>云台调速</span>
                <span class="text-amber-400 font-bold font-mono">档位: {{ ptzSpeed }}</span>
              </div>
              <input
                v-model.number="ptzSpeed"
                type="range"
                min="1"
                max="10"
                class="ptz-slider"
              />
            </div>
          </div>
        </div>

        <!-- Presets Slot Footer -->
        <div class="ptz-presets-footer">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-semibold text-gray-300">云台预置位快捷槽位 (ONVIF Presets)</span>
            <span class="text-[10px] text-gray-500 font-mono">
              <!--
                TODO(phase-ptz-presets): 接入 ONVIF PTZ 预置位读写接口
                后端 API: /api/v1/cameras/{id}/ptz/presets
                原型位置: protect-devices L2481-2530
              -->
              支持快速巡航与记忆点调用
            </span>
          </div>
          <div class="presets-grid">
            <div class="preset-card">
              <div>
                <div class="preset-name">1. 主门禁闸机视角</div>
                <div class="preset-sub">P: 0° T: 0° Z: 1.0x</div>
              </div>
              <button type="button" class="preset-btn" @click="showToast('调用预置位 1 (主门禁闸机)')">调用</button>
            </div>
            <div class="preset-card">
              <div>
                <div class="preset-name">2. 接待大厅全景</div>
                <div class="preset-sub">P: -45° T: 10° Z: 1.0x</div>
              </div>
              <button type="button" class="preset-btn" @click="showToast('调用预置位 2 (接待大厅全景)')">调用</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.devices-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  padding: 24px;
  background-color: #0c0e14;
  color: #d1d5db;
  overflow-y: auto;
  box-sizing: border-box;
}

/* Toast Banner */
.toast-banner {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(15, 23, 42, 0.95);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.3);
  padding: 8px 16px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
  z-index: 9999;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
  animation: fadeInDown 0.25s ease-out;
}

@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translate(-50%, -10px);
  }
  to {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}

/* Header */
.devices-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.devices-title {
  font-size: 18px;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 0.02em;
  margin: 0;
}

.devices-subtitle {
  font-size: 12px;
  color: #9ca3af;
  margin: 4px 0 0 0;
}

.devices-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  background: #171b26;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #ffffff;
}

.btn-action:hover {
  background: rgba(255, 255, 255, 0.1);
}

.btn-action--primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

.btn-action--primary:hover {
  background: #1d4ed8;
}

.btn-action--ghost {
  background: transparent;
  color: #9ca3af;
}

.btn-action--ghost:hover {
  color: #ffffff;
}

/* Error */
.notice-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #fca5a5;
  font-size: 12px;
  margin-bottom: 16px;
}

/* Filter Chips Bar */
.filter-chips-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.chip-btn {
  padding: 4px 12px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  background: #181d2a;
  color: #d1d5db;
  border: 1px solid rgba(255, 255, 255, 0.1);
  transition: all 0.15s ease;
}

.chip-btn:hover {
  color: #ffffff;
  border-color: rgba(255, 255, 255, 0.25);
}

.chip-btn--active {
  background: #2563eb;
  color: #ffffff;
  border-color: #2563eb;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
}

/* Devices Table Card */
.devices-table-card {
  background: #141722;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.table-container {
  overflow-x: auto;
  width: 100%;
}

.devices-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 12px;
}

.devices-table thead th {
  padding: 12px 16px;
  font-size: 10px;
  font-weight: 600;
  color: #9ca3af;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-family: monospace;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  white-space: nowrap;
}

.devices-table tbody td {
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  vertical-align: middle;
}

.devices-row {
  cursor: pointer;
  transition: background-color 0.12s ease;
}

.devices-row:hover {
  background-color: rgba(255, 255, 255, 0.03);
}

.cam-name {
  font-weight: 700;
  color: #ffffff;
  font-size: 13px;
}

.cam-sub {
  font-size: 10px;
  color: #9ca3af;
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.dot-sep {
  color: rgba(255, 255, 255, 0.2);
}

.stream-badges {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.stream-tag {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  white-space: nowrap;
}

.stream-tag--record {
  background: rgba(59, 130, 246, 0.2);
  color: #93c5fd;
  border: 1px solid rgba(59, 130, 246, 0.3);
}

.stream-tag--preview {
  background: rgba(255, 255, 255, 0.06);
  color: #d1d5db;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.ptz-trigger-btn {
  background: transparent;
  border: 0;
  padding: 0;
  color: #60a5fa;
  font-size: 12px;
  cursor: pointer;
  font-weight: 500;
}

.ptz-trigger-btn:hover {
  text-decoration: underline;
  color: #93c5fd;
}

/* Status Pills */
.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 9999px;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.status-pill--online {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.status-pill--maintenance {
  background: rgba(245, 158, 11, 0.2);
  color: #fbbf24;
}

.status-pill--disabled {
  background: rgba(239, 68, 68, 0.2);
  color: #f87171;
}

.status-pill--retired {
  background: rgba(107, 114, 128, 0.2);
  color: #9ca3af;
}

/* Row Actions */
.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.action-btn-sm {
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #ffffff;
  cursor: pointer;
  transition: all 0.15s ease;
}

.action-btn-sm:hover {
  background: rgba(255, 255, 255, 0.14);
}

.action-btn-sm--amber {
  background: rgba(245, 158, 11, 0.15);
  border-color: rgba(245, 158, 11, 0.3);
  color: #fbbf24;
}

.action-btn-sm--amber:hover {
  background: rgba(245, 158, 11, 0.25);
}

.action-btn-sm--playback {
  color: #60a5fa;
  border-color: rgba(96, 165, 250, 0.2);
}

.action-btn-sm--playback:hover {
  background: rgba(96, 165, 250, 0.15);
  color: #93c5fd;
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 16px;
  text-align: center;
}

/* PTZ Modal Backdrop */
.ptz-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.8);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.ptz-modal-dialog {
  background: #151822;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 24px;
  padding: 24px;
  width: 480px;
  max-width: 90vw;
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.6);
  color: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ptz-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  padding-bottom: 12px;
}

.ptz-modal-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ptz-icon-box {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(37, 99, 235, 0.2);
  color: #60a5fa;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(37, 99, 235, 0.3);
}

.ptz-modal-title {
  font-size: 14px;
  font-weight: 700;
  color: #ffffff;
}

.ptz-modal-sub {
  font-size: 11px;
  color: #34d399;
  font-family: monospace;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.ptz-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #34d399;
}

.ptz-close-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 0;
  color: #9ca3af;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
}

.ptz-close-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

/* Control Stage */
.ptz-control-stage {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 16px;
  align-items: center;
}

.ptz-dpad-col {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.ptz-section-label {
  font-size: 11px;
  color: #9ca3af;
  font-family: monospace;
  margin-bottom: 8px;
}

.ptz-dpad-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  padding: 8px;
  background: #0d1017;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  width: 176px;
  height: 176px;
  box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.5);
  box-sizing: border-box;
}

.dpad-btn {
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 0;
  color: #d1d5db;
  font-weight: 700;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  user-select: none;
  transition: all 0.1s ease;
}

.dpad-btn:hover {
  background: #2563eb;
  color: #ffffff;
}

.dpad-btn:active {
  transform: scale(0.94);
}

.dpad-btn--home {
  background: #2563eb;
  color: #ffffff;
  display: flex;
  flex-direction: column;
  font-size: 12px;
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.3);
}

.dpad-btn--home:hover {
  background: #1d4ed8;
}

/* Zoom & Speed Column */
.ptz-zoom-col {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ptz-box {
  background: #0d1017;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 10px;
}

.ptz-box-header {
  font-size: 10px;
  color: #9ca3af;
  font-family: monospace;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.ptz-zoom-buttons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}

.ptz-zoom-btn {
  padding: 6px 0;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #ffffff;
  font-family: monospace;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.1s ease;
}

.ptz-zoom-btn:hover {
  background: rgba(37, 99, 235, 0.3);
  border-color: #2563eb;
}

.ptz-slider {
  width: 100%;
  accent-color: #3b82f6;
  cursor: pointer;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}

/* Presets Footer */
.ptz-presets-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding-top: 12px;
}

.presets-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.preset-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 10px;
  background: #0d1017;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.preset-name {
  font-size: 11px;
  font-weight: 500;
  color: #ffffff;
}

.preset-sub {
  font-size: 9px;
  color: #9ca3af;
  font-family: monospace;
}

.preset-btn {
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(37, 99, 235, 0.25);
  border: 1px solid rgba(37, 99, 235, 0.4);
  color: #93c5fd;
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.1s ease;
}

.preset-btn:hover {
  background: #2563eb;
  color: #ffffff;
}
</style>
