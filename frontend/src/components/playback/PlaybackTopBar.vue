<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"

import type { CameraSummary } from "../../api/cameras"
import UiIcon from "../ui/UiIcon.vue"

type ZoomHours = 1 | 6 | 24

defineProps<{
  cameras: CameraSummary[]
  activeCameraId: string | null
  activeCameraName: string | null
  isToday: boolean
  syncMode: "tolerant" | "strict"
  zoomHours: ZoomHours
  zoomOptions: ZoomHours[]
  fullscreen: boolean
}>()

const cameraPanelOpen = defineModel<boolean>("cameraPanelOpen", { required: true })
const selectedDate = defineModel<string>("selectedDate", { required: true })

const emit = defineEmits<{
  "select-camera": [cameraId: string]
  "shift-day": [delta: number]
  "date-change": []
  "select-today": []
  "set-sync-mode": [mode: "tolerant" | "strict"]
  "go-to-files": []
  "set-zoom": [hours: ZoomHours]
  "toggle-fullscreen": []
}>()

const { t } = useI18n({ useScope: "global" })
const cameraDropdownOpen = ref(false)
const datePickerPopoverOpen = ref(false)

function togglePlaybackCameraDropdown(): void {
  cameraDropdownOpen.value = !cameraDropdownOpen.value
  if (cameraDropdownOpen.value) datePickerPopoverOpen.value = false
}

function togglePlaybackDatePicker(): void {
  datePickerPopoverOpen.value = !datePickerPopoverOpen.value
  if (datePickerPopoverOpen.value) cameraDropdownOpen.value = false
}

function selectPlaybackCamera(cameraId: string): void {
  emit("select-camera", cameraId)
  cameraDropdownOpen.value = false
}
</script>

<template>
  <header class="playback-unifi-topbar">
    <div class="topbar-left">
      <!-- View Title -->
      <div class="topbar-title-tag">
        <span class="blue-dot" />
        <span>时光回放 (Playback)</span>
      </div>

      <div class="topbar-divider" />

      <!-- Camera Selector Dropdown Pill (UniFi 机位选择器) -->
      <div class="relative-container">
        <button
          class="topbar-pill-btn"
          type="button"
          title="切换回放摄像机"
          @click="togglePlaybackCameraDropdown"
        >
          <span class="green-live-dot pulse-live" />
          <span class="pill-camera-name">{{ activeCameraName || t("playback.title") }}</span>
          <svg class="chevron-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        <!-- Camera Dropdown Menu -->
        <div v-if="cameraDropdownOpen" class="topbar-popover camera-dropdown-popover">
          <div class="popover-heading">选择回放机位 (Cameras)</div>
          <div class="popover-cam-list">
            <button
              v-for="camera in cameras"
              :key="camera.id"
              class="popover-cam-item"
              :class="{ 'popover-cam-item--active': activeCameraId === camera.id }"
              type="button"
              @click="selectPlaybackCamera(camera.id)"
            >
              <div class="popover-cam-left">
                <span class="cam-status-dot" :class="{ 'cam-status-dot--on': camera.enabled }" />
                <span class="cam-name">{{ camera.name }}</span>
              </div>
              <span class="cam-tag">{{ camera.adapter_type || "RTSP" }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Multi-camera Sync Panel Drawer Toggle -->
      <button
        class="topbar-icon-btn"
        type="button"
        :class="{ 'topbar-icon-btn--active': cameraPanelOpen }"
        :title="cameraPanelOpen ? t('playback.hideCameras') : '打开多机位同步面板'"
        @click="cameraPanelOpen = !cameraPanelOpen"
      >
        <UiIcon name="panel" :size="14" />
      </button>

      <div class="topbar-divider" />

      <!-- Date Selector Pill (UniFi 日期选择与切换) -->
      <div class="date-selector-group">
        <button
          class="date-nav-btn"
          type="button"
          title="前一天"
          @click="emit('shift-day', -1)"
        >
          <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        <div class="relative-container">
          <button
            class="topbar-pill-btn date-pill-btn"
            type="button"
            title="点击选择回放日期"
            @click="togglePlaybackDatePicker"
          >
            <UiIcon name="calendar" :size="13" class="text-blue" />
            <span class="date-label">{{ selectedDate }} {{ isToday ? "(今天)" : "" }}</span>
            <svg class="chevron-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          <!-- Datepicker Popover -->
          <div v-if="datePickerPopoverOpen" class="topbar-popover date-popover">
            <div class="popover-heading flex-between">
              <span>选择回放日期</span>
              <div class="quick-date-actions">
                <button
                  type="button"
                  class="quick-date-btn"
                  @click="emit('select-today'); datePickerPopoverOpen = false"
                >
                  今天
                </button>
                <button
                  type="button"
                  class="quick-date-btn"
                  @click="emit('shift-day', -1); datePickerPopoverOpen = false"
                >
                  昨天
                </button>
                <button type="button" class="popover-close-btn" @click="datePickerPopoverOpen = false"><UiIcon name="close" :size="12" /></button>
              </div>
            </div>
            <div class="date-input-wrap">
              <input
                v-model="selectedDate"
                type="date"
                class="native-date-input"
                @change="emit('date-change'); datePickerPopoverOpen = false"
              />
            </div>
          </div>
        </div>

        <button
          class="date-nav-btn"
          type="button"
          :disabled="isToday"
          title="后一天"
          @click="emit('shift-day', 1)"
        >
          <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      <div class="topbar-divider" />

      <!-- Sync Mode Switcher (Tolerant vs Strict) -->
      <div class="sync-mode-pill">
        <button
          class="sync-btn"
          :class="{ 'sync-btn--active': syncMode === 'tolerant' }"
          type="button"
          @click="emit('set-sync-mode', 'tolerant')"
        >
          {{ t("playback.tolerant") }}
        </button>
        <button
          class="sync-btn"
          :class="{ 'sync-btn--active': syncMode === 'strict' }"
          type="button"
          @click="emit('set-sync-mode', 'strict')"
        >
          {{ t("playback.strict") }}
        </button>
      </div>
    </div>

    <div class="topbar-right">
      <!-- Jump to File Manager -->
      <button
        class="action-pill-btn"
        type="button"
        title="在录像文件中心查看与管理当前片段"
        @click="emit('go-to-files')"
      >
        <UiIcon name="folder" :size="13" class="text-blue" />
        <span>管理当前文件</span>
      </button>


      <!-- Zoom Switcher -->
      <div class="zoom-pill">
        <button
          v-for="hours in zoomOptions"
          :key="hours"
          class="zoom-btn"
          :class="{ 'zoom-btn--active': zoomHours === hours }"
          type="button"
          @click="emit('set-zoom', hours)"
        >
          {{ hours }}h
        </button>
      </div>

      <!-- Fullscreen Toggle -->
      <button
        class="topbar-icon-btn"
        type="button"
        :title="fullscreen ? t('playback.exitFullscreen') : t('playback.fullscreenPlayback')"
        @click="emit('toggle-fullscreen')"
      >
        <UiIcon :name="fullscreen ? 'minimize' : 'maximize'" :size="14" />
      </button>
    </div>
  </header>
</template>

<style scoped>
/* ===== UniFi Protect Top Time-Lapse Control Header ===== */
.playback-unifi-topbar {
  /* Height is content-driven: at narrow widths the control groups wrap to a
     second row instead of squeezing buttons into vertical strips. Popovers
     stay unclipped, so overflow-x scrolling is not an option here. */
  min-height: 48px;
  background-color: var(--uf-bg-header);
  border-bottom: 1px solid var(--uf-border);
  padding: 6px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  row-gap: 4px;
  flex-shrink: 0;
  z-index: 30;
  user-select: none;
}

.topbar-left,
.topbar-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  row-gap: 4px;
  gap: 10px;
  min-width: 0;
}

/* Controls keep their natural width and let the group wrap between items;
   shrinking them is what produced the per-character vertical text strips. */
.topbar-left > *,
.topbar-right > * {
  flex-shrink: 0;
}

.topbar-title-tag,
.topbar-pill-btn,
.topbar-icon-btn,
.sync-btn,
.action-pill-btn,
.zoom-btn,
.quick-date-btn {
  white-space: nowrap;
}

.topbar-title-tag {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--uf-text-primary);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.blue-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: var(--uf-accent);
  box-shadow: 0 0 8px var(--uf-accent-glow);
}

.topbar-divider {
  width: 1px;
  height: 16px;
  background: var(--uf-border);
}

.relative-container {
  position: relative;
}

.topbar-pill-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-radius: 10px;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border-strong);
  color: var(--uf-text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.topbar-pill-btn:hover {
  border-color: var(--uf-accent);
  background: var(--uf-bg-hover);
}

.green-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: #10b981;
}

.pulse-live {
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.8);
}

.pill-camera-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chevron-icon {
  color: var(--uf-text-muted);
  flex-shrink: 0;
}

.topbar-icon-btn {
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  cursor: pointer;
  padding: 6px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.topbar-icon-btn:hover {
  color: var(--uf-text-primary);
  background: var(--uf-bg-hover);
}

.topbar-icon-btn--active {
  color: var(--text-on-accent);
  background: var(--uf-accent);
  border-color: var(--uf-accent);
}

.date-selector-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.date-nav-btn {
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  padding: 6px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.12s ease;
}

.date-nav-btn:hover:not(:disabled) {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.date-nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.date-pill-btn {
  font-family: var(--font-mono);
  font-size: 11px;
}

.sync-mode-pill {
  display: flex;
  align-items: center;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  border-radius: 8px;
  padding: 2px;
}

.sync-btn {
  background: transparent;
  border: none;
  color: var(--uf-text-muted);
  font-size: 11px;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.sync-btn:hover {
  color: var(--uf-text-primary);
}

.sync-btn--active {
  background: var(--uf-accent);
  color: var(--text-on-accent);
}

.action-pill-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 8px;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.action-pill-btn:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.action-pill-btn--active {
  background: var(--uf-accent-soft);
  border-color: var(--uf-accent);
  color: var(--uf-accent);
}

.action-pill-btn--amber {
  background: rgba(245, 158, 11, 0.15);
  border-color: rgba(245, 158, 11, 0.35);
  color: #f59e0b;
}

.action-pill-btn--amber:hover {
  background: rgba(245, 158, 11, 0.25);
  color: #f59e0b;
}

.action-pill-btn--blue {
  background: var(--uf-accent);
  border-color: var(--uf-accent);
  color: var(--text-on-accent);
  box-shadow: 0 2px 10px var(--uf-accent-glow);
}

.action-pill-btn--blue:hover {
  background: var(--uf-accent-hover);
}

.zoom-pill {
  display: flex;
  align-items: center;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  border-radius: 8px;
  padding: 2px;
}

.zoom-btn {
  background: transparent;
  border: none;
  color: var(--uf-text-muted);
  font-size: 10px;
  font-family: var(--font-mono);
  font-weight: 600;
  padding: 3px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.zoom-btn:hover {
  color: var(--uf-text-primary);
}

.zoom-btn--active {
  background: var(--uf-accent);
  color: var(--text-on-accent);
}

.text-blue {
  color: var(--uf-accent) !important;
}

.text-amber {
  color: #f59e0b !important;
}

/* Popover menus */
.topbar-popover {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  border-radius: 14px;
  box-shadow: var(--uf-shadow-lg);
  padding: 10px;
  z-index: 50;
  font-size: 12px;
}

.camera-dropdown-popover {
  width: 280px;
}

.date-popover {
  width: 280px;
}

.popover-heading {
  font-size: 10px;
  font-family: var(--font-mono);
  text-transform: uppercase;
  color: var(--uf-text-muted);
  letter-spacing: 0.05em;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--uf-border-subtle);
  margin-bottom: 6px;
}

.flex-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.popover-cam-list {
  max-height: 280px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.popover-cam-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  border-radius: 8px;
  background: transparent;
  border: none;
  color: var(--uf-text-secondary);
  cursor: pointer;
  text-align: left;
  transition: all 0.12s ease;
}

.popover-cam-item:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.popover-cam-item--active {
  background: var(--uf-accent-soft) !important;
  color: var(--uf-accent) !important;
}

.popover-cam-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.cam-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--uf-text-muted);
  flex-shrink: 0;
}

.cam-status-dot--on {
  background-color: #10b981;
}

.cam-name {
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cam-tag {
  font-size: 10px;
  color: var(--uf-accent);
  font-family: var(--font-mono);
}

.quick-date-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.quick-date-btn {
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
}

.quick-date-btn:hover {
  background: var(--uf-accent);
  color: var(--text-on-accent);
}

.popover-close-btn {
  background: transparent;
  border: none;
  color: var(--uf-text-muted);
  cursor: pointer;
  padding: 0 4px;
}

.popover-close-btn:hover {
  color: var(--uf-text-primary);
}

.date-input-wrap {
  padding-top: 4px;
}

.native-date-input {
  width: 100%;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border-strong);
  border-radius: 8px;
  padding: 6px 10px;
  color: var(--uf-text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  outline: none;
}

.native-date-input:focus {
  border-color: var(--uf-accent);
}
</style>
