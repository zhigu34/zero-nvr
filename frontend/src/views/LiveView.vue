<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue"

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

const auth = useAuthStore()
const layoutOptions: LiveLayoutSlots[] = [1, 4, 9, 16]
const workspace = ref<HTMLElement | null>(null)
const cameras = ref<CameraSummary[]>([])
const selectedIds = ref<string[]>([])
const layoutSlots = ref<LiveLayoutSlots>(4)
const focusedCameraId = ref<string | null>(null)
const cameraPanelOpen = ref(true)
const search = ref("")
const loading = ref(false)
const error = ref<string | null>(null)
const fullscreen = ref(false)

const savedLayouts = ref<LiveViewLayout[]>([])
const activeLayoutId = ref<string | null>(null)
const layoutBusy = ref(false)
const layoutCreateOpen = ref(false)
const layoutNameDraft = ref("")
const layoutNotice = ref<string | null>(null)

let layoutsInitialized = false
let layoutNoticeTimer: number | null = null

const enabledCameras = computed(() =>
  cameras.value.filter((camera) => camera.enabled)
)

const filteredCameras = computed(() => {
  const needle = search.value.trim().toLowerCase()
  if (!needle) return cameras.value

  return cameras.value.filter((camera) =>
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

const gridColumns = computed(() => {
  if (focusedCameraId.value || layoutSlots.value === 1) return 1
  if (layoutSlots.value === 4) return 2
  if (layoutSlots.value === 9) return 3
  return 4
})

const streamQuality = computed<LiveQuality>(() =>
  focusedCameraId.value || layoutSlots.value === 1 ? "high" : "low"
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
    showLayoutNotice("Layout saved")
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
    showLayoutNotice("Layout updated")
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
    showLayoutNotice("Default layout updated")
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
      `Delete the saved layout “${layout.name}”?`
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
    showLayoutNotice("Layout deleted")
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
  window.addEventListener("zero-nvr:refresh", handleRefreshEvent)
  window.addEventListener("keydown", handleKeydown)
  document.addEventListener("fullscreenchange", handleFullscreenChange)
})

onBeforeUnmount(() => {
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
          <strong>Cameras</strong>
          <span>{{ enabledCameras.length }} enabled</span>
        </div>
        <button
          class="icon-button topbar-icon-button"
          type="button"
          title="Refresh cameras"
          aria-label="Refresh cameras"
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
          placeholder="Search cameras"
          aria-label="Search cameras"
        />
      </label>

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
              selectedIds.includes(camera.id)
          }"
          type="button"
          :disabled="!camera.enabled"
          @click="toggleCamera(camera)"
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
              {{ camera.location || camera.adapter_type || "Camera" }}
            </small>
          </span>
          <span class="live-camera-row__check">
            <UiIcon
              v-if="selectedIds.includes(camera.id)"
              name="check"
              :size="14"
            />
          </span>
        </button>

        <div
          v-if="!filteredCameras.length && !loading"
          class="live-camera-list__empty"
        >
          No cameras found.
        </div>
      </div>
    </aside>

    <div class="live-stage">
      <header class="live-toolbar">
        <div class="live-toolbar__left">
          <button
            class="media-button"
            type="button"
            :title="cameraPanelOpen ? 'Hide cameras' : 'Show cameras'"
            :aria-label="cameraPanelOpen ? 'Hide cameras' : 'Show cameras'"
            @click="cameraPanelOpen = !cameraPanelOpen"
          >
            <UiIcon name="panel" :size="16" />
          </button>

          <span class="live-toolbar__title">
            {{ focusedCameraId ? "Camera focus" : "Live view" }}
          </span>

          <span
            v-if="selectedCameras.length > layoutSlots && !focusedCameraId"
            class="live-toolbar__hint"
          >
            {{ selectedCameras.length - layoutSlots }} hidden
          </span>

          <span
            v-if="layoutNotice"
            class="live-toolbar__hint"
          >
            {{ layoutNotice }}
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
              placeholder="Layout name"
              aria-label="Layout name"
              autofocus
            />
            <button
              class="media-button"
              type="submit"
              title="Save new layout"
              :disabled="layoutBusy || !layoutNameDraft.trim()"
            >
              <UiIcon name="check" :size="14" />
            </button>
            <button
              class="media-button"
              type="button"
              title="Cancel"
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
              aria-label="Saved live layouts"
              @change="handleLayoutSelection"
            >
              <option value="">Current view</option>
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
              title="Save changes to this layout"
              :disabled="layoutBusy || !layoutDirty"
              @click="saveActiveLayout"
            >
              <UiIcon name="save" :size="14" />
            </button>
            <button
              class="media-button"
              type="button"
              title="Save current view as a new layout"
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
                  ? 'Default layout'
                  : 'Set as default layout'
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
              title="Delete saved layout"
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
            Back to grid
          </button>

          <div v-else class="live-layout-switcher" aria-label="Grid layout">
            <button
              v-for="slots in layoutOptions"
              :key="slots"
              class="media-button"
              :class="{ 'media-button--active': layoutSlots === slots }"
              type="button"
              :title="`${slots} camera layout`"
              @click="setLayout(slots)"
            >
              <UiIcon :name="`grid${slots}`" :size="16" />
            </button>
          </div>

          <button
            class="media-button"
            type="button"
            :title="fullscreen ? 'Exit fullscreen' : 'Fullscreen live view'"
            :aria-label="fullscreen ? 'Exit fullscreen' : 'Fullscreen live view'"
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
          :focused="focusedCameraId === camera.id"
          :audio-enabled="
            Boolean(focusedCameraId) || layoutSlots === 1
          "
          @focus="focusCamera"
        />

        <div
          v-for="slot in emptySlots"
          :key="`empty-${slot}`"
          class="live-empty-tile"
        >
          <UiIcon name="cameras" :size="24" />
          <span>Select a camera</span>
        </div>

        <div
          v-if="!visibleCameras.length && emptySlots === 0"
          class="live-empty-stage"
        >
          <UiIcon name="cameras" :size="30" />
          <strong>No camera selected</strong>
          <span>Choose an enabled camera from the camera panel.</span>
        </div>
      </div>
    </div>
  </section>
</template>
