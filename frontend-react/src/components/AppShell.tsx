import { useState } from "react"
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router"
import {
  ChevronDown,
  KeyRound,
  LogOut,
  Menu,
  Moon,
  PanelLeftClose,
  Sun,
  User as UserIcon,
} from "lucide-react"
import { useTheme } from "../hooks/use-theme"
import { navigation } from "../lib/navigation"
import { cn } from "../lib/utils"
import { useAuthStore } from "../stores/auth"
import { ChangePasswordDialog } from "../routes/ChangePasswordDialog"

const ROLE_LABEL: Record<string, string> = {
  Administrator: "管理员",
  Operator: "操作员",
  Viewer: "浏览者",
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)
  const { isDark, toggle } = useTheme()
  const navigate = useNavigate()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const user = useAuthStore((s) => s.user)
  const atLeast = useAuthStore((s) => s.atLeast)
  const logout = useAuthStore((s) => s.logout)

  const groups = navigation
    .map((g) => ({ ...g, items: g.items.filter((i) => atLeast(i.requires)) }))
    .filter((g) => g.items.length > 0)

  const current = navigation
    .flatMap((g) => g.items)
    .find((i) => pathname === i.path)

  async function onLogout() {
    setMenuOpen(false)
    await logout()
    await navigate({ to: "/login" })
  }

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
                {user?.display_name ?? "—"}
              </p>
            </div>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto px-2.5 py-3">
          {groups.map((group) => (
            <div key={group.label} className="mb-4 last:mb-0">
              {!collapsed && (
                <p className="mb-1 px-2 text-[11px] font-medium text-muted-foreground">
                  {group.label}
                </p>
              )}
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const active = pathname === item.path
                  return (
                    <li key={item.key}>
                      <Link
                        to={item.path}
                        title={collapsed ? item.label : undefined}
                        className={cn(
                          "flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors",
                          active
                            ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                            : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                        )}
                      >
                        <item.icon className="size-4 shrink-0" />
                        {!collapsed && <span className="truncate">{item.label}</span>}
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
                        {!collapsed && atLeast(item.manage) === false && (
                          <span
                            className="ml-auto rounded border border-border px-1 text-[10px] text-muted-foreground"
                            title="当前角色只能查看"
                          >
                            只读
                          </span>
                        )}
                      </Link>
                    </li>
                  )
                })}
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
        <header className="relative flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background px-5">
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">
              {current?.label ?? "zero-nvr"}
            </h1>
          </div>

          <button
            type="button"
            onClick={toggle}
            className="flex size-8 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            title="切换主题"
          >
            {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>

          <div className="relative">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="flex items-center gap-2 rounded-lg border border-border py-1 pl-1.5 pr-2.5 transition-colors hover:bg-accent"
            >
              <span className="flex size-6 items-center justify-center rounded-md bg-primary/10 text-[10px] font-medium text-primary">
                {initials(user?.display_name ?? user?.username ?? "?")}
              </span>
              <span className="text-left leading-tight">
                <span className="block text-xs font-medium">
                  {user?.display_name ?? user?.username ?? "—"}
                </span>
                <span className="block text-[10px] text-muted-foreground">
                  {user?.roles.map((r) => ROLE_LABEL[r] ?? r).join(" / ") || "—"}
                </span>
              </span>
              <ChevronDown className="size-3 text-muted-foreground" />
            </button>

            {menuOpen && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setMenuOpen(false)}
                  aria-hidden
                />
                <div className="absolute right-0 top-full z-20 mt-1 w-56 overflow-hidden rounded-lg border border-border bg-popover p-1 shadow-md">
                  <div className="border-b border-border px-3 py-2">
                    <p className="truncate text-xs font-medium">
                      {user?.display_name}
                    </p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {user?.username}
                      {user?.email ? ` · ${user.email}` : ""}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false)
                      setPwdOpen(true)
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent"
                  >
                    <KeyRound className="size-3.5 text-muted-foreground" />
                    修改密码
                  </button>
                  <Link
                    to="/users"
                    onClick={() => setMenuOpen(false)}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent"
                  >
                    <UserIcon className="size-3.5 text-muted-foreground" />
                    用户与权限
                  </Link>
                  <button
                    type="button"
                    onClick={onLogout}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm text-destructive transition-colors hover:bg-destructive/8"
                  >
                    <LogOut className="size-3.5" />
                    退出登录
                  </button>
                </div>
              </>
            )}
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto" data-layout={current?.layout ?? "standard"}>
          <Outlet />
        </main>
      </div>

      <ChangePasswordDialog open={pwdOpen} onClose={() => setPwdOpen(false)} />
    </div>
  )
}

function initials(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return "?"
  if (/^[\x00-\x7F]+$/.test(trimmed)) {
    return trimmed.slice(0, 2).toUpperCase()
  }
  return trimmed.slice(0, 1)
}
