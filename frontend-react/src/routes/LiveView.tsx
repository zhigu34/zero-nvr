import { useState } from "react"
import {
  Camera,
  Grid2x2,
  Grid3x3,
  LayoutGrid,
  Maximize2,
  Save,
  Square,
  Volume2,
  VolumeX,
} from "lucide-react"
import { Badge, Button, Input, Select } from "../components/ui/primitives"
import {
  Callout,
  Segmented,
  StatusDot,
  Toolbar,
  ToolbarSpacer,
} from "../components/ui/display"
import { cameras } from "../lib/mock"
import { cn } from "../lib/utils"

const TILES = [
  { cam: cameras[0], transport: "WebRTC", hls: false },
  { cam: cameras[1], transport: "WebRTC", hls: false },
  { cam: cameras[2], transport: "WebRTC", hls: false },
  { cam: cameras[5], transport: "HLS", hls: true },
  { cam: cameras[6], transport: "WebRTC", hls: false },
  { cam: cameras[7], transport: "WebRTC", hls: false },
  { cam: cameras[9], transport: "HLS", hls: true },
  { cam: cameras[3], transport: "HLS", hls: true, degraded: true },
  { cam: cameras[4], transport: "—", hls: false, down: true },
]

/** A tile with no real stream: dark panel, name, clock, and a transport tag. */
function Tile({ t }: { t: (typeof TILES)[number] }) {
  const [muted, setMuted] = useState(true)

  return (
    <div className="group relative aspect-video overflow-hidden rounded-lg border border-border bg-neutral-950">
      {/* Faux picture area — diagonals so it never reads as a real feed. */}
      <div
        className="absolute inset-0 opacity-[0.18]"
        style={{
          backgroundImage:
            "repeating-linear-gradient(45deg, #fff 0 1px, transparent 1px 14px)",
        }}
      />
      {t.down ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 text-neutral-500">
          <Camera className="size-6" />
          <p className="text-xs">无信号</p>
          <p className="text-[10px] text-neutral-600">最后心跳 2 小时 14 分前</p>
        </div>
      ) : (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="rounded bg-black/45 px-2 py-0.5 text-[10px] text-neutral-400">
            静态原型 · 无真实画面
          </span>
        </div>
      )}

      {/* Top overlay */}
      <div className="absolute inset-x-0 top-0 flex items-center gap-1.5 bg-gradient-to-b from-black/70 to-transparent p-2">
        {t.cam.health === "online" && (
          <StatusDot tone={t.cam.recording ? "offline" : "online"} />
        )}
        <span className="truncate text-xs font-medium text-white">{t.cam.name}</span>
        <span className="ml-auto shrink-0 text-[10px] tabular-nums text-neutral-300">
          14:58:{String(t.cam.id.length * 7).padStart(2, "0")}
        </span>
      </div>

      {/* Bottom overlay */}
      {!t.down && (
        <div className="absolute inset-x-0 bottom-0 flex items-center gap-1.5 bg-gradient-to-t from-black/75 to-transparent p-2 opacity-0 transition-opacity group-hover:opacity-100">
          <Badge
            variant={t.transport === "WebRTC" ? "success" : t.degraded ? "warning" : "secondary"}
            className="bg-black/40 text-[10px] text-white backdrop-blur-sm"
          >
            {t.transport}
          </Badge>
          <span className="text-[10px] text-neutral-400">
            {t.cam.subStream}
          </span>
          <span className="ml-auto flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setMuted((v) => !v)}
              className="size-6 text-white hover:bg-white/15"
              title={muted ? "打开音频" : "静音"}
            >
              {muted ? <VolumeX className="size-3.5" /> : <Volume2 className="size-3.5" />}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              className="size-6 text-white hover:bg-white/15"
              title="抓图"
            >
              <Square className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              className="size-6 text-white hover:bg-white/15"
              title="全屏"
            >
              <Maximize2 className="size-3.5" />
            </Button>
          </span>
        </div>
      )}

      {t.degraded && (
        <div className="absolute inset-x-0 top-8 flex items-center justify-center">
          <span className="rounded bg-status-degraded/90 px-1.5 py-0.5 text-[10px] font-medium text-black">
            H.265 不支持 WebRTC · 已回退 HLS
          </span>
        </div>
      )}
    </div>
  )
}

export function LiveView() {
  const [grid, setGrid] = useState("4")
  const [filter, setFilter] = useState("all")

  const cols =
    grid === "2" ? "sm:grid-cols-2" : grid === "4" ? "sm:grid-cols-2 xl:grid-cols-4" : "sm:grid-cols-2 lg:grid-cols-3"

  const shown = filter === "rec" ? TILES.filter((t) => t.cam.recording) : TILES

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 p-4 pb-3">
        <Toolbar>
          <Segmented
            value={grid}
            onChange={setGrid}
            options={[
              { value: "2", label: <Grid2x2 /> },
              { value: "4", label: <LayoutGrid /> },
              { value: "9", label: <Grid3x3 /> },
            ]}
          />
          <Select
            className="w-36"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">全部机位</option>
            <option value="rec">仅录制中</option>
            <option value="offline">仅离线</option>
          </Select>
          <Select className="w-32" defaultValue="layout-a">
            <option value="layout-a">布局：默认九宫格</option>
            <option value="layout-b">布局：大门 + 周界</option>
            <option value="layout-c">布局：仓库巡检</option>
          </Select>
          <Input className="w-44" placeholder="按名称过滤机位" />
          <ToolbarSpacer />
          <Button variant="outline" size="sm">
            <Save /> 保存为个人布局
          </Button>
        </Toolbar>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
        <div className={cn("grid gap-2.5", cols)}>
          {shown.map((t) => (
            <Tile key={t.cam.id} t={t} />
          ))}
        </div>

        <div className="mt-3 space-y-2">
          <Callout tone="degraded" title="传输选择说明">
            瓦片按 WebRTC（WHEP）优先、失败回退 HLS；H.265 码流浏览器无法解码，强制走
            HLS。原型中「电梯厅（东）」演示了这一回退路径。
          </Callout>
        </div>
      </div>
    </div>
  )
}
