import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw
} from "vue-router"

import AppShell from "./layouts/AppShell.vue"
import AlertsView from "./views/AlertsView.vue"
import DashboardView from "./views/DashboardView.vue"
import CamerasView from "./views/CamerasView.vue"
import EventsView from "./views/EventsView.vue"
import LoginView from "./views/LoginView.vue"
import LiveView from "./views/LiveView.vue"
import PlaybackView from "./views/PlaybackView.vue"
import SetupView from "./views/SetupView.vue"
import StorageView from "./views/StorageView.vue"
import SystemView from "./views/SystemView.vue"
import { i18n } from "./i18n"
import { useAuthStore } from "./stores/auth"

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: LoginView,
    meta: { public: true, titleKey: "route.signIn" }
  },
  {
    path: "/setup",
    name: "setup",
    component: SetupView,
    meta: { public: true, titleKey: "route.initialSetup" }
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
        meta: { titleKey: "route.dashboard" }
      },
      {
        path: "live",
        name: "live",
        component: LiveView,
        meta: {
          titleKey: "route.live"
        }
      },
      {
        path: "playback",
        name: "playback",
        component: PlaybackView,
        meta: {
          titleKey: "route.playback"
        }
      },
      {
        path: "events",
        name: "events",
        component: EventsView,
        meta: {
          titleKey: "route.events"
        }
      },
      {
        path: "alerts",
        name: "alerts",
        component: AlertsView,
        meta: {
          titleKey: "route.alerts"
        }
      },
      {
        path: "cameras",
        name: "cameras",
        component: CamerasView,
        meta: { titleKey: "route.cameras" }
      },
      {
        path: "storage",
        name: "storage",
        component: StorageView,
        meta: {
          titleKey: "route.storage"
        }
      },
      {
        path: "system",
        name: "system",
        component: SystemView,
        meta: {
          titleKey: "route.system"
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

function updateDocumentTitle(
  route: typeof router.currentRoute.value
): void {
  const key = route.meta.titleKey
  document.title =
    typeof key === "string"
      ? `${i18n.global.t(key)} · zero-nvr`
      : "zero-nvr"
}

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.bootstrap()

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

router.afterEach((to) => {
  updateDocumentTitle(to)
})

window.addEventListener(
  "zero-nvr:locale-changed",
  () => updateDocumentTitle(router.currentRoute.value)
)
