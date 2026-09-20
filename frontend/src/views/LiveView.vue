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
import type { LiveQuality } from "../api/live"
import LiveCameraTile from "../components/live/LiveCameraTile.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type LayoutSlots = 1 | 4 | 9

const auth = useAuthStore()
const layoutOptions: LayoutSlots[] = [1, 4, 9]
const workspace = ref<HTMLElement | null>(null)
const cameras = ref<CameraSummary[]>([])
const selectedIds = ref<string[]>([])
const layoutSlots = ref<LayoutSlots>(4)
const focusedCameraId = ref<string | null>(null)
const cameraPanelOpen = ref(true)
const search = ref("")
const loading = ref(false)
const error = ref<string | null>(null)
const fullscreen = ref(false)

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
  return layoutSlots.value === 4 ? 2 : 3
})

const streamQuality = computed<LiveQuality>(() =>
  focusedCameraId.value || layoutSlots.value <= 4 ? "high" : "low"
)

function initializeSelection(): void {
  const validIds = new Set(cameras.value.map((camera) => camera.id))
  selectedIds.value = selectedIds.value.filter((id) => validIds.has(id))

  if (!selectedIds.value.length) {
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

async function refresh(): Promise<void> {
  if (!auth.hasPermission("camera.view")) return

  loading.value = true
  error.value = null
  try {
    cameras.value = await listCameras()
    initializeSelection()
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

  selectedIds.value = [camera.id, ...selectedIds.value].slice(0, 9)
}

function focusCamera(cameraId: string): void {
  if (focusedCameraId.value === cameraId) {
    focusedCameraId.value = null
    return
  }

  if (!selectedIds.value.includes(cameraId)) {
    selectedIds.value = [cameraId, ...selectedIds.value].slice(0, 9)
  }
  focusedCameraId.value = cameraId
}

function setLayout(slots: LayoutSlots): void {
  layoutSlots.value = slots
  focusedCameraId.value = null
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
        </div>

        <div class="live-toolbar__actions">
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
