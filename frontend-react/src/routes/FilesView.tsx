import { useEffect, useState } from "react"
import {
  ChevronDown,
  ChevronRight,
  Download,
  FileVideo,
  FolderOpen,
  FolderTree,
  Globe,
  HardDrive,
  Link2,
  Lock,
  Play,
  RefreshCw,
  Share2,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react"
import {
  Badge,
  Button,
  Input,
  Select,
  Separator,
  Switch,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui/primitives"
import {
  Callout,
  Checkbox,
  EmptyState,
  KeyValue,
  PageHeader,
  ProgressBar,
  PrototypeNote,
  RowActions,
  Segmented,
  StatusDot,
  StatusLabel,
} from "../components/ui/display"
import { cameras, segments, TODAY, users, type RecordingSegment } from "../lib/mock"
import { cn } from "../lib/utils"

/* ------------------------------------------------------------------ Model */

const LOCATION: Record<
  RecordingSegment["location"],
  { label: string; tone: "online" | "degraded" | "unknown"; note: string }
> = {
  本地: { label: "本地", tone: "online", note: "主录像盘直读，打开最快" },
  已归档: {
    label: "已归档",
    tone: "degraded",
    note: "已迁至云端归档（OpenList），首次打开需回源，耗时数十秒",
  },
  备份: {
    label: "备份",
    tone: "unknown",
    note: "仅存在于外接备份盘，属冷数据，不保证随时可取",
  },
}

type TreeNode = {
  id: string
  parent?: string
  label: string
  hint: string
  depth: number
  kind: "all" | "camera" | "day" | "hour"
  expandable: boolean
}

/** camera → date → hour, derived from the cameras and segments fixtures. */
function buildTree(): TreeNode[] {
  const rows: TreeNode[] = [
    {
      id: "all",
      label: "全部录像",
      hint: `${segments.length} 片段`,
      depth: 0,
      kind: "all",
      expandable: false,
    },
  ]
  for (const cam of cameras) {
    const segs = segments.filter((s) => s.camera === cam.name)
    const camId = `cam:${cam.name}`
    rows.push({
      id: camId,
      label: cam.name,
      hint: segs.length > 0 ? `${segs.length} 片段` : "无录像",
      depth: 0,
      kind: "camera",
      expandable: segs.length > 0,
    })
    if (segs.length === 0) continue
    const dayId = `day:${cam.name}`
    rows.push({
      id: dayId,
      parent: camId,
      label: `今天 · ${TODAY.slice(5)}`,
      hint: `${segs.length} 片段`,
      depth: 1,
      kind: "day",
      expandable: true,
    })
    const hours = [...new Set(segs.map((s) => s.start.slice(0, 2)))].sort()
    for (const hour of hours) {
      const inHour = segs.filter((s) => s.start.slice(0, 2) === hour)
      rows.push({
        id: `hr:${cam.name}:${hour}`,
        parent: dayId,
        label: `${hour}:00 – ${hour}:59`,
        hint: `${inHour.length} 片段`,
        depth: 2,
        kind: "hour",
        expandable: false,
      })
    }
  }
  return rows
}

const TREE = buildTree()

const PARENT: Record<string, string> = {}
for (const n of TREE) {
  if (n.parent) PARENT[n.id] = n.parent
}

function isVisible(id: string, expanded: string[]) {
  let p = PARENT[id]
  while (p) {
    if (!expanded.includes(p)) return false
    p = PARENT[p]
  }
  return true
}

function matchesNode(seg: RecordingSegment, id: string) {
  if (id === "all") return true
  const [kind, cam, hour] = id.split(":")
  if (kind === "cam" || kind === "day") return seg.camera === cam
  if (kind === "hr") return seg.camera === cam && seg.start.slice(0, 2) === hour
  return true
}

type ExportTask = {
  id: string
  name: string
  progress: number
  state: "running" | "done" | "failed"
}

type ShareLink = {
  id: string
  url: string
  scope: string
  expires: string
  state: "active" | "revoked"
}

/* ------------------------------------------------------------------- Page */

export function FilesView() {
  const [node, setNode] = useState("all")
  const [expanded, setExpanded] = useState<string[]>(["cam:前门人行入口"])
  const [loc, setLoc] = useState("all")
  const [q, setQ] = useState("")
  const [sel, setSel] = useState<string[]>([])
  const [prot, setProt] = useState<Record<string, boolean>>({})

  const [tasks, setTasks] = useState<ExportTask[]>([
    { id: "ex-01", name: "seg-02 · 前门人行入口 14:45", progress: 62, state: "running" },
    { id: "ex-02", name: "seg-07 · 地下车库 B1 入口 12:00", progress: 100, state: "failed" },
  ])

  const [shareOn, setShareOn] = useState(true)
  const [ttl, setTtl] = useState("24h")
  const [seq, setSeq] = useState(2)
  const [links, setLinks] = useState<ShareLink[]>([
    {
      id: "sl-01",
      url: "https://share.zero-nvr.example/s/a7f3k2",
      scope: "seg-02 · 15 分钟片段",
      expires: "10-03 14:52",
      state: "active",
    },
  ])

  // Prototype only: an in-flight export advances so the progress bar is real.
  useEffect(() => {
    const timer = setInterval(() => {
      setTasks((prev) =>
        prev.map((task) =>
          task.state !== "running"
            ? task
            : task.progress >= 100
              ? { ...task, state: "done" }
              : { ...task, progress: task.progress + 4 },
        ),
      )
    }, 600)
    return () => clearInterval(timer)
  }, [])

  const rows = segments.filter(
    (s) =>
      matchesNode(s, node) &&
      (loc === "all" || s.location === loc) &&
      (q === "" || s.camera.includes(q) || s.start.includes(q) || s.id.includes(q)),
  )
  const target = sel.length > 0 ? sel.length : rows.length
  const me = users[0]

  const toggleSel = (id: string, on: boolean) =>
    setSel((prev) => (on ? [...prev, id] : prev.filter((x) => x !== id)))

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <PageHeader
          title="文件"
          description="录像目录浏览与导出。目录按 摄像机 → 日期 → 小时 组织；单个片段导出为 mp4，可选生成公网分享链接。"
          actions={
            <>
              <Badge variant="outline">
                {segments.length} 个片段 · 今日
              </Badge>
              <Button variant="outline" size="sm">
                <RefreshCw /> 刷新
              </Button>
            </>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1">
        {/* ------------------------------------------------ directory tree */}
        <aside className="flex w-64 shrink-0 flex-col border-r border-border">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2.5">
            <FolderTree className="size-4 text-muted-foreground" />
            <span className="text-sm font-semibold">目录</span>
            <span className="ml-auto text-xs tabular-nums text-muted-foreground">
              {cameras.length} 机位
            </span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
            {TREE.filter((n) => isVisible(n.id, expanded)).map((n) => {
              const open = expanded.includes(n.id)
              return (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => {
                    setNode(n.id)
                    if (n.expandable) {
                      setExpanded((prev) =>
                        prev.includes(n.id)
                          ? prev.filter((x) => x !== n.id)
                          : [...prev, n.id],
                      )
                    }
                  }}
                  className={cn(
                    "flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-xs transition-colors hover:bg-accent",
                    node === n.id && "bg-accent text-accent-foreground",
                  )}
                  style={{ paddingLeft: 6 + n.depth * 14 }}
                >
                  {n.expandable ? (
                    open ? (
                      <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                    )
                  ) : (
                    <span className="inline-block size-3.5 shrink-0" />
                  )}
                  {n.kind === "hour" ? (
                    <FileVideo className="size-3.5 shrink-0 text-muted-foreground" />
                  ) : (
                    <FolderOpen className="size-3.5 shrink-0 text-muted-foreground" />
                  )}
                  <span
                    className={cn(
                      "min-w-0 flex-1 truncate",
                      n.kind === "hour"
                        ? "text-muted-foreground"
                        : "font-medium",
                    )}
                  >
                    {n.label}
                  </span>
                  <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                    {n.hint}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="shrink-0 space-y-2 border-t border-border p-3">
            {(
              ["本地", "已归档", "备份"] as const
            ).map((key) => {
              const count = segments.filter((s) => s.location === key).length
              return (
                <StatusLabel
                  key={key}
                  tone={LOCATION[key].tone}
                  className="justify-between"
                >
                  <span className="flex items-center gap-1.5">
                    {LOCATION[key].label}
                    <span className="text-muted-foreground">
                      {LOCATION[key].note}
                    </span>
                  </span>
                  <span className="shrink-0 tabular-nums">{count}</span>
                </StatusLabel>
              )
            })}
            <PrototypeNote>
              原型数据仅含今日片段，因此日期层只有一层。真实目录下日期层会随保留天数展开
              （本地 30 天、归档 90 天）。
            </PrototypeNote>
          </div>
        </aside>

        {/* --------------------------------------------------- segment list */}
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-2">
            <Segmented
              value={loc}
              onChange={setLoc}
              options={[
                { value: "all", label: "全部位置" },
                { value: "本地", label: "本地" },
                { value: "已归档", label: "已归档" },
                { value: "备份", label: "备份" },
              ]}
            />
            <Input
              className="w-40"
              placeholder="搜索片段 / 机位 / 时间"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <span className="text-xs text-muted-foreground">
              {rows.length} 个片段
            </span>
            <span className="ml-auto" />
            {sel.length > 0 && (
              <Button
                variant="ghost"
                size="icon-sm"
                title="清除选择"
                onClick={() => setSel([])}
              >
                <X className="size-3.5" />
              </Button>
            )}
          </div>

          {sel.length > 0 && (
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-muted/50 px-3 py-2">
              <span className="text-xs font-medium">已选 {sel.length} 项</span>
              <span className="text-xs text-muted-foreground">
                将导出为 {target} 个 mp4
              </span>
              <span className="ml-auto" />
              <Button variant="outline" size="sm">
                <Download /> 批量下载
              </Button>
              <Button variant="outline" size="sm">
                <Share2 /> 创建分享链接
                <Badge variant="warning">需操作员</Badge>
              </Button>
              <Button variant="outline" size="sm">
                <Trash2 /> 删除
              </Button>
            </div>
          )}

          <div className="min-h-0 flex-1 overflow-auto">
            {rows.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  icon={<FolderOpen />}
                  title="该目录下没有录像片段"
                  description="机位未录制、已超出保留期，或片段已被归档清理。离线机位不会出现任何片段。"
                />
              </div>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH className="w-10">
                      <Checkbox
                        checked={sel.length === rows.length && rows.length > 0}
                        onChange={(e) =>
                          setSel(e.target.checked ? rows.map((r) => r.id) : [])
                        }
                      />
                    </TH>
                    <TH>机位</TH>
                    <TH>开始时间</TH>
                    <TH>时长</TH>
                    <TH>分辨率</TH>
                    <TH>编码</TH>
                    <TH>大小</TH>
                    <TH>存储位置</TH>
                    <TH className="w-16">保护锁</TH>
                    <TH className="text-right">操作</TH>
                  </TR>
                </THead>
                <TBody>
                  {rows.map((s) => {
                    const meta = LOCATION[s.location]
                    const locked = prot[s.id] ?? s.protected
                    return (
                      <TR key={s.id} className={cn(locked && "bg-status-degraded/5")}>
                        <TD>
                          <Checkbox
                            checked={sel.includes(s.id)}
                            onChange={(e) => toggleSel(s.id, e.target.checked)}
                          />
                        </TD>
                        <TD className="font-medium">{s.camera}</TD>
                        <TD className="tabular-nums">{s.start}</TD>
                        <TD className="tabular-nums text-muted-foreground">
                          {s.duration}
                        </TD>
                        <TD className="text-muted-foreground">{s.resolution}</TD>
                        <TD>
                          <Badge variant={s.codec === "H.265" ? "secondary" : "outline"}>
                            {s.codec}
                          </Badge>
                        </TD>
                        <TD className="tabular-nums">{s.size}</TD>
                        <TD title={meta.note}>
                          <span className="flex items-center gap-1.5">
                            <StatusDot tone={meta.tone} />
                            <span className="text-xs">{meta.label}</span>
                          </span>
                        </TD>
                        <TD>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            title={
                              locked
                                ? "受保护：不被保留策略自动清理，点击解除"
                                : "未受保护：可能被自动清理，点击保护"
                            }
                            onClick={() =>
                              setProt((prev) => ({ ...prev, [s.id]: !locked }))
                            }
                          >
                            <Lock
                              className={cn(
                                "size-3.5",
                                locked
                                  ? "text-status-degraded"
                                  : "text-muted-foreground",
                              )}
                            />
                          </Button>
                        </TD>
                        <TD>
                          <RowActions>
                            <Button variant="ghost" size="icon-sm" title="播放">
                              <Play className="size-3.5" />
                            </Button>
                            <Button variant="ghost" size="icon-sm" title="下载 mp4">
                              <Download className="size-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              title="选中并创建分享链接"
                              onClick={() =>
                                setSel((prev) =>
                                  prev.includes(s.id) ? prev : [...prev, s.id],
                                )
                              }
                            >
                              <Share2 className="size-3.5" />
                            </Button>
                          </RowActions>
                        </TD>
                      </TR>
                    )
                  })}
                </TBody>
              </Table>
            )}
          </div>
        </section>

        {/* ----------------------------------------- export + share panel */}
        <aside className="w-80 shrink-0 space-y-4 overflow-y-auto border-l border-border p-4">
          <section className="space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-sm font-semibold">
                <Download className="size-4 text-muted-foreground" />
                导出任务
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={rows.length === 0}
                onClick={() => {
                  const picks = sel.length > 0 ? sel : rows.map((r) => r.id)
                  picks.forEach((id, i) => {
                    const seg = segments.find((s) => s.id === id)
                    if (!seg) return
                    setTasks((prev) => [
                      ...prev,
                      {
                        id: `ex-${prev.length + 1}-${i}`,
                        name: `${seg.id} · ${seg.camera} ${seg.start}`,
                        progress: 4,
                        state: "running",
                      },
                    ])
                  })
                }}
              >
                导出 {target} 项
              </Button>
            </div>

            {tasks.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
                暂无导出任务
              </p>
            ) : (
              <div className="space-y-2">
                {tasks.map((t) => (
                  <div
                    key={t.id}
                    className="space-y-1.5 rounded-lg border border-border p-2.5"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="min-w-0 flex-1 truncate font-mono text-xs">
                        {t.name}
                      </span>
                      <Badge
                        variant={
                          t.state === "running"
                            ? "default"
                            : t.state === "done"
                              ? "success"
                              : "danger"
                        }
                      >
                        {t.state === "running"
                          ? "转码中"
                          : t.state === "done"
                            ? "完成"
                            : "失败"}
                      </Badge>
                    </div>
                    <ProgressBar
                      value={t.state === "failed" ? 100 : t.progress}
                      tone={
                        t.state === "failed"
                          ? "offline"
                          : t.state === "done"
                            ? "online"
                            : "degraded"
                      }
                      showLabel
                    />
                    {t.state === "failed" && (
                      <p className="flex items-center gap-1 text-[11px] text-status-offline">
                        <TriangleAlert className="size-3" />
                        源片段位于备份盘，冷数据未命中，已中断
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}

            <p className="text-[11px] leading-relaxed text-muted-foreground">
              导出为 mp4 时会转码为 H.264 以保证浏览器可播；H.265 源在多数浏览器中
              无法直接解码，因此导出不保留原始编码。
            </p>
          </section>

          <Separator />

          <section className="space-y-2.5">
            <span className="flex items-center gap-1.5 text-sm font-semibold">
              <Globe className="size-4 text-muted-foreground" />
              公网分享链接
            </span>

            <Callout tone="offline" title="分享链接是全系统唯一免鉴权取用录像的路径">
              拿到链接的人无需登录即可观看该片段，且链接在公网可达、可被转发，无法靠
              内网隔离兜底。创建与撤销仅限 操作员 及以上角色，并写入审计日志
              （操作者、来源 IP、片段 ID）。默认有效期 24 小时。
            </Callout>

            <div className="space-y-1.5 rounded-lg border border-border p-2.5">
              <label className="flex items-center justify-between gap-2 text-xs">
                <span className="text-muted-foreground">允许创建分享链接</span>
                <Switch
                  aria-checked={shareOn}
                  onClick={() => setShareOn((v) => !v)}
                />
              </label>
              <label className="flex items-center justify-between gap-2 text-xs">
                <span className="text-muted-foreground">有效期</span>
                <Select
                  className="h-7 w-28 text-xs"
                  value={ttl}
                  onChange={(e) => setTtl(e.target.value)}
                >
                  <option value="1h">1 小时</option>
                  <option value="24h">24 小时</option>
                  <option value="7d">7 天</option>
                  <option value="forever">永久（不推荐）</option>
                </Select>
              </label>
              <div className="flex items-center gap-2 pt-1">
                <Button
                  size="sm"
                  disabled={!shareOn}
                  onClick={() => {
                    setSeq((n) => n + 1)
                    setLinks((prev) => [
                      {
                        id: `sl-${seq}`,
                        url: `https://share.zero-nvr.example/s/k${seq}9xq`,
                        scope: sel.length > 0 ? `已选 ${sel.length} 个片段` : `当前目录 ${rows.length} 个片段`,
                        expires:
                          ttl === "forever"
                            ? "永久有效"
                            : ttl === "1h"
                              ? "1 小时后"
                              : ttl === "7d"
                                ? "7 天后"
                                : "24 小时后",
                        state: "active",
                      },
                      ...prev,
                    ])
                  }}
                >
                  <Link2 /> 创建链接
                </Button>
                <Badge variant="warning">
                  <Lock className="size-3" />
                  需 操作员
                </Badge>
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {me.username} · {me.role}
                </span>
              </div>
            </div>

            <div className="space-y-1.5">
              {links.length === 0 && (
                <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
                  暂无分享链接
                </p>
              )}
              {links.map((l) => (
                <div
                  key={l.id}
                  className={cn(
                    "space-y-1.5 rounded-lg border p-2.5",
                    l.state === "revoked"
                      ? "border-border bg-muted/40 opacity-70"
                      : "border-status-offline/30",
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    <StatusDot
                      tone={l.state === "revoked" ? "unknown" : "offline"}
                    />
                    <span className="font-mono text-xs break-all">{l.url}</span>
                  </div>
                  <KeyValue label="范围">{l.scope}</KeyValue>
                  <KeyValue label="有效期">{l.expires}</KeyValue>
                  {l.state === "active" ? (
                    <div className="flex justify-end gap-1 pt-1">
                      <Button variant="ghost" size="icon-sm" title="复制链接">
                        <Link2 className="size-3.5" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="text-destructive"
                        onClick={() =>
                          setLinks((prev) =>
                            prev.map((x) =>
                              x.id === l.id ? { ...x, state: "revoked" } : x,
                            ),
                          )
                        }
                      >
                        撤销
                      </Button>
                    </div>
                  ) : (
                    <p className="pt-1 text-right text-[11px] text-muted-foreground">
                      已撤销 · 记录保留于审计日志
                    </p>
                  )}
                </div>
              ))}
            </div>

            <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
              <TriangleAlert className="mt-0.5 size-3 shrink-0 text-status-degraded" />
              撤销只影响链接可达性，已下载的文件无法收回。片段被保留策略清理后链接自动
              失效，但链接本身不随之删除。
            </p>

            <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <HardDrive className="size-3" />
              目标：{sel.length > 0 ? `已选 ${sel.length} 个片段` : `当前目录 ${rows.length} 个片段`}
            </p>
          </section>
        </aside>
      </div>
    </div>
  )
}
