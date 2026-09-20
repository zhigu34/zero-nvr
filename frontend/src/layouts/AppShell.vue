<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"
import { useRouter } from "vue-router"

import { useAuthStore } from "../stores/auth"

const router = useRouter()
const auth = useAuthStore()
const sidebarOpen = ref(false)

const navigation = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/live", label: "Live" },
  { to: "/playback", label: "Playback" },
  { to: "/events", label: "Events" },
  { to: "/cameras", label: "Cameras" },
  { to: "/storage", label: "Storage" },
  { to: "/system", label: "System" }
]

let eventSource: EventSource | null = null

function emitRefresh(type: string): void {
  window.dispatchEvent(
    new CustomEvent("zero-nvr:refresh", { detail: { type } })
  )
}

function startEventStream(): void {
  if (!auth.hasPermission("system.view") || eventSource) return

  eventSource = new EventSource("/api/v1/system/events/stream")
  eventSource.addEventListener("ready", () => emitRefresh("ready"))
  eventSource.addEventListener(
    "api.mutation",
    () => emitRefresh("api.mutation")
  )
}

async function logout(): Promise<void> {
  await auth.logout()
  await router.push({ name: "login" })
}

onMounted(startEventStream)
onBeforeUnmount(() => {
  eventSource?.close()
  eventSource = null
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ 'sidebar--open': sidebarOpen }">
      <div class="brand">
        <div class="brand__mark">0</div>
        <div>
          <strong>zero-nvr</strong>
          <span>control plane</span>
        </div>
      </div>

      <nav class="primary-nav" aria-label="Primary navigation">
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          class="primary-nav__item"
          @click="sidebarOpen = false"
        >
          <span class="primary-nav__dot" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar__footer">
        <span class="status-dot status-dot--ok" />
        <span>Core online</span>
      </div>
    </aside>

    <button
      v-if="sidebarOpen"
      class="sidebar-backdrop"
      aria-label="Close navigation"
      @click="sidebarOpen = false"
    />

    <div class="shell-main">
      <header class="topbar">
        <button
          class="icon-button menu-button"
          aria-label="Open navigation"
          @click="sidebarOpen = !sidebarOpen"
        >
          <span />
          <span />
          <span />
        </button>

        <div class="topbar__identity">
          <strong>{{ auth.user?.display_name }}</strong>
          <span>{{ auth.user?.username }}</span>
        </div>

        <button class="button button--ghost" @click="logout">
          Sign out
        </button>
      </header>

      <main class="page-surface">
        <RouterView />
      </main>
    </div>
  </div>
</template>
