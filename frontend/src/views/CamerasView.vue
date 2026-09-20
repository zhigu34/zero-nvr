<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue"

import { listCameras, type CameraSummary } from "../api/cameras"
import { errorMessage } from "../api/client"
import CameraDetailPanel from "../components/cameras/CameraDetailPanel.vue"
import CameraGroupsPanel from "../components/cameras/CameraGroupsPanel.vue"
import CameraOnboardingPanel from "../components/cameras/CameraOnboardingPanel.vue"
import { useAuthStore } from "../stores/auth"

const auth = useAuthStore()
const cameras = ref<CameraSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const showOnboarding = ref(false)
const selectedCamera = ref<CameraSummary | null>(null)
const workspace = ref<"cameras" | "groups" | "retired">("cameras")

const activeCameras = computed(() =>
  cameras.value.filter((camera) => !camera.retired_at)
)
const retiredCameras = computed(() =>
  cameras.value.filter((camera) => Boolean(camera.retired_at))
)
const inventoryCameras = computed(() =>
  workspace.value === "retired"
    ? retiredCameras.value
    : activeCameras.value
)
const inventoryTitle = computed(() =>
  workspace.value === "retired"
    ? "Retired cameras"
    : "Configured cameras"
)

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    cameras.value = await listCameras({
      includeRetired: auth.hasPermission("camera.configure")
    })
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function handleRefresh(): void {
  void refresh()
}

function handleCreated(): void {
  showOnboarding.value = false
  void refresh()
}

function openCamera(camera: CameraSummary): void {
  selectedCamera.value = camera
}

async function handleCameraChanged(): Promise<void> {
  const selectedId = selectedCamera.value?.id
  await refresh()
  if (selectedId) {
    selectedCamera.value =
      cameras.value.find((item) => item.id === selectedId) ?? null
    if (selectedCamera.value?.retired_at) {
      workspace.value = "retired"
    } else if (
      selectedCamera.value &&
      workspace.value === "retired"
    ) {
      workspace.value = "cameras"
    }
  }
}

onMounted(() => {
  void refresh()
  window.addEventListener("zero-nvr:refresh", handleRefresh)
})
onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", handleRefresh)
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <p class="eyebrow">Device center</p>
        <h1>Cameras</h1>
        <p class="page-subtitle">
          Discover and validate devices before they become canonical Cameras.
          Source credentials stay server-side.
        </p>
      </div>

      <div class="page-actions">
        <button
          class="button button--secondary"
          :disabled="loading"
          @click="refresh"
        >
          {{ loading ? "Refreshing…" : "Refresh" }}
        </button>
        <button
          v-if="auth.hasPermission('camera.configure')"
          class="button button--primary"
          type="button"
          @click="
            workspace = 'cameras';
            selectedCamera = null;
            showOnboarding = !showOnboarding
          "
        >
          {{ showOnboarding ? "Hide onboarding" : "Add camera" }}
        </button>
      </div>
    </div>

    <p v-if="error" class="notice notice--error">{{ error }}</p>

    <div
      v-if="auth.hasPermission('camera.configure')"
      class="camera-workspace-tabs"
    >
      <button
        type="button"
        :class="{ 'camera-workspace-tab--active': workspace === 'cameras' }"
        @click="workspace = 'cameras'"
      >
        Cameras
      </button>
      <button
        type="button"
        :class="{ 'camera-workspace-tab--active': workspace === 'retired' }"
        @click="
          workspace = 'retired';
          showOnboarding = false;
          selectedCamera = null
        "
      >
        Retired
        <span v-if="retiredCameras.length">{{ retiredCameras.length }}</span>
      </button>
      <button
        type="button"
        :class="{ 'camera-workspace-tab--active': workspace === 'groups' }"
        @click="
          workspace = 'groups';
          showOnboarding = false;
          selectedCamera = null
        "
      >
        Groups
      </button>
    </div>

    <CameraOnboardingPanel
      v-if="showOnboarding && workspace === 'cameras'"
      @created="handleCreated"
      @close="showOnboarding = false"
    />

    <CameraGroupsPanel
      v-if="workspace === 'groups'"
      :cameras="activeCameras"
    />

    <template v-else>
    <section class="panel">
      <div class="panel__header">
        <div>
          <p class="eyebrow">
            {{ workspace === "retired" ? "History" : "Inventory" }}
          </p>
          <h2>{{ inventoryTitle }}</h2>
        </div>
        <span class="badge badge--muted">
          {{ inventoryCameras.length }}
        </span>
      </div>

      <div
        v-if="!inventoryCameras.length"
        class="empty-state empty-state--large"
      >
        <strong>
          {{
            workspace === "retired"
              ? "No retired cameras"
              : "No cameras configured"
          }}
        </strong>
        <p
          v-if="
            auth.hasPermission('camera.configure') &&
            workspace !== 'retired'
          "
        >
          Use Add camera for ONVIF discovery/import or a manually supplied RTSP
          source.
        </p>
        <p v-else-if="workspace === 'retired'">
          Retired cameras keep their recordings and event history.
        </p>
        <p v-else>
          No Cameras are visible within your current scope.
        </p>
      </div>

      <div v-else class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Location</th>
              <th>Adapter</th>
              <th>Storage label</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="camera in inventoryCameras"
              :key="camera.id"
              class="camera-inventory-row"
              tabindex="0"
              @click="openCamera(camera)"
              @keydown.enter="openCamera(camera)"
            >
              <td>
                <button
                  class="camera-name-button"
                  type="button"
                  @click.stop="openCamera(camera)"
                >
                  {{ camera.name }}
                </button>
              </td>
              <td>{{ camera.location || "—" }}</td>
              <td>{{ camera.adapter_type || "manual" }}</td>
              <td>{{ camera.storage_label || "—" }}</td>
              <td>
                <span
                  class="badge"
                  :class="
                    camera.retired_at
                      ? 'badge--muted'
                      : camera.enabled
                        ? 'badge--ok'
                        : 'badge--muted'
                  "
                >
                  {{
                    camera.retired_at
                      ? "Retired"
                      : camera.enabled
                        ? "Enabled"
                        : "Disabled"
                  }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    </template>

    <CameraDetailPanel
      v-if="selectedCamera"
      :camera="selectedCamera"
      @close="selectedCamera = null"
      @changed="handleCameraChanged"
    />
  </div>
</template>

<style scoped>
.camera-workspace-tabs {
  display: flex;
  gap: 2px;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--border-subtle);
}

.camera-workspace-tabs button {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 5px;
  padding: 0 10px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 9px;
  font-weight: 600;
}

.camera-workspace-tabs button > span {
  display: inline-grid;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--surface-subtle);
  place-items: center;
  font-size: 7px;
}

.camera-workspace-tabs .camera-workspace-tab--active {
  border-bottom-color: var(--accent);
  color: var(--text-primary);
}

.camera-inventory-row {
  cursor: pointer;
}

.camera-inventory-row:hover {
  background: var(--surface-hover);
}

.camera-inventory-row:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.camera-name-button {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  font: inherit;
  font-weight: 650;
  text-align: left;
}

.camera-name-button:hover {
  color: var(--accent);
}
</style>
