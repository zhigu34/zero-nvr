<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"

import { listCameras, type CameraSummary } from "../api/cameras"
import { errorMessage } from "../api/client"
import CameraDetailPanel from "../components/cameras/CameraDetailPanel.vue"
import CameraOnboardingPanel from "../components/cameras/CameraOnboardingPanel.vue"
import { useAuthStore } from "../stores/auth"

const auth = useAuthStore()
const cameras = ref<CameraSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const showOnboarding = ref(false)
const selectedCamera = ref<CameraSummary | null>(null)

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    cameras.value = await listCameras()
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
          @click="showOnboarding = !showOnboarding"
        >
          {{ showOnboarding ? "Hide onboarding" : "Add camera" }}
        </button>
      </div>
    </div>

    <p v-if="error" class="notice notice--error">{{ error }}</p>

    <CameraOnboardingPanel
      v-if="showOnboarding"
      @created="handleCreated"
      @close="showOnboarding = false"
    />

    <section class="panel">
      <div class="panel__header">
        <div>
          <p class="eyebrow">Inventory</p>
          <h2>Configured cameras</h2>
        </div>
        <span class="badge badge--muted">{{ cameras.length }}</span>
      </div>

      <div v-if="!cameras.length" class="empty-state empty-state--large">
        <strong>No cameras configured</strong>
        <p v-if="auth.hasPermission('camera.configure')">
          Use Add camera for ONVIF discovery/import or a manually supplied RTSP
          source.
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
              v-for="camera in cameras"
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
                  :class="camera.enabled ? 'badge--ok' : 'badge--muted'"
                >
                  {{ camera.enabled ? "Enabled" : "Disabled" }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <CameraDetailPanel
      v-if="selectedCamera"
      :camera="selectedCamera"
      @close="selectedCamera = null"
      @changed="handleCameraChanged"
    />
  </div>
</template>

<style scoped>
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
