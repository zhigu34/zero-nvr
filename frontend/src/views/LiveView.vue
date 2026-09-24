<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue"
import { useI18n } from "vue-i18n"

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
import { useAuthStore } from "../stores/auth"

interface NetworkInformationLike extends EventTarget {
  saveData?: boolean
  effectiveType?: string
  downlink?: number
  rtt?: number
}

const auth = useAuthStore()
const { t } = useI18n({ useScope: "global" })
const layoutOptions: LiveLayoutSlots[] = [1, 4, 9, 16]
const workspace = ref<HTMLElement | null>(null)
const cameras = ref<CameraSummary[]>([])
const selectedIds = ref<string[]>([])
const layoutSlots = ref<LiveLayoutSlots>(4)
const focusedCameraId = ref<string | null>(null)
const cameraPanelOpen = ref(true)
const search = ref("")
const cameraFilter = ref<"all" | "selected">("all")
const draggingCameraId = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const fullscreen = ref(false)
const networkConstrained = ref(false)

const savedLayouts = ref<LiveViewLayout[]>([])
const activeLayoutId = ref<string | null>(null)
const layoutBusy = ref(false)
const layoutCreateOpen = ref(false)
const layoutNameDraft = ref("")
const layoutNotice = ref<string | null>(null)

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

const activeLayout = computed(() =>
  savedLayouts.value.find(
    (layout) => layout.id === activeLayoutId.value
  ) ?? null
)

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

function initializeSelection(fillIfEmpty = true): void {
  const validIds = new Set(
    cameras.value
      .filter((camera) => camera.enabled)
      .map((camera) => camera.id)
  )
  selectedIds.value = selectedIds.value.filter(
    (id) => validIds.has(id)
  )

  if (fillIfEmpty && !selectedIds.value.length) {
    selectedIds.value = enabledCameras.value
      .slice(0, Math.min(4, enabledCameras.value.length))
      .map((camera) => camera.id)
  }

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
  cameraPanelOpen.value = layout.layout.camera_panel_open
  focusedCameraId.value = null
  activeLayoutId.value = layout.id
}

async function refresh(): Promise<void> {
  if (!auth.hasPermission("camera.view")) return

  loading.value = true
  error.value = null
  try {
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
        initializeSelection(true)
      }
      layoutsInitialized = true
    } else {
      initializeSelection(activeLayoutId.value === null)
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function toggleCamera(camera: CameraSummary): void {
  if (!camera.enabled) return

  const exists = selectedIds.value.includes(camera.id)
  if (exists) {
    selectedIds.value = selectedIds.value.filter(
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
  focusedCameraId.value = null
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
    !window.confirm(
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

async function toggleFullscreen(): Promise<void> {
  if (!document.fullscreenElement) {
    await workspace.value?.requestFullscreen?.()
  } else {
    await document.exitFullscreen()
  }
}

function handleFullscreenChange(): void {
  fullscreen.value = Boolean(document.fullscreenElement)
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && focusedCameraId.value) {
    focusedCameraId.value = null
  }
}

function handleRefreshEvent(): void {
  void refresh()
}

onMounted(() => {
  void refresh()
  evaluateNetworkQuality(true)
  networkInformation()?.addEventListener(
    "change",
    handleNetworkChange
  )
  window.addEventListener("zero-nvr:refresh", handleRefreshEvent)
  window.addEventListener("keydown", handleKeydown)
  document.addEventListener("fullscreenchange", handleFullscreenChange)
})

onBeforeUnmount(() => {
  networkInformation()?.removeEventListener(
    "change",
    handleNetworkChange
  )
  clearNetworkTimers()
  window.removeEventListener("zero-nvr:refresh", handleRefreshEvent)
  window.removeEventListener("keydown", handleKeydown)
  document.removeEventListener("fullscreenchange", handleFullscreenChange)
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
                ? t("live.gridSlot", { slot: cameraSlotNumber(camera.id) })
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
      <header class="live-toolbar">
        <div class="live-toolbar__left">
          <button
            class="media-button"
            type="button"
            :title="cameraPanelOpen ? t('live.hideCameras') : t('live.showCameras')"
            :aria-label="cameraPanelOpen ? t('live.hideCameras') : t('live.showCameras')"
            @click="cameraPanelOpen = !cameraPanelOpen"
          >
            <UiIcon name="panel" :size="16" />
          </button>

          <span class="live-toolbar__title">
            {{ focusedCameraId ? t("live.cameraFocus") : t("live.liveView") }}
          </span>

          <span class="live-toolbar__status">
            <i />
            {{ t("live.liveCount", { count: visibleCameraCount }) }}
            <template v-if="!focusedCameraId">
              · {{ t("live.viewCount", { count: layoutSlots }) }}
            </template>
          </span>

          <span
            v-if="selectedCameras.length > layoutSlots && !focusedCameraId"
            class="live-toolbar__hint"
          >
            {{ t("live.hiddenCount", {
              count: selectedCameras.length - layoutSlots
            }) }}
          </span>

          <span
            v-if="layoutNotice"
            class="live-toolbar__hint"
          >
            {{ layoutNotice }}
          </span>

          <span
            v-if="networkConstrained"
            class="live-toolbar__hint"
          >
            {{ t("live.networkSaving") }}
          </span>
        </div>

        <div class="live-toolbar__actions">
          <form
            v-if="!focusedCameraId && layoutCreateOpen"
            class="live-layout-create"
            @submit.prevent="createCurrentLayout"
          >
            <input
              v-model="layoutNameDraft"
              type="text"
              maxlength="128"
              :placeholder="t('live.layoutName')"
              :aria-label="t('live.layoutName')"
              autofocus
            />
            <button
              class="media-button"
              type="submit"
              :title="t('live.saveNewLayout')"
              :disabled="layoutBusy || !layoutNameDraft.trim()"
            >
              <UiIcon name="check" :size="14" />
            </button>
            <button
              class="media-button"
              type="button"
              :title="t('live.cancel')"
              @click="cancelLayoutCreate"
            >
              <UiIcon name="close" :size="14" />
            </button>
          </form>

          <div
            v-if="!focusedCameraId && !layoutCreateOpen"
            class="live-saved-layouts"
          >
            <select
              :value="activeLayoutId || ''"
              :aria-label="t('live.savedLayouts')"
              @change="handleLayoutSelection"
            >
              <option value="">{{ t("live.currentView") }}</option>
              <option
                v-for="layout in savedLayouts"
                :key="layout.id"
                :value="layout.id"
              >
                {{ layout.is_default ? "★ " : "" }}{{ layout.name }}
              </option>
            </select>
            <button
              v-if="activeLayout"
              class="media-button"
              type="button"
              :title="t('live.saveChanges')"
              :disabled="layoutBusy || !layoutDirty"
              @click="saveActiveLayout"
            >
              <UiIcon name="save" :size="14" />
            </button>
            <button
              class="media-button"
              type="button"
              :title="t('live.saveAsNew')"
              :disabled="layoutBusy"
              @click="beginLayoutCreate"
            >
              <UiIcon name="plus" :size="14" />
            </button>
            <button
              v-if="activeLayout"
              class="media-button"
              :class="{
                'media-button--active': activeLayout.is_default
              }"
              type="button"
              :title="
                activeLayout.is_default
                  ? t('live.defaultLayout')
                  : t('live.setDefaultLayout')
              "
              :disabled="layoutBusy || activeLayout.is_default"
              @click="setActiveLayoutDefault"
            >
              <UiIcon name="star" :size="14" />
            </button>
            <button
              v-if="activeLayout"
              class="media-button"
              type="button"
              :title="t('live.deleteSavedLayout')"
              :disabled="layoutBusy"
              @click="deleteActiveLayout"
            >
              <UiIcon name="trash" :size="14" />
            </button>
          </div>

          <button
            v-if="focusedCameraId"
            class="media-button media-button--text"
            type="button"
            @click="focusedCameraId = null"
          >
            <UiIcon name="grid4" :size="15" />
            {{ t("live.backToGrid") }}
          </button>

          <div v-else class="live-layout-switcher" :aria-label="t('live.gridLayout')">
            <button
              v-for="slots in layoutOptions"
              :key="slots"
              class="media-button"
              :class="{ 'media-button--active': layoutSlots === slots }"
              type="button"
              :title="t('live.cameraLayout', { count: slots })"
              @click="setLayout(slots)"
            >
              <UiIcon :name="`grid${slots}`" :size="16" />
            </button>
          </div>

          <button
            class="media-button"
            type="button"
            :title="fullscreen ? t('live.exitFullscreen') : t('live.fullscreenLiveView')"
            :aria-label="fullscreen ? t('live.exitFullscreen') : t('live.fullscreenLiveView')"
            @click="toggleFullscreen"
          >
            <UiIcon
              :name="fullscreen ? 'minimize' : 'maximize'"
              :size="16"
            />
          </button>
        </div>
      </header>

      <div
        class="live-grid"
        :style="{ '--live-columns': String(gridColumns) }"
      >
        <LiveCameraTile
          v-for="camera in visibleCameras"
          :key="camera.id"
          :camera="camera"
          :quality="streamQuality"
          :allow-high-quality="highQualityAllowed"
          :focused="focusedCameraId === camera.id"
          :audio-enabled="
            Boolean(focusedCameraId) || layoutSlots === 1
          "
          @focus="focusCamera"
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
