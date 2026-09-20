import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw
} from "vue-router"

import AppShell from "./layouts/AppShell.vue"
import DashboardView from "./views/DashboardView.vue"
import CamerasView from "./views/CamerasView.vue"
import EventsView from "./views/EventsView.vue"
import LoginView from "./views/LoginView.vue"
import LiveView from "./views/LiveView.vue"
import PlaybackView from "./views/PlaybackView.vue"
import SetupView from "./views/SetupView.vue"
import StorageView from "./views/StorageView.vue"
import SystemView from "./views/SystemView.vue"
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
        component: LiveView,
        meta: {
          title: "Live"
        }
      },
      {
        path: "playback",
        name: "playback",
        component: PlaybackView,
        meta: {
          title: "Playback"
        }
      },
      {
        path: "events",
        name: "events",
        component: EventsView,
        meta: {
          title: "Events"
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
        component: StorageView,
        meta: {
          title: "Storage"
        }
      },
      {
        path: "system",
        name: "system",
        component: SystemView,
        meta: {
          title: "System"
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
