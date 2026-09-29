<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import AccountPanel from "../components/account/AccountPanel.vue"
import LanguageControl from "../components/ui/LanguageControl.vue"
import ThemeControl from "../components/ui/ThemeControl.vue"
import { useAuthStore } from "../stores/auth"

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n({ useScope: "global" })

const accountOpen = ref(false)

/**
 * 导航项目对齐原型 Dock 顺序：
 * live → playback → files → events(detections) → cameras(devices) → storage → system
 * 原型底部独立放置 system，这里统一排在列表最后保持逻辑一致
 */
const navigation = [
  { to: "/live",     labelKey: "nav.live",     label: "实时监控 (Live View)" },
  { to: "/playback", labelKey: "nav.playback", label: "时光回放 (Time-Lapse)" },
  { to: "/files",    labelKey: "nav.files",    label: "录像文件管理 (Files & WebDAV)" },
  { to: "/events",   labelKey: "nav.events",   label: "事件与告警中心 (Alerts & AI)" },
  { to: "/cameras",  labelKey: "nav.cameras",  label: "机位设备管理 (ONVIF & CSV)" },
  { to: "/storage",  labelKey: "nav.storage",  label: "存储与云归档 (Storage & Cloud)" },
  { to: "/system",   labelKey: "nav.system",   label: "系统运维 & 灾备 (Operations)", bottomGroup: true }
]

const topNavItems = computed(() => navigation.filter(i => !i.bottomGroup))
const bottomNavItems = computed(() => navigation.filter(i => i.bottomGroup))

const pageTitle = computed(() => {
  const key = route.meta.titleKey
  return typeof key === "string" ? t(key) : "zero-nvr"
})

/** 沉浸式视图（live/playback/files）完全接管内容区，隐藏占位 topbar */
const isImmersive = computed(() => route.meta.layout === "immersive")

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

onMounted(startEventStream)
onBeforeUnmount(() => {
  eventSource?.close()
  eventSource = null
})
</script>

<template>
  <div class="app-shell">
    <!-- ================= UNIFI OS ICON DOCK (56px) ================= -->
    <!-- 对应原型 L173-265 的 <aside> dock 结构 -->
    <aside class="sidebar">
      <!-- 上半区：Logo + 主导航 -->
      <div class="sidebar-top">
        <!-- Protect Shield Logo — 对应原型 L177-182 的渐变盾牌图标 -->
        <RouterLink to="/live" class="brand-logo" title="zero-nvr · UniFi Protect">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
               stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            <path d="M9 12l2 2 4-4"/>
          </svg>
        </RouterLink>

        <!-- 主导航图标 — 对应原型 L184-242 -->
        <nav aria-label="Primary navigation">
          <!-- Live View -->
          <RouterLink to="/live" class="dock-icon" :class="{ active: isActive('/live') }"
                      :title="t('nav.live')">
            <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
              <rect x="3" y="3" width="7" height="7" rx="1.5"/>
              <rect x="14" y="3" width="7" height="7" rx="1.5"/>
              <rect x="14" y="14" width="7" height="7" rx="1.5"/>
              <rect x="3" y="14" width="7" height="7" rx="1.5"/>
            </svg>
            <span class="dock-tooltip">实时监控 (Live View)</span>
          </RouterLink>

          <!-- Time-Lapse Playback -->
          <RouterLink to="/playback" class="dock-icon" :class="{ active: isActive('/playback') }"
                      :title="t('nav.playback')">
            <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="9"/>
              <polyline points="12 7 12 12 15 15"/>
            </svg>
            <span class="dock-tooltip">时光回放 (Time-Lapse)</span>
          </RouterLink>

          <!-- Recordings File Manager -->
          <RouterLink to="/files" class="dock-icon" :class="{ active: isActive('/files') }"
                      :title="t('nav.files')">
            <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
              <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
            </svg>
            <span class="dock-tooltip">录像文件管理 (Files & WebDAV)</span>
          </RouterLink>

          <!-- Detections & Alerts (对应 /events 路由) -->
          <RouterLink to="/events" class="dock-icon" :class="{ active: isActive('/events') || isActive('/alerts') }"
                      :title="t('nav.events')">
            <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
            </svg>
            <span class="dock-tooltip">事件与告警中心 (Alerts & AI)</span>
          </RouterLink>

          <!-- Devices & Cameras -->
          <RouterLink to="/cameras" class="dock-icon" :class="{ active: isActive('/cameras') }"
                      :title="t('nav.cameras')">
            <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
              <circle cx="12" cy="13" r="4"/>
            </svg>
            <span class="dock-tooltip">机位设备管理 (ONVIF & CSV)</span>
          </RouterLink>

          <!-- Storage & Cloud Archive -->
          <RouterLink to="/storage" class="dock-icon" :class="{ active: isActive('/storage') }"
                      :title="t('nav.storage')">
            <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
              <path d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"/>
            </svg>
            <span class="dock-tooltip">存储与云归档 (Storage & Cloud)</span>
          </RouterLink>
        </nav>
      </div>

      <!-- 下半区：连接状态 + System + 语言/主题 + 用户头像 -->
      <!-- 对应原型 L245-264 底部区域 -->
      <div class="sidebar-bottom">
        <!--
          TODO(phase-telemetry): WebRTC 实时遥测状态指示点
          后端 API: WebRTC ICE 连接状态（待实现 /api/v1/system/rtc/health）
          原型位置: protect dock L248
          实现说明: 读取 LiveView 的 WebRTC PeerConnection 状态，
                   connected → 绿色呼吸动画，disconnected → 灰色，failed → 红色
          当前: 始终显示灰色占位点
        -->
        <div
          class="webrtc-status-dot"
          title="WebRTC 连接状态（功能开发中）"
        ></div>

        <!-- System Settings -->
        <RouterLink to="/system" class="dock-icon" :class="{ active: isActive('/system') }"
                    :title="t('nav.system')">
          <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
          <span class="dock-tooltip">系统运维 & 灾备 (Operations)</span>
        </RouterLink>

        <!-- Theme / Language (轻量底部控件，不在原型中但保留功能) -->
        <ThemeControl class="sidebar-util-btn" />
        <LanguageControl class="sidebar-util-btn" />

        <!-- User Avatar — 对应原型 L260-263 的用户头像 -->
        <button @click="toggleAccount" class="user-avatar-btn" :title="auth.user?.display_name || 'Account'">
          {{ userInitial }}
          <span class="dock-tooltip">
            {{ auth.user?.display_name || auth.user?.username }}
          </span>
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

/* ===== Dock 侧边栏 ===== */
/* 对应原型: w-14 bg-[#10131b] border-r border-white/5 flex flex-col items-center py-3.5 justify-between */
.sidebar {
  width: 56px;
  min-width: 56px;
  background-color: #10131b;
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  padding: 14px 0;
  z-index: 40;
  user-select: none;
  flex-shrink: 0;
}

.sidebar-top,
.sidebar-bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  gap: 16px;  /* space-y-4 = 16px */
  padding: 0 8px;
}

.sidebar-bottom {
  gap: 12px;
}

/* ===== Shield Logo ===== */
/* 对应原型: w-9 h-9 rounded-xl bg-gradient-to-tr from-blue-700 via-blue-600 to-indigo-500 */
.brand-logo {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  background: linear-gradient(135deg, #1d4ed8, #2563eb, #6366f1);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
  margin-bottom: 8px;
  cursor: pointer;
  text-decoration: none;
  flex-shrink: 0;
}

/* ===== Dock 图标 ===== */
/* 对应原型 CSS: .dock-icon { transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1); position: relative; } */
.dock-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6b7280;   /* text-gray-400 */
  transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
  cursor: pointer;
  text-decoration: none;
  flex-shrink: 0;
}

.dock-icon:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
}

/* 激活状态 — 对应原型: background: var(--uf-blue); box-shadow: 0 0 16px var(--uf-blue-glow) */
.dock-icon.active {
  color: #ffffff;
  background: #006fff;
  box-shadow: 0 0 16px rgba(0, 111, 255, 0.28);
}

/* 激活指示条 — 对应原型 .dock-icon.active::before */
.dock-icon.active::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 25%;
  bottom: 25%;
  width: 3px;
  border-radius: 0 4px 4px 0;
  background: #ffffff;
}

/* ===== Tooltip ===== */
/* 对应原型: absolute left-14 bg-[#1c212e] text-white text-xs px-2.5 py-1 rounded-md */
.dock-tooltip {
  position: absolute;
  left: 52px;
  background-color: #1c212e;
  color: #ffffff;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  border: 1px solid rgba(255, 255, 255, 0.10);
  transition: opacity 0.15s ease;
  z-index: 50;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}

.dock-icon:hover .dock-tooltip,
.user-avatar-btn:hover .dock-tooltip {
  opacity: 1;
}

/* ===== WebRTC 状态指示点 ===== */
/* 对应原型 L248: w-2.5 h-2.5 rounded-full bg-emerald-400 pulse-live
   当前占位显示为灰色静态点，待接入真实 WebRTC 状态后改为绿色 + 动画
   TODO(phase-telemetry): 接入 WebRTC 状态后启用 .webrtc-status-dot--connected 类 */
.webrtc-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background-color: #374151;  /* 灰色占位 */
  cursor: pointer;
  flex-shrink: 0;
}

/* 已连接状态样式（待启用） */
/* .webrtc-status-dot--connected {
  background-color: #10b981;
  animation: uf-pulse 1.8s ease-in-out infinite;
} */

/* ===== 底部工具按钮（主题/语言）===== */
.sidebar-util-btn {
  color: #6b7280;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 6px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, background 0.15s;
}

.sidebar-util-btn:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
}

/* ===== 用户头像 ===== */
/* 对应原型 L261: w-7 h-7 rounded-full bg-blue-600/30 border border-blue-500/50 */
.user-avatar-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background-color: rgba(37, 99, 235, 0.3);
  border: 1px solid rgba(59, 130, 246, 0.5);
  color: #60a5fa;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 12px;
  cursor: pointer;
  position: relative;
  flex-shrink: 0;
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
  height: 48px;
  padding: 0 20px;
  background-color: #10131b;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  flex-shrink: 0;
}

.placeholder-topbar__title {
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
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
