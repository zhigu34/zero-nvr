<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"

import { apiRequest, errorMessage } from "../api/client"

interface CameraSummary {
  id: string
  name: string
  enabled: boolean
  location: string | null
  storage_label: string | null
  adapter_type: string | null
}

const cameras = ref<CameraSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    cameras.value = await apiRequest<CameraSummary[]>("/cameras")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function handleRefresh(): void {
  void refresh()
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
          Canonical Camera inventory. Source credentials stay server-side.
        </p>
      </div>
      <button
        class="button button--secondary"
        :disabled="loading"
        @click="refresh"
      >
        {{ loading ? "Refreshing…" : "Refresh" }}
      </button>
    </div>

    <p v-if="error" class="notice notice--error">{{ error }}</p>

    <section class="panel">
      <div v-if="!cameras.length" class="empty-state empty-state--large">
        <strong>No cameras configured</strong>
        <p>
          The backend already supports manual RTSP and ONVIF onboarding.
          The guided add-camera workflow is the next frontend slice.
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
            <tr v-for="camera in cameras" :key="camera.id">
              <td><strong>{{ camera.name }}</strong></td>
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
  </div>
</template>
