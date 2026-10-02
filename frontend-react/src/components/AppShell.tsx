import { useEffect, useState } from "react"
import { ChevronDown, Menu, Moon, PanelLeftClose, Sun } from "lucide-react"
import { useTheme } from "../hooks/use-theme"
import { navigation, type NavItem } from "../lib/navigation"
import { AuditView } from "../routes/AuditView"
import { AlertsView } from "../routes/AlertsView"
import { CamerasView } from "../routes/CamerasView"
import { EventsView } from "../routes/EventsView"
import { FilesView } from "../routes/FilesView"
import { LiveView } from "../routes/LiveView"
import { PlaybackView } from "../routes/PlaybackView"
import { SchedulesView } from "../routes/SchedulesView"
import { StorageView } from "../routes/StorageView"
import { SystemView } from "../routes/SystemView"
import { TimelineView } from "../routes/TimelineView"
import { UsersView } from "../routes/UsersView"
import { cn } from "../lib/utils"

const PAGES: Record<string, () => React.JSX.Element> = {
  live: LiveView,
  playback: PlaybackView,
  timeline: TimelineView,
  cameras: CamerasView,
  schedules: SchedulesView,
  events: EventsView,
  alerts: AlertsView,
  storage: StorageView,
  files: FilesView,
  system: SystemView,
  users: UsersView,
  audit: AuditView,
}

function readHash() {
  const key = window.location.hash.replace(/^#\/?/, "")
  return key && key in PAGES ? key : "live"
}

export function App() {
  const [active, setActive] = useState(readHash)
  const [collapsed, setCollapsed] = useState(false)
  const { isDark, toggle } = useTheme()

  useEffect(() => {
    const onHash = () => setActive(readHash())
    window.addEventListener("hashchange", onHash)
    return () => window.removeEventListener("hashchange", onHash)
  }, [])

  const go = (key: string) => {
    window.location.hash = `/${key}`
    setActive(key)
  }

  const current: NavItem =
    navigation.flatMap((g) => g.items).find((i) => i.key === active) ??
    navigation[0].items[0]
  const Page = PAGES[active] ?? PAGES.live

  return (
    <div className="flex h-svh w-full overflow-hidden bg-background text-foreground">
      <aside
        className={cn(
          "flex shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200",
          collapsed ? "w-[60px]" : "w-[248px]",
        )}
      >
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-sidebar-border px-4">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <span className="text-xs font-bold">Z</span>
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">zero-nvr</p>
              <p className="truncate text-[10px] text-muted-foreground">
                静态原型
              </p>
            </div>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto px-2.5 py-3">
          {navigation.map((group) => (
            <div key={group.label} className="mb-4 last:mb-0">
              {!collapsed && (
                <p className="mb-1 px-2 text-[11px] font-medium text-muted-foreground">
                  {group.label}
                </p>
              )}
              <ul className="space-y-0.5">
                {group.items.map((item) => (
                  <li key={item.key}>
                    <button
                      type="button"
                      onClick={() => go(item.key)}
                      title={collapsed ? item.label : undefined}
                      className={cn(
                        "flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors",
                        active === item.key
                          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                          : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                      )}
                    >
                      <item.icon className="size-4 shrink-0" />
                      {!collapsed && (
                        <span className="truncate">{item.label}</span>
                      )}
                      {!collapsed && item.badge === "optional" && (
                        <span className="ml-auto rounded border border-border px-1 text-[10px] text-muted-foreground">
                          可选
                        </span>
                      )}
                      {!collapsed && item.badge === "not-configured" && (
                        <span className="ml-auto rounded border border-status-degraded/40 px-1 text-[10px] text-status-degraded">
                          未接入
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-sidebar-border p-2.5">
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent/60"
          >
            {collapsed ? (
              <Menu className="size-4" />
            ) : (
              <PanelLeftClose className="size-4" />
            )}
            {!collapsed && <span>收起侧边栏</span>}
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background px-5">
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">{current.label}</h1>
          </div>
          <button
            type="button"
            onClick={toggle}
            className="flex size-8 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            title="切换主题"
          >
            {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
          <button
            type="button"
            className="flex items-center gap-2 rounded-lg border border-border py-1 pl-1.5 pr-2.5 transition-colors hover:bg-accent"
          >
            <span className="flex size-6 items-center justify-center rounded-md bg-primary/10 text-[10px] font-medium text-primary">
              AD
            </span>
            <span className="text-left leading-tight">
              <span className="block text-xs font-medium">admin</span>
              <span className="block text-[10px] text-muted-foreground">
                管理员
              </span>
            </span>
            <ChevronDown className="size-3 text-muted-foreground" />
          </button>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto">
          <Page />
        </main>
      </div>
    </div>
  )
}
