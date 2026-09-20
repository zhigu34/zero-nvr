<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import { apiRequest, errorMessage } from "../api/client"
import { useAuthStore } from "../stores/auth"

interface HealthComponent {
  status: "OK" | "DEGRADED" | "ERROR" | "DISABLED"
  message: string | null
  details: Record<string, unknown>
}

interface SystemHealth {
  status: "OK" | "DEGRADED" | "ERROR" | "DISABLED"
  components: Record<string, HealthComponent>
}

interface CameraSummary {
  id: string
  name: string
  enabled: boolean
  location: string | null
  storage_label: string | null
  adapter_type: string | null
}

const auth = useAuthStore()
const health = ref<SystemHealth | null>(null)
const cameras = ref<CameraSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const enabledCameraCount = computed(
  () => cameras.value.filter((camera) => camera.enabled).length
)

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  const tasks: Promise<void>[] = []

  if (auth.hasPermission("system.view")) {
    tasks.push(
      apiRequest<SystemHealth>("/system/health").then((value) => {
        health.value = value
      })
    )
  }
  if (auth.hasPermission("camera.view")) {
    tasks.push(
      apiRequest<CameraSummary[]>("/cameras").then((value) => {
        cameras.value = value
      })
    )
  }

  try {
    await Promise.all(tasks)
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
        <p class="eyebrow">Overview</p>
        <h1>Dashboard</h1>
        <p class="page-subtitle">
          Current product health and camera inventory from the canonical
          zero-nvr API.
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

    <section class="metric-grid">
      <article class="metric-card">
        <span class="metric-card__label">System</span>
        <strong>{{ health?.status ?? "—" }}</strong>
        <span>Capability health aggregate</span>
      </article>
      <article class="metric-card">
        <span class="metric-card__label">Cameras</span>
        <strong>{{ cameras.length }}</strong>
        <span>{{ enabledCameraCount }} enabled</span>
      </article>
      <article class="metric-card">
        <span class="metric-card__label">Core</span>
        <strong>SQLite</strong>
        <span>Default first-class database mode</span>
      </article>
    </section>

    <section v-if="health" class="panel">
      <div class="panel__header">
        <div>
          <p class="eyebrow">Runtime</p>
          <h2>Capability health</h2>
        </div>
      </div>
      <div class="health-grid">
        <article
          v-for="(component, name) in health.components"
          :key="name"
          class="health-item"
        >
          <div>
            <span
              class="status-dot"
              :class="`status-dot--${component.status.toLowerCase()}`"
            />
            <strong>{{ name }}</strong>
          </div>
          <span class="health-item__status">{{ component.status }}</span>
          <p v-if="component.message">{{ component.message }}</p>
        </article>
      </div>
    </section>

    <section class="panel">
      <div class="panel__header">
        <div>
          <p class="eyebrow">Device center</p>
          <h2>Recent cameras</h2>
        </div>
        <RouterLink class="text-link" to="/cameras">Open Cameras</RouterLink>
      </div>

      <div v-if="!cameras.length" class="empty-state">
        <strong>No cameras yet</strong>
        <p>Add cameras from the Cameras workspace when onboarding is configured.</p>
      </div>

      <div v-else class="compact-list">
        <article
          v-for="camera in cameras.slice(0, 6)"
          :key="camera.id"
          class="compact-list__item"
        >
          <div>
            <strong>{{ camera.name }}</strong>
            <span>{{ camera.location || "No location" }}</span>
          </div>
          <span
            class="badge"
            :class="camera.enabled ? 'badge--ok' : 'badge--muted'"
          >
            {{ camera.enabled ? "Enabled" : "Disabled" }}
          </span>
        </article>
      </div>
    </section>
  </div>
</template>
