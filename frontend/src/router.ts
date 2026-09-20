import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw
} from "vue-router"

import AppShell from "./layouts/AppShell.vue"
import DashboardView from "./views/DashboardView.vue"
import CamerasView from "./views/CamerasView.vue"
import LoginView from "./views/LoginView.vue"
import SetupView from "./views/SetupView.vue"
import WorkspaceView from "./views/WorkspaceView.vue"
import { useAuthStore } from "./stores/auth"

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: LoginView,
    meta: { public: true, title: "Sign in" }
  },
  {
    path: "/setup",
    name: "setup",
    component: SetupView,
    meta: { public: true, title: "Initial setup" }
  },
  {
    path: "/",
    component: AppShell,
    children: [
      { path: "", redirect: "/dashboard" },
      {
        path: "dashboard",
        name: "dashboard",
        component: DashboardView,
        meta: { title: "Dashboard" }
      },
      {
        path: "live",
        name: "live",
        component: WorkspaceView,
        meta: {
          title: "Live",
          description:
            "Live-view workspace will consume zero-nvr media-session descriptors without exposing camera credentials."
        }
      },
      {
        path: "playback",
        name: "playback",
        component: WorkspaceView,
        meta: {
          title: "Playback",
          description:
            "Historical playback will use Timeline and PlaybackResolver APIs as the storage-independent source of truth."
        }
      },
      {
        path: "events",
        name: "events",
        component: WorkspaceView,
        meta: {
          title: "Events",
          description:
            "Provider-neutral ONVIF, Frigate and system events will appear here through the canonical Event API."
        }
      },
      {
        path: "cameras",
        name: "cameras",
        component: CamerasView,
        meta: { title: "Cameras" }
      },
      {
        path: "storage",
        name: "storage",
        component: WorkspaceView,
        meta: {
          title: "Storage",
          description:
            "Local recording targets, retention and remote archive status will be managed from this workspace."
        }
      },
      {
        path: "system",
        name: "system",
        component: WorkspaceView,
        meta: {
          title: "System",
          description:
            "Health, users, notifications, integrations, backup and audit configuration belong under System."
        }
      }
    ]
  },
  { path: "/:pathMatch(.*)*", redirect: "/dashboard" }
]

export const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.bootstrap()

  document.title = to.meta.title
    ? `${String(to.meta.title)} · zero-nvr`
    : "zero-nvr"

  if (auth.setupRequired) {
    return to.name === "setup" ? true : { name: "setup" }
  }

  if (to.name === "setup") {
    return auth.user ? { name: "dashboard" } : { name: "login" }
  }

  if (to.meta.public) {
    if (to.name === "login" && auth.user) return { name: "dashboard" }
    return true
  }

  if (!auth.user) {
    return {
      name: "login",
      query: { redirect: to.fullPath }
    }
  }

  return true
})
