<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"

import ThemeControl from "../components/ui/ThemeControl.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const sidebarOpen = ref(false)
const sidebarCollapsed = ref(
  window.localStorage.getItem("zero-nvr.sidebar-collapsed") === "1"
)

const navigation = [
  { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { to: "/live", label: "Live", icon: "live" },
  { to: "/playback", label: "Playback", icon: "playback" },
  { to: "/events", label: "Events", icon: "events" },
  { to: "/cameras", label: "Cameras", icon: "cameras" },
  { to: "/storage", label: "Storage", icon: "storage" },
  { to: "/system", label: "System", icon: "system" }
]

const pageTitle = computed(() => String(route.meta.title ?? "zero-nvr"))
const userInitial = computed(() => {
  const source = auth.user?.display_name || auth.user?.username || "Z"
  return source.trim().charAt(0).toUpperCase()
})

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

function toggleNavigation(): void {
  if (window.matchMedia("(max-width: 900px)").matches) {
    sidebarOpen.value = !sidebarOpen.value
    return
  }

  sidebarCollapsed.value = !sidebarCollapsed.value
  window.localStorage.setItem(
    "zero-nvr.sidebar-collapsed",
    sidebarCollapsed.value ? "1" : "0"
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
  <div
    class="app-shell"
    :class="{ 'app-shell--collapsed': sidebarCollapsed }"
  >
    <aside
      class="sidebar"
      :class="{
        'sidebar--open': sidebarOpen,
        'sidebar--collapsed': sidebarCollapsed
      }"
    >
      <div class="brand">
        <div class="brand__mark" aria-hidden="true">
          <UiIcon name="cameras" :size="18" />
        </div>
        <div class="brand__copy">
          <strong>zero-nvr</strong>
          <span>video security</span>
        </div>
      </div>

      <nav class="primary-nav" aria-label="Primary navigation">
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          class="primary-nav__item"
          :title="sidebarCollapsed ? item.label : undefined"
          @click="sidebarOpen = false"
        >
          <UiIcon class="primary-nav__icon" :name="item.icon" :size="18" />
          <span class="primary-nav__label">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar__footer">
        <span class="status-dot status-dot--ok" />
        <span class="sidebar__footer-label">Core online</span>
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
        <div class="topbar__left">
          <button
            class="icon-button topbar-icon-button"
            type="button"
            aria-label="Toggle navigation"
            title="Toggle navigation"
            @click="toggleNavigation"
          >
            <UiIcon
              :name="sidebarCollapsed ? 'expand' : 'collapse'"
              :size="18"
            />
          </button>
          <span class="topbar__divider" />
          <strong class="topbar__title">{{ pageTitle }}</strong>
        </div>

        <div class="topbar__actions">
          <ThemeControl />

          <div class="topbar__user">
            <span class="user-avatar">{{ userInitial }}</span>
            <div class="topbar__identity">
              <strong>{{ auth.user?.display_name }}</strong>
              <span>{{ auth.user?.username }}</span>
            </div>
          </div>

          <button
            class="icon-button topbar-icon-button"
            type="button"
            aria-label="Sign out"
            title="Sign out"
            @click="logout"
          >
            <UiIcon name="logout" :size="17" />
          </button>
        </div>
      </header>

      <main
        class="page-surface"
        :class="{
          'page-surface--media':
            route.name === 'live' || route.name === 'playback'
        }"
      >
        <RouterView />
      </main>
    </div>
  </div>
</template>
