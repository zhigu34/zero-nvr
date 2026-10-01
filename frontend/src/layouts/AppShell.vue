<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import AccountPanel from "../components/account/AccountPanel.vue"
import ConfirmDialog from "../components/ui/ConfirmDialog.vue"
import LanguageControl from "../components/ui/LanguageControl.vue"
import ThemeControl from "../components/ui/ThemeControl.vue"
import { useAuthStore } from "../stores/auth"

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n({ useScope: "global" })

const accountOpen = ref(false)

/**
 * 导航顺序沿用原型 Dock（docs/archive/zero_nvr_prototype.html）：业务功能一组、
 * 系统运维独立沉底一组。布局本身是 shadcn-admin 的 sidebar 模式（ADR 0013）。
 */
const navigation = [
  { to: "/live",     labelKey: "nav.live" },
  { to: "/playback", labelKey: "nav.playback" },
  { to: "/files",    labelKey: "nav.files" },
  { to: "/events",   labelKey: "nav.events" },
  { to: "/cameras",  labelKey: "nav.cameras" },
  { to: "/recording-schedules", labelKey: "nav.schedules" },
  { to: "/storage",  labelKey: "nav.storage" },
  { to: "/system",   labelKey: "nav.system", bottomGroup: true }
]

const topNavItems = computed(() => navigation.filter(i => !i.bottomGroup))
const bottomNavItems = computed(() => navigation.filter(i => i.bottomGroup))

const pageTitle = computed(() => {
  const key = route.meta.titleKey
  return typeof key === "string" ? t(key) : "zero-nvr"
})

/** 沉浸式视图（live/playback/files）完全接管内容区，隐藏占位 topbar */
const isImmersive = computed(() => route.meta.layout === "immersive")

const SIDEBAR_STORAGE_KEY = "zero-nvr.sidebar-collapsed"

/** Below this width the labelled sidebar would squeeze the content area, so
     the shell forces the icon rail instead of the user's stored preference. */
const NARROW_VIEWPORT_QUERY = "(max-width: 900px)"

function readStoredCollapsed(): boolean {
  return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "collapsed"
}

/**
 * 侧栏折叠态持久化。shadcn-admin 默认展开；折叠时退化为原先 56px 图标
 * dock 的交互（悬浮 tooltip），老用户肌肉记忆不丢。
 */
const preferredCollapsed = ref(readStoredCollapsed())

/** 窄视口强制折叠（不持久化，仅随视口宽度生效）。 */
const narrowViewport = ref(false)
let narrowQuery: MediaQueryList | null = null

function handleNarrowChange(): void {
  narrowViewport.value = narrowQuery?.matches ?? false
}

const sidebarCollapsed = computed(
  () => preferredCollapsed.value || narrowViewport.value
)

function toggleSidebar(): void {
  preferredCollapsed.value = !preferredCollapsed.value
  window.localStorage.setItem(
    SIDEBAR_STORAGE_KEY,
    preferredCollapsed.value ? "collapsed" : "expanded"
  )
}

const userInitial = computed(() => {
  const source = auth.user?.display_name || auth.user?.username || "Z"
  return source.trim().charAt(0).toUpperCase()
})

function isActive(to: string): boolean {
  return route.path === to || route.path.startsWith(to + "/")
}

let eventSource: EventSource | null = null

function emitRefresh(type: string): void {
  window.dispatchEvent(new CustomEvent("zero-nvr:refresh", { detail: { type } }))
}

function startEventStream(): void {
  if (!auth.hasPermission("system.view") || eventSource) return
  eventSource = new EventSource("/api/v1/system/events/stream")
  eventSource.addEventListener("ready", () => emitRefresh("ready"))
  eventSource.addEventListener("api.mutation", () => emitRefresh("api.mutation"))
}

function toggleAccount(): void {
  accountOpen.value = !accountOpen.value
}

async function logout(): Promise<void> {
  accountOpen.value = false
  await auth.logout()
  await router.push({ name: "login" })
}

onMounted(() => {
  startEventStream()
  if (typeof window.matchMedia === "function") {
    narrowQuery = window.matchMedia(NARROW_VIEWPORT_QUERY)
    narrowViewport.value = narrowQuery.matches
    narrowQuery.addEventListener("change", handleNarrowChange)
  }
})
onBeforeUnmount(() => {
  eventSource?.close()
  eventSource = null
  narrowQuery?.removeEventListener("change", handleNarrowChange)
  narrowQuery = null
})
</script>

<template>
  <div class="app-shell">
    <!-- ================= SHADCN-STYLE SIDEBAR (ADR 0013) ================= -->
    <aside class="sidebar" :class="{ 'sidebar--collapsed': sidebarCollapsed }">
      <!-- 品牌行 + 折叠开关 -->
      <div class="sidebar-header">
        <RouterLink to="/live" class="brand" :title="t('brand.videoSecurity')">
          <span class="brand__mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
                 stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              <path d="M9 12l2 2 4-4"/>
            </svg>
          </span>
          <span v-if="!sidebarCollapsed" class="brand__copy">
            <strong>zero-nvr</strong>
            <span>{{ t("brand.videoSecurity") }}</span>
          </span>
        </RouterLink>
        <button v-if="!narrowViewport" type="button" class="sidebar-collapse-btn"
                :title="t('nav.sidebarCollapse')" @click="toggleSidebar">
          <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"
               :class="{ 'sidebar-collapse-btn__icon--flipped': sidebarCollapsed }">
            <path d="m11 17-5-5 5-5"/>
            <path d="m18 17-5-5 5-5"/>
          </svg>
        </button>
      </div>

      <!-- 主导航 -->
      <nav class="sidebar-nav" aria-label="Primary navigation">
        <p v-if="!sidebarCollapsed" class="sidebar-nav__group-label">{{ t("nav.groupPlatform") }}</p>
        <RouterLink v-for="item in topNavItems" :key="item.to" :to="item.to" class="sidebar-item"
                    :class="{ 'sidebar-item--active': isActive(item.to) }" :title="t(item.labelKey)">
          <svg v-if="item.to === '/live'" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <rect x="3" y="3" width="7" height="7" rx="1.5"/>
            <rect x="14" y="3" width="7" height="7" rx="1.5"/>
            <rect x="14" y="14" width="7" height="7" rx="1.5"/>
            <rect x="3" y="14" width="7" height="7" rx="1.5"/>
          </svg>
          <svg v-else-if="item.to === '/playback'" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="9"/>
            <polyline points="12 7 12 12 15 15"/>
          </svg>
          <svg v-else-if="item.to === '/files'" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
          </svg>
          <svg v-else-if="item.to === '/events'" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
          </svg>
          <svg v-else-if="item.to === '/cameras'" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
            <circle cx="12" cy="13" r="4"/>
          </svg>
          <svg v-else-if="item.to === '/recording-schedules'" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
            <line x1="16" y1="2" x2="16" y2="6"/>
            <line x1="8" y1="2" x2="8" y2="6"/>
            <line x1="3" y1="10" x2="21" y2="10"/>
            <path d="M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01M16 18h.01"/>
          </svg>
          <svg v-else width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <path d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"/>
          </svg>
          <span v-if="!sidebarCollapsed" class="sidebar-item__label">{{ t(item.labelKey) }}</span>
        </RouterLink>

        <template v-for="item in bottomNavItems" :key="item.to">
          <p v-if="!sidebarCollapsed" class="sidebar-nav__group-label">{{ t("nav.groupSystem") }}</p>
          <RouterLink :to="item.to" class="sidebar-item" :class="{ 'sidebar-item--active': isActive(item.to) }"
                      :title="t(item.labelKey)">
            <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            <span v-if="!sidebarCollapsed" class="sidebar-item__label">{{ t(item.labelKey) }}</span>
          </RouterLink>
        </template>
      </nav>

      <!-- 底部：主题/语言 + 用户 -->
      <div class="sidebar-footer">
        <div v-if="!sidebarCollapsed" class="sidebar-footer__utils">
          <!--
            TODO(phase-telemetry): WebRTC 实时遥测状态指示点
            后端 API: WebRTC ICE 连接状态（待实现 /api/v1/system/rtc/health）
            实现说明: 读取 LiveView 的 WebRTC PeerConnection 状态，
                     connected → 绿色呼吸动画，disconnected → 灰色，failed → 红色
            当前: 始终显示灰色占位点
          -->
          <span class="webrtc-status-dot" :title="t('nav.webrtcPlaceholder')"></span>
          <ThemeControl />
          <LanguageControl />
        </div>
        <template v-else>
          <ThemeControl />
          <LanguageControl />
        </template>

        <button type="button" class="sidebar-user" @click="toggleAccount"
                :title="auth.user?.display_name || auth.user?.username || 'Account'">
          <span class="sidebar-user__avatar" aria-hidden="true">{{ userInitial }}</span>
          <span v-if="!sidebarCollapsed" class="sidebar-user__meta">
            <strong>{{ auth.user?.display_name || auth.user?.username }}</strong>
            <span>{{ t("nav.accountManage") }}</span>
          </span>
          <svg v-if="!sidebarCollapsed" class="sidebar-user__chevron" width="14" height="14" fill="none"
               stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <path d="m9 18 6-6-6-6"/>
          </svg>
        </button>
      </div>
    </aside>

    <AccountPanel v-if="accountOpen" @close="accountOpen = false" />

    <!-- ================= 主内容区 ================= -->
    <div class="shell-main">
      <!-- 非沉浸式页面（Dashboard/System/Cameras 等）显示通用 topbar -->
      <header v-if="!isImmersive" class="placeholder-topbar">
        <strong class="placeholder-topbar__title">{{ pageTitle }}</strong>
      </header>

      <!-- 沉浸式视图（Live/Playback/Files）完全接管，flex-col 铺满 -->
      <main class="page-surface" :class="{ 'page-surface--immersive': isImmersive }">
        <RouterView />
      </main>
    </div>

    <!-- Single confirmation dialog for the whole app: callers raise it with
         `await confirmAction({...})` instead of window.confirm. -->
    <ConfirmDialog />
  </div>
</template>

<style scoped>
/* ===== App Shell 骨架 ===== */
.app-shell {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background-color: var(--surface-base);
}

/* ===== shadcn 式侧栏：展开 264px / 折叠 60px（ADR 0013） ===== */
.sidebar {
  position: relative;
  display: flex;
  width: 264px;
  min-width: 264px;
  flex-direction: column;
  overflow: hidden;
  background-color: var(--uf-bg-dock);
  border-right: 1px solid var(--uf-border);
  transition: width 180ms ease, min-width 180ms ease;
  z-index: 40;
  user-select: none;
  flex-shrink: 0;
}

.sidebar--collapsed {
  width: 60px;
  min-width: 60px;
}

/* --- 品牌行 --- */
.sidebar-header {
  display: flex;
  min-height: 56px;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border-bottom: 1px solid var(--uf-border-subtle);
}

.brand {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 10px;
  padding: 6px 4px;
  border-radius: var(--radius-md);
  text-decoration: none;
}

.brand__mark {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  border-radius: var(--radius-md);
  background: var(--accent);
  color: var(--text-on-accent);
}

.brand__copy {
  min-width: 0;
  white-space: nowrap;
}

.brand__copy strong {
  display: block;
  font-size: 13px;
  font-weight: 620;
  letter-spacing: -0.01em;
  color: var(--uf-text-primary);
}

.brand__copy span {
  display: block;
  margin-top: 1px;
  font-size: 10px;
  color: var(--uf-text-muted);
}

.sidebar-collapse-btn {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  place-items: center;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--uf-text-muted);
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.sidebar-collapse-btn:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.sidebar-collapse-btn__icon--flipped {
  transform: rotate(180deg);
}

/* --- 导航 --- */
.sidebar-nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  padding: 10px 8px;
}

.sidebar-nav__group-label {
  margin: 14px 8px 4px;
  font-size: 11px;
  font-weight: 550;
  letter-spacing: 0.04em;
  color: var(--uf-text-muted);
  white-space: nowrap;
}

.sidebar-nav__group-label:first-child {
  margin-top: 2px;
}

.sidebar-item {
  position: relative;
  display: flex;
  min-height: 34px;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border-radius: var(--radius-md);
  color: var(--uf-text-secondary);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  text-decoration: none;
  transition: background-color 140ms ease, color 140ms ease;
}

.sidebar-item svg {
  flex: 0 0 18px;
}

.sidebar-item:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.sidebar-item--active,
.sidebar-item--active:hover {
  background: var(--uf-bg-active);
  color: var(--text-primary);
  font-weight: 600;
}

.sidebar-item--active svg {
  color: var(--accent);
}

/* 折叠态的名称提示由原生 title 属性承担：自定义浮层会被侧栏的
   overflow/滚动容器裁剪，portal 化 tooltip 不值得为此引入。 */

/* --- 底部区 --- */
.sidebar-footer {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 8px 12px;
  border-top: 1px solid var(--uf-border-subtle);
}

.sidebar-footer__utils {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 4px;
}

.sidebar--collapsed .sidebar-footer__utils {
  justify-content: center;
}

.sidebar--collapsed .sidebar-footer > * {
  align-self: center;
}

/* WebRTC 占位指示点 —— 语义见模板内 TODO(phase-telemetry) */
.webrtc-status-dot {
  width: 8px;
  height: 8px;
  margin-right: auto;
  border-radius: 50%;
  background: var(--uf-border-strong);
  cursor: default;
}

.sidebar-user {
  position: relative;
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 10px;
  padding: 4px 6px;
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--uf-text-secondary);
  cursor: pointer;
  text-align: left;
  transition: background-color 140ms ease;
}

.sidebar-user:hover {
  background: var(--uf-bg-hover);
}

.sidebar-user__avatar {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  place-items: center;
  border-radius: 50%;
  background: var(--uf-bg-active);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 650;
}

.sidebar-user__meta {
  min-width: 0;
  white-space: nowrap;
}

.sidebar-user__meta strong {
  display: block;
  overflow: hidden;
  font-size: 12.5px;
  font-weight: 570;
  color: var(--uf-text-primary);
  text-overflow: ellipsis;
}

.sidebar-user__meta > span {
  display: block;
  font-size: 10.5px;
  color: var(--uf-text-muted);
}

.sidebar-user__chevron {
  margin-left: auto;
  color: var(--uf-text-muted);
}

/* ===== 主内容区 ===== */
.shell-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background-color: var(--surface-base);
  min-width: 0;
}

/* 普通页面的通用标题栏 */
.placeholder-topbar {
  display: flex;
  align-items: center;
  height: 52px;
  padding: 0 20px;
  background-color: var(--uf-bg-header);
  border-bottom: 1px solid var(--uf-border);
  flex-shrink: 0;
}

.placeholder-topbar__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--uf-text-primary);
}

/* 内容页面 */
.page-surface {
  flex: 1;
  overflow-y: auto;
  position: relative;
  min-height: 0;
}

/* 沉浸式媒体视图：Live / Playback / Files
   这些视图自带 header，不需要 placeholder-topbar，
   通过 display:flex + flex-direction:column 确保子视图可以用 100% 高度 */
.page-surface--immersive {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
