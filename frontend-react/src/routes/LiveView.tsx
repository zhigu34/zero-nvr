import { useMemo, useState } from "react"

import { LiveTile } from "../components/live/LiveTile"
import {
  Callout,
  EmptyState,
  PageHeader,
  Segmented,
  Toolbar,
  ToolbarSpacer,
} from "../components/ui/display"
import { Button } from "../components/ui/primitives"
import { Checkbox } from "../components/ui/display"
import { useCameras } from "../lib/queries"
import { cn } from "../lib/utils"

/**
 * Live monitoring wall.
 *
 * Layouts are limited to the same slot counts the backend's preview wall
 * accepts (4 / 9 / 16) so that switching a layout here cannot produce a
 * configuration the rest of the media stack would refuse. Note there is no
 * single-tile option: the smallest supported wall is four.
 *
 * Selection is capped at 16 for the same reason, and the cap is enforced in
 * the UI rather than by letting the backend reject the sync message later.
 */

const LAYOUTS = [
  { value: "4", label: "4 画面", columns: 2 },
  { value: "9", label: "9 画面", columns: 3 },
  { value: "16", label: "16 画面", columns: 4 },
] as const

const MAX_TILES = 16

export function LiveView() {
  const camerasQuery = useCameras()
  const [selected, setSelected] = useState<string[]>([])
  const [layout, setLayout] = useState<"4" | "9" | "16">("4")

  const active = useMemo(
    () => camerasQuery.data?.filter((camera) => selected.includes(camera.id)) ?? [],
    [camerasQuery.data, selected],
  )

  const columns = LAYOUTS.find((entry) => entry.value === layout)!.columns
  const capacity = Number(layout)

  const toggle = (cameraId: string) => {
    setSelected((current) => {
      if (current.includes(cameraId)) {
        return current.filter((id) => id !== cameraId)
      }
      if (current.length >= capacity) return current
      return [...current, cameraId]
    })
  }

  if (camerasQuery.isPending) {
    return (
      <div className="p-6">
        <PageHeader title="实时监控" description="正在加载机位列表…" />
      </div>
    )
  }

  if (camerasQuery.isError) {
    return (
      <div className="p-6">
        <PageHeader title="实时监控" />
        <Callout tone="offline" title="无法加载机位列表">
          {camerasQuery.error instanceof Error
            ? camerasQuery.error.message
            : "未知错误"}
        </Callout>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="实时监控"
        description={`已选择 ${active.length} / ${capacity} 路`}
      />

      <Toolbar>
        <Segmented
          options={LAYOUTS.map((entry) => ({
            value: entry.value,
            label: entry.label,
          }))}
          value={layout}
          onChange={(value) => {
            const next = value as "4" | "9" | "16"
            setLayout(next)
            // Shrinking the wall must not leave tiles the layout cannot show.
            setSelected((current) => current.slice(0, Number(next)))
          }}
        />
        <ToolbarSpacer />
        {active.length ? (
          <Button variant="outline" size="sm" onClick={() => setSelected([])}>
            清空
          </Button>
        ) : null}
      </Toolbar>

      <div className="flex flex-1 flex-col gap-3 overflow-auto p-4">
        {camerasQuery.data.length === 0 ? (
          <EmptyState
            title="还没有可监控的机位"
            description="先在机位管理中添加并启用摄像机。"
          />
        ) : null}

        {/*
          The picker stays mounted once a tile is running. Hiding it after the
          first selection left no way to add a second camera without clearing
          the wall, which made a "wall" impossible to build.
        */}
        {camerasQuery.data.length > 0 ? (
          <div className="rounded-lg border border-border p-4">
            <p className="mb-3 text-sm font-medium">
              选择要监控的机位
              <span className="ml-2 text-xs text-muted-foreground">
                当前布局最多 {capacity} 路
              </span>
            </p>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {camerasQuery.data.map((camera) => {
                const chosen = selected.includes(camera.id)
                const full = selected.length >= capacity
                return (
                  <label
                    key={camera.id}
                    className={cn(
                      "flex items-center gap-2 rounded border border-border px-2.5 py-2 text-sm",
                      // A disabled-but-checked row must stay clickable, or the
                      // user cannot deselect the last camera either.
                      full && !chosen && "opacity-50",
                    )}
                  >
                    <Checkbox
                      checked={chosen}
                      disabled={full && !chosen}
                      onChange={() => toggle(camera.id)}
                    />
                    <span className="min-w-0 truncate">{camera.name}</span>
                  </label>
                )
              })}
            </div>
          </div>
        ) : null}

        {active.length > 0 ? (
          <div
            className="grid gap-2"
            style={{
              gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
            }}
          >
            {active.map((camera) => (
              <LiveTile
                key={camera.id}
                cameraId={camera.id}
                cameraName={camera.name}
                className={cn("aspect-video")}
              />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

export { MAX_TILES }
