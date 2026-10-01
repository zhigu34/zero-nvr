<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  watch
} from "vue"
import { useI18n } from "vue-i18n"

import { useFullscreen } from "../composables/useFullscreen"

import { useGlobalRefresh } from "../composables/useGlobalRefresh"

import {
  listCameras,
  type CameraSummary
} from "../api/cameras"
import { errorMessage } from "../api/client"
import {
  createLiveViewLayout,
  deleteLiveViewLayout,
  listLiveViewLayouts,
  updateLiveViewLayout,
  type LiveLayoutSlots,
  type LiveQuality,
  type LiveViewLayout,
  type LiveViewLayoutState
} from "../api/live"
import LiveCameraTile from "../components/live/LiveCameraTile.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import {
  createLivePreviewWallClient,
  type PreviewGridSlots
} from "../live/previewWall"
import { useAuthStore } from "../stores/auth"

import { confirmAction } from "../composables/useConfirm"
import { useAsyncResource } from "../composables/useAsyncResource"

// These prompts all remove or irreversibly change stored data, so the
// dialog styles the accept action as destructive.
const confirmDestroy = (message: string) =>
  confirmAction({ message, danger: true })

interface NetworkInformationLike extends EventTarget {
  saveData?: boolean
  effectiveType?: string
  downlink?: number
  rtt?: number
}

const auth = useAuthStore()
const { loading, error, run } = useAsyncResource()
const { t } = useI18n({ useScope: "global" })
const previewWall = createLivePreviewWallClient()
const layoutOptions: LiveLayoutSlots[] = [1, 4, 9, 16]
const workspace = ref<HTMLElement | null>(null)
const cameras = ref<CameraSummary[]>([])
const selectedIds = ref<string[]>([])
const playingIds = ref<string[]>([])
const layoutSlots = ref<LiveLayoutSlots>(4)
const focusedCameraId = ref<string | null>(null)
const cameraPanelOpen = ref(false)
const search = ref("")
const cameraFilter = ref<"all" | "selected">("all")
const draggingCameraId = ref<string | null>(null)
const fullscreen = ref(false)
const networkConstrained = ref(false)

const savedLayouts = ref<LiveViewLayout[]>([])
const activeLayoutId = ref<string | null>(null)
const layoutBusy = ref(false)
const layoutCreateOpen = ref(false)
const layoutNameDraft = ref("")
const layoutNotice = ref<string | null>(null)
const presetsPopoverOpen = ref(false)
const qualityPopoverOpen = ref(false)

function togglePresetsPopover(): void {
  presetsPopoverOpen.value = !presetsPopoverOpen.value
  if (presetsPopoverOpen.value) qualityPopoverOpen.value = false
}

function toggleQualityPopover(): void {
  qualityPopoverOpen.value = !qualityPopoverOpen.value
  if (qualityPopoverOpen.value) presetsPopoverOpen.value = false
}

let layoutsInitialized = false
let layoutNoticeTimer: number | null = null
let networkDowngradeTimer: number | null = null
let networkUpgradeTimer: number | null = null

const enabledCameras = computed(() =>
  cameras.value.filter((camera) => camera.enabled)
)

const filteredCameras = computed(() => {
  const source =
    cameraFilter.value === "selected"
      ? cameras.value.filter((camera) =>
          selectedIds.value.includes(camera.id)
        )
      : cameras.value

  const needle = search.value.trim().toLowerCase()
  if (!needle) return source

  return source.filter((camera) =>
    [camera.name, camera.location, camera.adapter_type]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(needle))
  )
})

const selectedCameras = computed(() => {
  const byId = new Map(
    cameras.value.map((camera) => [camera.id, camera])
  )
  return selectedIds.value
    .map((id) => byId.get(id))
    .filter((camera): camera is CameraSummary => Boolean(camera))
})

const visibleCameras = computed(() => {
  if (focusedCameraId.value) {
    const camera = cameras.value.find(
      (item) => item.id === focusedCameraId.value
    )
    return camera ? [camera] : []
  }

  return selectedCameras.value.slice(0, layoutSlots.value)
})

const emptySlots = computed(() =>
  focusedCameraId.value
    ? 0
    : Math.max(0, layoutSlots.value - visibleCameras.value.length)
)

const visibleCameraCount = computed(() =>
  focusedCameraId.value
    ? visibleCameras.value.length
    : Math.min(
        selectedCameras.value.length,
        layoutSlots.value
      )
)

const visiblePlayingCount = computed(() => {
  const visibleIds = new Set(
    visibleCameras.value.map((camera) => camera.id)
  )
  return playingIds.value.filter((id) =>
    visibleIds.has(id)
  ).length
})

const gridColumns = computed(() => {
  if (focusedCameraId.value || layoutSlots.value === 1) return 1
  if (layoutSlots.value === 4) return 2
  if (layoutSlots.value === 9) return 3
  return 4
})

const streamQuality = computed<LiveQuality>(() => {
  if (networkConstrained.value) return "low"
  return focusedCameraId.value || layoutSlots.value === 1
    ? "high"
    : "low"
})

const highQualityAllowed = computed(
  () => !networkConstrained.value
)

const previewWallLayout = computed<PreviewGridSlots | null>(() => {
  if (focusedCameraId.value || layoutSlots.value === 1) return null
  return layoutSlots.value
})

watch(
  previewWallLayout,
  (slots) => previewWall.setLayout(slots),
  { immediate: true }
)

const activeLayout = computed(() =>
  savedLayouts.value.find(
    (layout) => layout.id === activeLayoutId.value
  ) ?? null
)

const activePresetLabel = computed(() => {
  if (activeLayout.value) {
    return activeLayout.value.name
  }
  return t("live.viewCount", { count: layoutSlots.value })
})

function currentLayoutState(): LiveViewLayoutState {
  return {
    slots: layoutSlots.value,
    camera_ids: selectedIds.value.slice(0, 16),
    camera_panel_open: cameraPanelOpen.value
  }
}

function layoutStateEquals(
  left: LiveViewLayoutState,
  right: LiveViewLayoutState
): boolean {
  return (
    left.slots === right.slots &&
    left.camera_panel_open === right.camera_panel_open &&
    left.camera_ids.length === right.camera_ids.length &&
    left.camera_ids.every(
      (cameraId, index) => cameraId === right.camera_ids[index]
    )
  )
}

const layoutDirty = computed(() => {
  const layout = activeLayout.value
  if (!layout) return false
  return !layoutStateEquals(
    currentLayoutState(),
    layout.layout
  )
})

function showLayoutNotice(message: string): void {
  if (layoutNoticeTimer !== null) {
    window.clearTimeout(layoutNoticeTimer)
  }
  layoutNotice.value = message
  layoutNoticeTimer = window.setTimeout(() => {
    layoutNotice.value = null
    layoutNoticeTimer = null
  }, 1800)
}

function networkInformation(): NetworkInformationLike | null {
  const candidate = (
    navigator as Navigator & {
      connection?: NetworkInformationLike
      mozConnection?: NetworkInformationLike
      webkitConnection?: NetworkInformationLike
    }
  )
  return (
    candidate.connection ??
    candidate.mozConnection ??
    candidate.webkitConnection ??
    null
  )
}

function clearNetworkTimers(): void {
  if (networkDowngradeTimer !== null) {
    window.clearTimeout(networkDowngradeTimer)
    networkDowngradeTimer = null
  }
  if (networkUpgradeTimer !== null) {
    window.clearTimeout(networkUpgradeTimer)
    networkUpgradeTimer = null
  }
}

function networkLooksConstrained(
  info: NetworkInformationLike
): boolean {
  return Boolean(
    info.saveData ||
    info.effectiveType === "slow-2g" ||
    info.effectiveType === "2g" ||
    (
      typeof info.downlink === "number" &&
      info.downlink > 0 &&
      info.downlink < 2
    ) ||
    (
      typeof info.rtt === "number" &&
      info.rtt > 500
    )
  )
}

function networkLooksRecovered(
  info: NetworkInformationLike
): boolean {
  if (info.saveData) return false
  if (
    info.effectiveType === "slow-2g" ||
    info.effectiveType === "2g"
  ) {
    return false
  }
  if (
    typeof info.downlink === "number" &&
    info.downlink > 0 &&
    info.downlink < 4
  ) {
    return false
  }
  if (
    typeof info.rtt === "number" &&
    info.rtt > 300
  ) {
    return false
  }
  return true
}

function evaluateNetworkQuality(
  immediate = false
): void {
  const info = networkInformation()
  if (!info) return

  if (networkLooksConstrained(info)) {
    if (networkUpgradeTimer !== null) {
      window.clearTimeout(networkUpgradeTimer)
      networkUpgradeTimer = null
    }
    if (networkConstrained.value) return
    if (networkDowngradeTimer !== null) return

    const apply = () => {
      networkDowngradeTimer = null
      networkConstrained.value = true
    }
    if (immediate) {
      apply()
    } else {
      networkDowngradeTimer = window.setTimeout(
        apply,
        1500
      )
    }
    return
  }

  if (networkDowngradeTimer !== null) {
    window.clearTimeout(networkDowngradeTimer)
    networkDowngradeTimer = null
  }
  if (
    !networkConstrained.value ||
    !networkLooksRecovered(info) ||
    networkUpgradeTimer !== null
  ) {
    return
  }

  networkUpgradeTimer = window.setTimeout(() => {
    networkUpgradeTimer = null
    const latest = networkInformation()
    if (
      latest &&
      networkLooksRecovered(latest)
    ) {
      networkConstrained.value = false
    }
  }, 8000)
}

function handleNetworkChange(): void {
  evaluateNetworkQuality(false)
}

function initializeSelection(): void {
  const validIds = new Set(
    cameras.value
      .filter((camera) => camera.enabled)
      .map((camera) => camera.id)
  )
  selectedIds.value = selectedIds.value.filter(
    (id) => validIds.has(id)
  )

  playingIds.value = playingIds.value.filter((id) =>
    validIds.has(id) && selectedIds.value.includes(id)
  )

  if (
    focusedCameraId.value &&
    !validIds.has(focusedCameraId.value)
  ) {
    focusedCameraId.value = null
  }
}

function applyLayout(layout: LiveViewLayout): void {
  const enabledIds = new Set(
    enabledCameras.value.map((camera) => camera.id)
  )
  layoutSlots.value = layout.layout.slots
  selectedIds.value = layout.layout.camera_ids.filter(
    (cameraId) => enabledIds.has(cameraId)
  )
  playingIds.value = []
  cameraPanelOpen.value = layout.layout.camera_panel_open
  focusedCameraId.value = null
  activeLayoutId.value = layout.id
}

async function refresh(): Promise<void> {
  if (!auth.hasPermission("camera.view")) return

  await run(async () => {
    const [nextCameras, nextLayouts] = await Promise.all([
      listCameras(),
      listLiveViewLayouts()
    ])
    cameras.value = nextCameras
    savedLayouts.value = nextLayouts

    if (
      activeLayoutId.value &&
      !nextLayouts.some(
        (layout) => layout.id === activeLayoutId.value
      )
    ) {
      activeLayoutId.value = null
    }

    if (!layoutsInitialized) {
      const defaultLayout = nextLayouts.find(
        (layout) => layout.is_default
      )
      if (defaultLayout) {
        applyLayout(defaultLayout)
      } else {
        initializeSelection()
      }
      layoutsInitialized = true
    } else {
      initializeSelection()
    }
  })
}

function toggleCamera(camera: CameraSummary): void {
  if (!camera.enabled) return

  const exists = selectedIds.value.includes(camera.id)
  if (exists) {
    selectedIds.value = selectedIds.value.filter(
      (id) => id !== camera.id
    )
    playingIds.value = playingIds.value.filter(
      (id) => id !== camera.id
    )
    if (focusedCameraId.value === camera.id) {
      focusedCameraId.value = null
    }
    return
  }

  selectedIds.value = [camera.id, ...selectedIds.value].slice(0, 16)
}

function fillGrid(): void {
  const selected = selectedIds.value.filter((id) =>
    enabledCameras.value.some((camera) => camera.id === id)
  )
  const selectedSet = new Set(selected)

  for (const camera of enabledCameras.value) {
    if (selected.length >= layoutSlots.value) break
    if (selectedSet.has(camera.id)) continue
    selected.push(camera.id)
    selectedSet.add(camera.id)
  }

  selectedIds.value = selected.slice(0, 16)
  focusedCameraId.value = null
}

function clearGrid(): void {
  selectedIds.value = []
  playingIds.value = []
  focusedCameraId.value = null
}

function setCameraPlayback(
  cameraId: string,
  enabled: boolean
): void {
  if (
    enabled &&
    selectedIds.value.includes(cameraId)
  ) {
    playingIds.value = Array.from(
      new Set([...playingIds.value, cameraId])
    )
    return
  }

  playingIds.value = playingIds.value.filter(
    (id) => id !== cameraId
  )
}

function startVisibleCameras(): void {
  const visibleIds = visibleCameras.value.map(
    (camera) => camera.id
  )
  playingIds.value = Array.from(
    new Set([...playingIds.value, ...visibleIds])
  )
}

function stopVisibleCameras(): void {
  const visibleIds = new Set(
    visibleCameras.value.map((camera) => camera.id)
  )
  playingIds.value = playingIds.value.filter(
    (id) => !visibleIds.has(id)
  )
}

function cameraSlotNumber(cameraId: string): number | null {
  const index = selectedIds.value.indexOf(cameraId)
  return index >= 0 ? index + 1 : null
}

function handleCameraDragStart(
  camera: CameraSummary,
  event: DragEvent
): void {
  if (
    !camera.enabled ||
    !selectedIds.value.includes(camera.id)
  ) {
    event.preventDefault()
    return
  }

  draggingCameraId.value = camera.id
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move"
    event.dataTransfer.setData("text/plain", camera.id)
  }
}

function handleCameraDragEnd(): void {
  draggingCameraId.value = null
}

function dropCameraBefore(targetCameraId: string): void {
  const sourceCameraId = draggingCameraId.value
  if (
    !sourceCameraId ||
    sourceCameraId === targetCameraId
  ) {
    draggingCameraId.value = null
    return
  }

  const next = [...selectedIds.value]
  const sourceIndex = next.indexOf(sourceCameraId)
  const targetIndex = next.indexOf(targetCameraId)
  if (sourceIndex < 0 || targetIndex < 0) {
    draggingCameraId.value = null
    return
  }

  next.splice(sourceIndex, 1)
  const adjustedTarget = next.indexOf(targetCameraId)
  next.splice(adjustedTarget, 0, sourceCameraId)
  selectedIds.value = next
  draggingCameraId.value = null
}

function openCameraPicker(): void {
  cameraPanelOpen.value = true
  cameraFilter.value = "all"
}

function focusCamera(cameraId: string): void {
  if (focusedCameraId.value === cameraId) {
    focusedCameraId.value = null
    return
  }

  if (!selectedIds.value.includes(cameraId)) {
    selectedIds.value = [cameraId, ...selectedIds.value].slice(0, 16)
  }
  focusedCameraId.value = cameraId
}

function setLayout(slots: LiveLayoutSlots): void {
  layoutSlots.value = slots
  focusedCameraId.value = null
  const stillVisible = new Set(
    selectedIds.value.slice(0, slots)
  )
  playingIds.value = playingIds.value.filter(
    (id) => stillVisible.has(id)
  )
}

function handleLayoutSelection(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (!value) {
    activeLayoutId.value = null
    return
  }
  const layout = savedLayouts.value.find(
    (item) => item.id === value
  )
  if (layout) applyLayout(layout)
}

function beginLayoutCreate(): void {
  layoutNameDraft.value = ""
  layoutCreateOpen.value = true
}

function cancelLayoutCreate(): void {
  layoutCreateOpen.value = false
  layoutNameDraft.value = ""
}

async function createCurrentLayout(): Promise<void> {
  const name = layoutNameDraft.value.trim()
  if (!name || layoutBusy.value) return

  layoutBusy.value = true
  error.value = null
  try {
    const created = await createLiveViewLayout({
      name,
      is_default: savedLayouts.value.length === 0,
      layout: currentLayoutState()
    })
    savedLayouts.value = await listLiveViewLayouts()
    applyLayout(
      savedLayouts.value.find(
        (layout) => layout.id === created.id
      ) ?? created
    )
    cancelLayoutCreate()
    showLayoutNotice(t("live.layoutSaved"))
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    layoutBusy.value = false
  }
}

async function saveActiveLayout(): Promise<void> {
  const layout = activeLayout.value
  if (!layout || layoutBusy.value || !layoutDirty.value) return

  layoutBusy.value = true
  error.value = null
  try {
    const updated = await updateLiveViewLayout(
      layout.id,
      { layout: currentLayoutState() }
    )
    savedLayouts.value = savedLayouts.value.map((item) =>
      item.id === updated.id ? updated : item
    )
    showLayoutNotice(t("live.layoutUpdated"))
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    layoutBusy.value = false
  }
}

async function setActiveLayoutDefault(): Promise<void> {
  const layout = activeLayout.value
  if (!layout || layout.is_default || layoutBusy.value) return

  layoutBusy.value = true
  error.value = null
  try {
    const updated = await updateLiveViewLayout(
      layout.id,
      { is_default: true }
    )
    savedLayouts.value = savedLayouts.value.map((item) => ({
      ...item,
      is_default: item.id === updated.id
    }))
    showLayoutNotice(t("live.defaultLayoutUpdated"))
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    layoutBusy.value = false
  }
}

async function deleteActiveLayout(): Promise<void> {
  const layout = activeLayout.value
  if (!layout || layoutBusy.value) return
  if (
    !await confirmDestroy(
      t("live.deleteLayoutConfirm", { name: layout.name })
    )
  ) {
    return
  }

  layoutBusy.value = true
  error.value = null
  try {
    await deleteLiveViewLayout(layout.id)
    savedLayouts.value = savedLayouts.value.filter(
      (item) => item.id !== layout.id
    )
    activeLayoutId.value = null
    showLayoutNotice(t("live.layoutDeleted"))
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    layoutBusy.value = false
  }
}

// `workspace` is the element that goes fullscreen; the composable also owns the
// `fullscreenchange` listener that keeps `fullscreen` in sync.
const { toggle: toggleFullscreen } = useFullscreen(workspace, fullscreen)

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && focusedCameraId.value) {
    focusedCameraId.value = null
  }
}

useGlobalRefresh(refresh)

onMounted(() => {
  void refresh()
  evaluateNetworkQuality(true)
  networkInformation()?.addEventListener(
    "change",
    handleNetworkChange
  )
  window.addEventListener("keydown", handleKeydown)
})

onBeforeUnmount(() => {
  previewWall.close()
  networkInformation()?.removeEventListener(
    "change",
    handleNetworkChange
  )
  clearNetworkTimers()
  window.removeEventListener("keydown", handleKeydown)
  if (layoutNoticeTimer !== null) {
    window.clearTimeout(layoutNoticeTimer)
  }
})
</script>

<template>
  <section ref="workspace" class="live-workspace">
    <aside
      v-if="cameraPanelOpen"
      class="live-camera-panel"
    >
      <div class="live-camera-panel__header">
        <div>
          <strong>{{ t("live.cameras") }}</strong>
          <span>
            {{ t("live.selectionSummary", {
              selected: selectedCameras.length,
              enabled: enabledCameras.length
            }) }}
          </span>
        </div>
        <div class="flex items-center gap-1">
          <button
            class="icon-button topbar-icon-button"
            type="button"
            :title="t('live.refreshCameras')"
            :aria-label="t('live.refreshCameras')"
            :disabled="loading"
            @click="refresh"
          >
            <UiIcon name="refresh" :size="16" />
          </button>
          <button
            class="icon-button topbar-icon-button"
            type="button"
            :title="t('live.hideCameras')"
            :aria-label="t('live.hideCameras')"
            @click="cameraPanelOpen = false"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </div>
      </div>

      <label class="live-search">
        <UiIcon name="search" :size="15" />
        <input
          v-model="search"
          type="search"
          :placeholder="t('live.searchCameras')"
          :aria-label="t('live.searchCameras')"
        />
      </label>

      <div class="live-camera-panel__filters">
        <div class="live-camera-filter" :aria-label="t('live.cameraFilter')">
          <button
            type="button"
            :class="{ 'live-camera-filter__active': cameraFilter === 'all' }"
            @click="cameraFilter = 'all'"
          >
            {{ t("live.all") }}
            <span>{{ cameras.length }}</span>
          </button>
          <button
            type="button"
            :class="{ 'live-camera-filter__active': cameraFilter === 'selected' }"
            @click="cameraFilter = 'selected'"
          >
            {{ t("live.selected") }}
            <span>{{ selectedCameras.length }}</span>
          </button>
        </div>
        <div class="live-camera-panel__quick-actions">
          <button
            type="button"
            :disabled="!enabledCameras.length"
            @click="fillGrid"
          >
            {{ t("live.fillSlots", { slots: layoutSlots }) }}
          </button>
          <button
            type="button"
            :disabled="!selectedCameras.length"
            @click="clearGrid"
          >
            {{ t("live.clear") }}
          </button>
        </div>
      </div>

      <div v-if="error" class="live-panel-error">
        {{ error }}
      </div>

      <div class="live-camera-list">
        <button
          v-for="camera in filteredCameras"
          :key="camera.id"
          class="live-camera-row"
          :class="{
            'live-camera-row--selected':
              selectedIds.includes(camera.id),
            'live-camera-row--dragging':
              draggingCameraId === camera.id
          }"
          type="button"
          :disabled="!camera.enabled"
          :draggable="camera.enabled && selectedIds.includes(camera.id)"
          @click="toggleCamera(camera)"
          @dragstart="handleCameraDragStart(camera, $event)"
          @dragend="handleCameraDragEnd"
          @dragover.prevent
          @drop.prevent="dropCameraBefore(camera.id)"
        >
          <span
            class="live-camera-row__status"
            :class="{
              'live-camera-row__status--enabled': camera.enabled
            }"
          />
          <span class="live-camera-row__copy">
            <strong>{{ camera.name }}</strong>
            <small>
              {{ camera.location || camera.adapter_type || t("live.cameraFallback") }}
            </small>
          </span>
          <span
            class="live-camera-row__check"
            :title="
              cameraSlotNumber(camera.id)
                ? t('live.gridSlot', { slot: cameraSlotNumber(camera.id) })
                : undefined
            "
          >
            <span
              v-if="cameraSlotNumber(camera.id)"
              class="live-camera-row__slot"
            >
              {{ cameraSlotNumber(camera.id) }}
            </span>
          </span>
        </button>

        <div
          v-if="!filteredCameras.length && !loading"
          class="live-camera-list__empty"
        >
          {{
            cameraFilter === "selected"
              ? t("live.noSelectedCameras")
              : t("live.noCamerasFound")
          }}
        </div>
      </div>
    </aside>

    <div class="live-stage">
            <!-- UniFi Protect 3-Section Floating Pill HUD -->
      <div class="live-floating-hud">
        <!-- Left: Presets Popover, Defaults, New, & Camera Drawer Toggle -->
        <div class="hud-group">
          <div class="unifi-pill">
            <!-- Camera panel toggle -->
            <button
              class="pill-btn pill-btn--icon"
              type="button"
              :class="{ 'pill-btn--active': cameraPanelOpen }"
              :title="cameraPanelOpen ? t('live.hideCameras') : t('live.showCameras')"
              @click="cameraPanelOpen = !cameraPanelOpen"
            >
              <UiIcon name="cameras" :size="14" />
            </button>

            <span class="pill-divider" />

            <!-- Presets dropdown toggle -->
            <button
              class="pill-btn pill-btn--dropdown"
              type="button"
              @click="togglePresetsPopover"
            >
              <span class="pulse-indicator" />
              <span class="preset-name">{{ activePresetLabel }}</span>
              <svg class="chevron-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            <!-- Set as Default (if active layout exists) -->
            <template v-if="activeLayout">
              <span class="pill-divider" />
              <button
                class="pill-btn pill-btn--text"
                type="button"
                :disabled="layoutBusy || activeLayout.is_default"
                :title="activeLayout.is_default ? t('live.defaultLayout') : t('live.setDefaultLayout')"
                @click="setActiveLayoutDefault"
              >
                <UiIcon name="star" :size="11" /> {{ activeLayout.is_default ? "默认预案" : "设为默认" }}
              </button>
            </template>

            <!-- Save changes (if dirty) -->
            <button
              v-if="activeLayout && layoutDirty"
              class="pill-btn pill-btn--text text-accent"
              type="button"
              :disabled="layoutBusy"
              :title="t('live.saveChanges')"
              @click="saveActiveLayout"
            >
              <UiIcon name="save" :size="12" />
              <span>保存修改</span>
            </button>

            <span class="pill-divider" />
            <!-- New preset button -->
            <button
              class="pill-btn pill-btn--text"
              type="button"
              :disabled="layoutBusy"
              @click="beginLayoutCreate"
            >
              + 新建
            </button>
          </div>

          <!-- Presets Popover Menu -->
          <div v-if="presetsPopoverOpen" class="hud-popover hud-popover--left">
            <div class="popover-header">
              <span>{{ t("live.savedLayouts") }}</span>
              <button class="popover-close" @click="presetsPopoverOpen = false"><UiIcon name="close" :size="12" /></button>
            </div>

            <!-- Create layout inline form -->
            <form
              v-if="layoutCreateOpen"
              class="popover-create-form"
              @submit.prevent="createCurrentLayout"
            >
              <input
                v-model="layoutNameDraft"
                type="text"
                maxlength="128"
                :placeholder="t('live.layoutName')"
                autofocus
              />
              <div class="popover-create-actions">
                <button type="submit" class="btn-create-submit" :disabled="layoutBusy || !layoutNameDraft.trim()">
                  {{ t("live.saveNewLayout") }}
                </button>
                <button type="button" class="btn-create-cancel" @click="cancelLayoutCreate">
                  {{ t("live.cancel") }}
                </button>
              </div>
            </form>

            <div v-else class="popover-list">
              <button
                class="popover-item"
                :class="{ 'popover-item--active': !activeLayoutId }"
                type="button"
                @click="activeLayoutId = null; presetsPopoverOpen = false"
              >
                <div class="popover-item-left">
                  <span class="item-dot" />
                  <span>{{ t("live.currentView") }}</span>
                </div>
                <span class="item-badge">{{ layoutSlots }}机位</span>
              </button>

              <div
                v-for="layout in savedLayouts"
                :key="layout.id"
                class="popover-item-row"
              >
                <button
                  class="popover-item"
                  :class="{ 'popover-item--active': activeLayoutId === layout.id }"
                  type="button"
                  @click="applyLayout(layout); presetsPopoverOpen = false"
                >
                  <div class="popover-item-left">
                    <span class="item-dot" />
                    <span>{{ layout.name }}</span>
                  </div>
                  <span class="item-badge">
                    <UiIcon v-if="layout.is_default" name="star" :size="10" /> {{ layout.is_default ? "默认" : `${layout.layout.slots}机位` }}
                  </span>
                </button>
                <button
                  class="popover-item-del"
                  type="button"
                  :title="t('live.deleteSavedLayout')"
                  @click.stop="activeLayoutId = layout.id; deleteActiveLayout()"
                >
                  <UiIcon name="close" :size="12" />
                </button>
              </div>

              <div v-if="!savedLayouts.length" class="popover-empty">
                暂无已保存预案，点击上方“+ 新建”保存当前布局
              </div>
            </div>
          </div>
        </div>

        <!-- Center: Grid Layout Switcher & Focus Indicator -->
        <div class="hud-group">
          <!-- Exit Focus Button (when focusedCameraId is active) -->
          <button
            v-if="focusedCameraId"
            class="media-button exit-focus-pill"
            type="button"
            @click="focusedCameraId = null"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
            <span>{{ t("live.backToGrid") }}</span>
          </button>

          <!-- Grid Selector Pill (1, 4, 9, 16) -->
          <div v-else class="live-layout-switcher unifi-pill" :aria-label="t('live.gridLayout')">
            <button
              v-for="slots in layoutOptions"
              :key="slots"
              class="media-button grid-slot-btn"
              :class="{ 'media-button--active': layoutSlots === slots }"
              type="button"
              :title="t('live.cameraLayout', { count: slots })"
              @click="setLayout(slots)"
            >
              {{ slots }}
            </button>
          </div>
        </div>

        <!-- Right: Stream Quality, Play/Pause Visible, & Fullscreen -->
        <div class="hud-group">
          <div class="unifi-pill">
            <!-- Quality & Network indicator -->
            <button
              class="pill-btn pill-btn--text quality-indicator-btn"
              type="button"
              :title="networkConstrained ? t('live.networkSaving') : '画质策略'"
              @click="toggleQualityPopover"
            >
              <span
                class="quality-dot"
                :class="{ 'quality-dot--warn': networkConstrained }"
              />
              <span class="quality-label">
                {{ networkConstrained ? '弱网自适应' : (focusedCameraId || layoutSlots === 1 ? '4K/主码流' : '自动自适应') }}
              </span>
            </button>

            <span class="pill-divider" />

            <!-- Batch Start/Stop Visible -->
            <button
              class="pill-btn pill-btn--icon"
              type="button"
              :disabled="!visibleCameras.length || visiblePlayingCount === visibleCameras.length"
              :title="t('live.startVisible')"
              @click="startVisibleCameras"
            >
              <UiIcon name="play" :size="13" />
            </button>

            <button
              class="pill-btn pill-btn--icon"
              type="button"
              :disabled="visiblePlayingCount === 0"
              :title="t('live.stopVisible')"
              @click="stopVisibleCameras"
            >
              <UiIcon name="pause" :size="13" />
            </button>

            <span class="pill-divider" />

            <!-- Fullscreen Toggle -->
            <button
              class="pill-btn pill-btn--icon"
              type="button"
              :title="fullscreen ? t('live.exitFullscreen') : t('live.fullscreenLiveView')"
              @click="toggleFullscreen"
            >
              <UiIcon :name="fullscreen ? 'minimize' : 'maximize'" :size="14" />
            </button>
          </div>

          <!-- Quality Strategy Popover -->
          <div v-if="qualityPopoverOpen" class="hud-popover hud-popover--right">
            <div class="popover-header">
              <span>分屏画质策略 (Quality Strategy)</span>
              <button class="popover-close" @click="qualityPopoverOpen = false"><UiIcon name="close" :size="12" /></button>
            </div>
            <div class="popover-list">
              <div class="quality-strategy-card">
                <div class="quality-card-title"><UiIcon name="activity" :size="12" /> 智能自适应 (Auto)</div>
                <div class="quality-card-desc">多路分屏优先子码流保流畅，单机放大自动切 4K/2K 主码流</div>
                <span class="quality-badge">当前生效中</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Notice Banner (if any) -->
      <div v-if="layoutNotice" class="hud-notice-banner">
        {{ layoutNotice }}
      </div>

      <div
        class="live-grid"
        :style="{ '--live-columns': String(gridColumns) }"
      >
        <LiveCameraTile
          v-for="(camera, index) in visibleCameras"
          :key="camera.id"
          :camera="camera"
          :quality="streamQuality"
          :allow-high-quality="highQualityAllowed"
          :focused="focusedCameraId === camera.id"
          :audio-enabled="
            Boolean(focusedCameraId) || layoutSlots === 1
          "
          :playback-enabled="playingIds.includes(camera.id)"
          :preview-wall="previewWallLayout === null ? null : previewWall"
          :preview-slot="index"
          @focus="focusCamera"
          @playback-change="setCameraPlayback"
        />

        <button
          v-for="slot in emptySlots"
          :key="`empty-${slot}`"
          class="live-empty-tile"
          type="button"
          :title="t('live.openCameraPicker')"
          @click="openCameraPicker"
        >
          <UiIcon name="plus" :size="22" />
          <span>{{ t("live.addCamera") }}</span>
        </button>

        <div
          v-if="!visibleCameras.length && emptySlots === 0"
          class="live-empty-stage"
        >
          <UiIcon name="cameras" :size="30" />
          <strong>{{ t("live.noCameraSelected") }}</strong>
          <span>{{ t("live.chooseCamera") }}</span>
          <button
            class="media-button media-button--text"
            type="button"
            @click="openCameraPicker"
          >
            <UiIcon name="plus" :size="14" />
            {{ t("live.selectCameras") }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.live-stage {
  position: relative !important;
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  background: #050607;
  overflow: hidden;
}

.live-floating-hud {
  position: absolute;
  top: 12px;
  left: 16px;
  right: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  z-index: 30;
  pointer-events: none;
}

.hud-group {
  position: relative;
  pointer-events: auto;
}

.unifi-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: rgba(18, 22, 32, 0.85);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9999px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
  color: #ffffff;
  user-select: none;
}

.pill-divider {
  width: 1px;
  height: 14px;
  background: rgba(255, 255, 255, 0.15);
  margin: 0 2px;
}

.pill-btn {
  background: transparent;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 500;
  padding: 3px 6px;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.pill-btn:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
}

.pill-btn--active {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.12);
}

.pill-btn--icon {
  padding: 4px;
  border-radius: 9999px;
}

.pulse-indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: #10b981;
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.8);
}

.preset-name {
  color: #ffffff;
  font-weight: 600;
}

.chevron-icon {
  color: #9ca3af;
}

.text-accent {
  color: #3b82f6 !important;
}

/* Exit focus pill */
.exit-focus-pill {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: rgba(18, 22, 32, 0.9);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(245, 158, 11, 0.4);
  border-radius: 9999px;
  color: #fcd34d;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
  transition: all 0.15s ease;
}

.exit-focus-pill:hover {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  border-color: rgba(245, 158, 11, 0.6);
}

/* Grid slot buttons */
.grid-slot-btn {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 9999px;
  background: transparent;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  transition: all 0.15s ease;
}

.grid-slot-btn:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.1);
}

.grid-slot-btn.media-button--active {
  background: #006fff !important;
  color: #ffffff !important;
  box-shadow: 0 0 12px rgba(0, 111, 255, 0.4);
}

/* Quality dot */
.quality-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #60a5fa;
}

.quality-dot--warn {
  background-color: #f59e0b;
}

.quality-label {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
}

/* Popover menus */
.hud-popover {
  position: absolute;
  top: calc(100% + 8px);
  width: 260px;
  background: #151822;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 14px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6);
  padding: 8px;
  z-index: 50;
  font-size: 12px;
}

.hud-popover--left {
  left: 0;
}

.hud-popover--right {
  right: 0;
}

.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 6px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #9ca3af;
  font-weight: 600;
}

.popover-close {
  background: transparent;
  border: none;
  color: #6b7280;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
}

.popover-close:hover {
  color: #ffffff;
}

.popover-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.popover-item-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.popover-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #d1d5db;
  font-size: 12px;
  cursor: pointer;
  text-align: left;
  transition: all 0.12s ease;
}

.popover-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #ffffff;
}

.popover-item--active {
  background: rgba(0, 111, 255, 0.15) !important;
  color: #ffffff !important;
}

.popover-item-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.item-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background-color: #10b981;
}

.item-badge {
  font-size: 10px;
  color: #60a5fa;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.popover-item-del {
  background: transparent;
  border: none;
  color: #6b7280;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 10px;
}

.popover-item-del:hover {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

.popover-empty {
  padding: 12px 8px;
  text-align: center;
  font-size: 11px;
  color: #6b7280;
  line-height: 1.4;
}

.popover-create-form {
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.popover-create-form input {
  background: #0d0f15;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  padding: 6px 8px;
  color: #ffffff;
  font-size: 12px;
  outline: none;
}

.popover-create-form input:focus {
  border-color: #006fff;
}

.popover-create-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
}

.btn-create-submit {
  background: #006fff;
  color: #ffffff;
  border: none;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
}

.btn-create-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-create-cancel {
  background: transparent;
  color: #9ca3af;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11px;
  cursor: pointer;
}

.quality-strategy-card {
  padding: 8px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quality-card-title {
  color: #93c5fd;
  font-weight: 600;
  font-size: 12px;
}

.quality-card-desc {
  font-size: 10px;
  color: #9ca3af;
  line-height: 1.4;
}

.quality-badge {
  align-self: flex-start;
  margin-top: 4px;
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 9px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.hud-notice-banner {
  position: absolute;
  top: 56px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(18, 22, 32, 0.95);
  border: 1px solid rgba(59, 130, 246, 0.4);
  color: #93c5fd;
  padding: 6px 14px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 500;
  z-index: 40;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
  pointer-events: none;
}
</style>
