<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import AccountPanel from "../components/account/AccountPanel.vue"
import LanguageControl from "../components/ui/LanguageControl.vue"
import ThemeControl from "../components/ui/ThemeControl.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n({ useScope: "global" })

const accountOpen = ref(false)

const navigation = [
  { to: "/live", labelKey: "nav.live", icon: "live" },
  { to: "/playback", labelKey: "nav.playback", icon: "playback" },
  { to: "/files", labelKey: "nav.files", icon: "folder" },
  { to: "/events", labelKey: "nav.events", icon: "events" },
  { to: "/alerts", labelKey: "nav.alerts", icon: "bell", permission: "alert.view" },
  { to: "/cameras", labelKey: "nav.cameras", icon: "cameras" },
  { to: "/storage", labelKey: "nav.storage", icon: "storage" },
  { to: "/system", labelKey: "nav.system", icon: "system" }
]

const visibleNavigation = computed(() =>
  navigation.filter(
    (item) =>
      !("permission" in item) ||
      !item.permission ||
      auth.hasPermission(item.permission)
  )
)

const pageTitle = computed(() => {
  const key = route.meta.titleKey
  return typeof key === "string" ? t(key) : "zero-nvr"
})

const isImmersive = computed(() => route.meta.layout === "immersive")

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

function toggleAccount(): void {
  accountOpen.value = !accountOpen.value
}

async function logout(): Promise<void> {
  accountOpen.value = false
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
    <!-- ================= UNIFI OS ICON DOCK (56px) ================= -->
    <aside class="sidebar">
      <div class="sidebar-top">
        <!-- Protect Shield Logo (Link to Dashboard) -->
        <RouterLink to="/dashboard" class="brand-logo" title="zero-nvr · Dashboard">
          <UiIcon name="cameras" :size="20" />
        </RouterLink>

        <!-- Dock Items -->
        <RouterLink
          v-for="item in visibleNavigation"
          :key="item.to"
          :to="item.to"
          class="dock-icon"
          :class="{'active': route.path.startsWith(item.to)}"
          :title="t(item.labelKey)"
        >
          <UiIcon :name="item.icon" :size="20" />
          <span class="dock-tooltip">
            {{ t(item.labelKey) }}
          </span>
        </RouterLink>
      </div>

      <!-- Bottom: System & User -->
      <div class="sidebar-bottom">
        <ThemeControl class="sidebar-control-btn" />
        <LanguageControl class="sidebar-control-btn" />
        
        <button @click="logout" class="sidebar-control-btn btn-logout" :title="t('shell.signOut')">
          <UiIcon name="logout" :size="18" />
        </button>

        <button @click="toggleAccount" class="user-avatar-btn" :title="t('shell.account')">
          {{ userInitial }}
          <span class="dock-tooltip">
            {{ auth.user?.display_name }} ({{ auth.user?.username }})
          </span>
        </button>
      </div>
    </aside>

    <AccountPanel
      v-if="accountOpen"
      @close="accountOpen = false"
    />

    <!-- Main Workspace -->
    <div class="shell-main">
      <!-- Placeholder Topbar: only shown for non-immersive pages (Dashboard, System, etc.) -->
      <header v-if="!isImmersive" class="placeholder-topbar">
        <strong class="placeholder-topbar__title">{{ pageTitle }}</strong>
      </header>

      <main class="page-surface" :class="{ 'page-surface--immersive': isImmersive }">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background-color: var(--surface-base);
}

.sidebar {
  width: 56px;
  min-width: 56px;
  background-color: var(--surface-nav);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  padding: 14px 0;
  z-index: 40;
  user-select: none;
}

.sidebar-top,
.sidebar-bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  gap: 8px;
}

.brand-logo {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(to top right, #1d4ed8, #2563eb, #6366f1);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
  margin-bottom: 8px;
  cursor: pointer;
  text-decoration: none;
}

.dock-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  transition: all 0.15s ease;
  position: relative;
  cursor: pointer;
  text-decoration: none;
}

.dock-icon:hover {
  color: var(--text-primary);
  background-color: var(--surface-hover);
}

.dock-icon.active {
  color: #ffffff;
  background-color: var(--accent);
  box-shadow: 0 4px 12px var(--accent-soft);
}

.dock-tooltip {
  position: absolute;
  left: 50px;
  background-color: var(--surface-raised);
  color: var(--text-primary);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  border: 1px solid var(--border-subtle);
  transition: opacity 0.2s;
  z-index: 50;
  box-shadow: var(--shadow-menu);
}

.dock-icon:hover .dock-tooltip,
.user-avatar-btn:hover .dock-tooltip {
  opacity: 1;
}

.sidebar-control-btn {
  color: var(--text-secondary);
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s;
}

.sidebar-control-btn:hover {
  color: var(--text-primary);
  background-color: var(--surface-hover);
}

.btn-logout:hover {
  color: var(--danger);
}

.user-avatar-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background-color: var(--accent-soft);
  border: 1px solid var(--accent);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 12px;
  cursor: pointer;
  position: relative;
  margin-top: 4px;
}

.shell-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
  background-color: var(--surface-base);
}

.placeholder-topbar {
  display: flex;
  align-items: center;
  height: 48px;
  padding: 0 16px;
  background-color: var(--surface-nav);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.placeholder-topbar__title {
  font-size: 14px;
  font-weight: 600;
}

.page-surface {
  flex: 1;
  overflow-y: auto;
  position: relative;
}

.page-surface--immersive {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
