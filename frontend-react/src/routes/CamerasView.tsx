import { useState } from "react"
import { Download, Plus, RefreshCw, Upload, Wand2 } from "lucide-react"
import {
  Badge,
  Button,
  Input,
  Select,
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
  PageHeader,
  ProgressBar,
  RowActions,
  Segmented,
  StatCard,
  StatusDot,
  Toolbar,
  ToolbarSpacer,
} from "../components/ui/display"
import { cameras, type Camera } from "../lib/mock"
import { cn } from "../lib/utils"

const healthMeta: Record<
  Camera["health"],
  { label: string; tone: "online" | "offline" | "degraded" | "unknown" }
> = {
  online: { label: "在线", tone: "online" },
  offline: { label: "离线", tone: "offline" },
  degraded: { label: "抖动", tone: "degraded" },
  unknown: { label: "未接入", tone: "unknown" },
}

export function CamerasView() {
  const [q, setQ] = useState("")
  const [group, setGroup] = useState("all")
  const [sel, setSel] = useState<string[]>([])

  const rows = cameras.filter(
    (c) =>
      (group === "all" || c.group === group) &&
      (q === "" || c.name.includes(q) || c.vendor.includes(q)),
  )
  const online = cameras.filter((c) => c.health === "online").length
  const recording = cameras.filter((c) => c.recording).length

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="摄像机"
        description="设备接入、码流档案与用途绑定。一个机位可有多条码流，分别绑定录像 / 预览 / AI 检测 / 抓图 / 音频。"
        actions={
          <>
            <Button variant="outline" size="sm">
              <Upload /> 批量导入
            </Button>
            <Button size="sm">
              <Plus /> 添加机位
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="机位总数" value={cameras.length} unit="路" icon={<Wand2 className="size-4" />} />
        <StatCard label="在线" value={online} unit={`/ ${cameras.length}`} tone="online" />
        <StatCard label="录制中" value={recording} unit="路" tone="online" />
        <StatCard
          label="异常"
          value={cameras.length - online}
          unit="路"
          tone={cameras.length - online > 0 ? "degraded" : "online"}
          hint="1 路离线 · 1 路时钟偏差超阈值"
        />
      </div>

      <Toolbar>
        <Input
          className="w-48"
          placeholder="搜索机位名称 / 厂商"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Select
          className="w-32"
          value={group}
          onChange={(e) => setGroup(e.target.value)}
        >
          <option value="all">全部分组</option>
          <option value="一层">一层</option>
          <option value="室外">室外</option>
          <option value="地下">地下</option>
          <option value="仓库">仓库</option>
        </Select>
        <Segmented
          value="all"
          onChange={() => {}}
          options={[
            { value: "all", label: "全部" },
            { value: "on", label: "在线" },
            { value: "off", label: "离线" },
          ]}
        />
        {sel.length > 0 && (
          <span className="text-xs text-muted-foreground">已选 {sel.length} 项</span>
        )}
        <ToolbarSpacer />
        <Button variant="outline" size="icon-sm" title="刷新">
          <RefreshCw className="size-3.5" />
        </Button>
        <Button variant="outline" size="sm">
          <Download /> 导出 CSV
        </Button>
      </Toolbar>

      <Callout tone="degraded" title="萤石设备不走 ONVIF 接入">
        本页的 ONVIF 探测 / 局域网发现仅适用于能本地直连的设备。萤石无
        Linux SDK、局域网能力只覆盖手机端，事件只经公网 HTTPS WebHook 到达，
        因此它被归为「事件源」配置，不在本页出现。
      </Callout>

      <div className="overflow-hidden rounded-xl border border-border bg-card">
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
              <TH>分组</TH>
              <TH>厂商 / 型号</TH>
              <TH>接入</TH>
              <TH>状态</TH>
              <TH>码流绑定</TH>
              <TH>时钟偏差</TH>
              <TH className="w-24">占用</TH>
              <TH>最后心跳</TH>
              <TH className="text-right">操作</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((c) => {
              const m = healthMeta[c.health]
              return (
                <TR key={c.id}>
                  <TD>
                    <Checkbox
                      checked={sel.includes(c.id)}
                      onChange={(e) =>
                        setSel((prev) =>
                          e.target.checked
                            ? [...prev, c.id]
                            : prev.filter((x) => x !== c.id),
                        )
                      }
                    />
                  </TD>
                  <TD>
                    <div className="flex items-center gap-2">
                      <StatusDot
                        tone={m.tone}
                        pulse={c.health === "online"}
                      />
                      <span className="font-medium">{c.name}</span>
                      {c.aiEnabled && (
                        <Badge variant="outline" className="text-[10px]">
                          AI
                        </Badge>
                      )}
                    </div>
                  </TD>
                  <TD className="text-muted-foreground">{c.group}</TD>
                  <TD className="text-muted-foreground">
                    {c.vendor}
                    <span className="mx-1 text-border">/</span>
                    {c.model}
                  </TD>
                  <TD>
                    <Badge
                      variant={c.protocol === "ONVIF" ? "secondary" : "outline"}
                    >
                      {c.protocol}
                    </Badge>
                  </TD>
                  <TD>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "text-xs",
                          m.tone === "online" && "text-status-online",
                          m.tone === "offline" && "text-status-offline",
                          m.tone === "degraded" && "text-status-degraded",
                          m.tone === "unknown" && "text-muted-foreground",
                        )}
                      >
                        {m.label}
                      </span>
                      {c.recording && (
                        <Badge variant="danger" className="text-[10px]">
                          录制中
                        </Badge>
                      )}
                    </div>
                  </TD>
                  <TD>
                    <div className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
                      <span>录像 · {c.mainStream}</span>
                      <span>预览 · {c.subStream}</span>
                    </div>
                  </TD>
                  <TD>
                    {c.clockSkewMs > 1000 ? (
                      <Badge variant="warning">
                        {(c.clockSkewMs / 1000).toFixed(1)}s
                      </Badge>
                    ) : c.clockSkewMs === 0 ? (
                      <span className="text-xs text-muted-foreground">—</span>
                    ) : (
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {c.clockSkewMs} ms
                      </span>
                    )}
                  </TD>
                  <TD>
                    {c.storageUsedPct > 0 ? (
                      <ProgressBar
                        value={c.storageUsedPct}
                        tone={
                          c.storageUsedPct > 85
                            ? "degraded"
                            : c.storageUsedPct > 0
                              ? "online"
                              : "unknown"
                        }
                        showLabel
                      />
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TD>
                  <TD className="text-xs text-muted-foreground">
                    {c.lastSeen}
                  </TD>
                  <TD>
                    <RowActions>
                      <Button variant="ghost" size="icon-sm" title="编辑">
                        <Wand2 className="size-3.5" />
                      </Button>
                    </RowActions>
                  </TD>
                </TR>
              )
            })}
          </TBody>
        </Table>
      </div>
    </div>
  )
}
