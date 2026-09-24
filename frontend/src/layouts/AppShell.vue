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

const sidebarOpen = ref(false)
const sidebarCollapsed = ref(
  window.localStorage.getItem("zero-nvr.sidebar-collapsed") === "1"
)
const accountOpen = ref(false)

const navigation = [
  { to: "/dashboard", labelKey: "nav.dashboard", icon: "dashboard" },
  { to: "/live", labelKey: "nav.live", icon: "live" },
  { to: "/playback", labelKey: "nav.playback", icon: "playback" },
  { to: "/events", labelKey: "nav.events", icon: "events" },
  {
    to: "/alerts",
    labelKey: "nav.alerts",
    icon: "bell",
    permission: "alert.view"
  },
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
          <span>{{ t("brand.videoSecurity") }}</span>
        </div>
      </div>

      <nav class="primary-nav" :aria-label="t('shell.primaryNavigation')">
        <RouterLink
          v-for="item in visibleNavigation"
          :key="item.to"
          :to="item.to"
          class="primary-nav__item"
          :title="sidebarCollapsed ? t(item.labelKey) : undefined"
          @click="sidebarOpen = false"
        >
          <UiIcon class="primary-nav__icon" :name="item.icon" :size="18" />
          <span class="primary-nav__label">{{ t(item.labelKey) }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar__footer">
        <span class="status-dot status-dot--ok" />
        <span class="sidebar__footer-label">{{ t("shell.coreOnline") }}</span>
      </div>
    </aside>

    <button
      v-if="sidebarOpen"
      class="sidebar-backdrop"
      :aria-label="t('shell.closeNavigation')"
      @click="sidebarOpen = false"
    />

    <div class="shell-main">
      <header class="topbar">
        <div class="topbar__left">
          <button
            class="icon-button topbar-icon-button"
            type="button"
            :aria-label="t('shell.toggleNavigation')"
            :title="t('shell.toggleNavigation')"
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
          <LanguageControl />
          <ThemeControl />

          <button
            class="topbar__user"
            :class="{ 'topbar__user--active': accountOpen }"
            type="button"
            :aria-label="t('shell.openAccount')"
            :title="t('shell.account')"
            @click="toggleAccount"
          >
            <span class="user-avatar">{{ userInitial }}</span>
            <div class="topbar__identity">
              <strong>{{ auth.user?.display_name }}</strong>
              <span>{{ auth.user?.username }}</span>
            </div>
          </button>

          <button
            class="icon-button topbar-icon-button"
            type="button"
            :aria-label="t('shell.signOut')"
            :title="t('shell.signOut')"
            @click="logout"
          >
            <UiIcon name="logout" :size="17" />
          </button>
        </div>
      </header>

      <AccountPanel
        v-if="accountOpen"
        @close="accountOpen = false"
      />

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
