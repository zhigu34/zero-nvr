<script setup lang="ts">
import { computed } from "vue"

import type { HeatCell, SegmentItem } from "./types"

const props = defineProps<{
  selectedDate: string
  segments: SegmentItem[]
  totalDurationFormatted: string
  activeHeatBinIndex: number | null
}>()

const emit = defineEmits<{
  "select-cell": [cell: HeatCell, index: number]
}>()

// 288 Heatmap grid cells (24 hours * 12 slots = 288 bins)
const heatGrid = computed<HeatCell[]>(() => {
  const cells: HeatCell[] = []
  const [year, month, day] = props.selectedDate.split("-").map(Number)

  for (let h = 0; h < 24; h++) {
    for (let m = 0; m < 12; m++) {
      const startMin = m * 5
      const endMin = startMin + 5
      const timeLabel = `${String(h).padStart(2, "0")}:${String(startMin).padStart(2, "0")}`

      const cellStart = new Date(year, month - 1, day, h, startMin, 0, 0).getTime()
      const cellEnd = new Date(year, month - 1, day, h, endMin, 0, 0).getTime()

      const matched = props.segments.filter((s) => {
        const segStart = s.startDate.getTime()
        const segEnd = s.endDate.getTime()
        return segStart < cellEnd && segEnd > cellStart
      })

      let level = 0
      let bytes = 0
      if (matched.length > 0) {
        bytes = matched.reduce((acc, cur) => acc + cur.bytes, 0)
        const hasLock = matched.some((s) => s.protected)
        const hasEvent = matched.some((s) => s.type === "event")
        if (hasLock) level = 3
        else if (hasEvent) level = 2
        else level = 1
      }

      cells.push({
        hour: h,
        minuteSlot: m,
        timeLabel,
        level,
        count: matched.length,
        bytes
      })
    }
  }
  return cells
})
</script>

<template>
  <!-- 2. 24-hour Recording Heatmap Card (Clean concise header) -->
  <div class="inspector-card-section">
    <div class="section-header">
      <span class="section-title">
        <span class="blue-dot" />
        <span>24 小时录像热力图</span>
      </span>
      <span class="heat-summary-tag">
        {{ segments.length }} 段 · {{ totalDurationFormatted }}
      </span>
    </div>

    <!-- Heatmap Container with Minute Axis -->
    <div class="heatmap-container">
      <!-- Left minute labels (:00 ~ :55) -->
      <div class="heat-minute-axis">
        <span>:00</span>
        <span>:15</span>
        <span>:30</span>
        <span>:45</span>
        <span>:55</span>
      </div>

      <!-- Center 24-column x 12-row grid -->
      <div class="heat-matrix-col">
        <div class="heat-grid-24">
          <button
            v-for="(cell, idx) in heatGrid"
            :key="idx"
            type="button"
            class="heat-cell heat-cell-btn"
            :class="[
              `heat-cell--level-${cell.level}`,
              {
                'recorded': cell.level === 1,
                'warning': cell.level === 2,
                'cloud': cell.level === 3,
                'empty': cell.level === 0,
                'active': activeHeatBinIndex === idx
              }
            ]"
            :title="`[${cell.timeLabel}] ${cell.count > 0 ? `${cell.count} 个切片 · ${(cell.bytes / 1024 / 1024).toFixed(1)} MB` : '无录像'}`"
            @click="emit('select-cell', cell, idx)"
          />
        </div>

        <!-- Hour horizontal labels (00:00 to 24:00) -->
        <div class="heat-hour-axis">
          <span>00:00</span>
          <span>04:00</span>
          <span>08:00</span>
          <span>12:00</span>
          <span>16:00</span>
          <span>20:00</span>
          <span>24:00</span>
        </div>
      </div>
    </div>

    <!-- Heatmap Legend -->
    <div class="heat-legend-row">
      <div class="legend-item"><span class="legend-box bg-blue-600" /><span>录像覆盖</span></div>
      <div class="legend-item"><span class="legend-box bg-purple-500" /><span>远端归档</span></div>
      <div class="legend-item"><span class="legend-box bg-amber-500" /><span>有告警</span></div>
      <div class="legend-item"><span class="legend-box bg-white/10" /><span>无录像</span></div>
    </div>
  </div>

</template>

<style scoped>
.inspector-card-section {
  background-color: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  border-radius: 14px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--uf-text-primary);
}

.blue-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: var(--uf-accent);
  box-shadow: 0 0 8px var(--uf-accent-glow);
  flex-shrink: 0;
}

.heat-summary-tag {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--uf-accent);
  white-space: nowrap;
}

/* Heatmap Section in Inspector */
.heatmap-container {
  display: flex;
  gap: 6px;
  align-items: stretch;
  background: var(--uf-bg-card-sub);
  padding: 8px;
  border-radius: 10px;
  border: 1px solid var(--uf-border);
}

.heat-minute-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  height: 94px;
  font-size: 8px;
  font-family: var(--font-mono);
  color: var(--uf-text-muted);
  width: 16px;
  text-align: right;
  flex-shrink: 0;
  user-select: none;
}

.heat-matrix-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
}

.heat-grid-24 {
  display: grid !important;
  grid-template-columns: repeat(24, minmax(0, 1fr)) !important;
  grid-template-rows: repeat(12, 6px) !important;
  grid-auto-flow: column !important;
  gap: 2px !important;
  width: 100% !important;
}

.heat-cell-btn {
  height: 6px !important;
  min-height: 6px !important;
  border-radius: 1px !important;
  background: var(--uf-bg-hover);
  cursor: pointer;
  border: none;
  padding: 0;
  transition: all 0.12s ease;
  display: block;
  width: 100%;
}

.heat-cell-btn:hover {
  transform: scale(1.3);
  z-index: 30;
  position: relative;
  filter: brightness(1.3);
}

.heat-cell-btn.recorded {
  background: rgba(37, 99, 235, 0.65);
}

.heat-cell-btn.cloud {
  background: #8b5cf6;
  box-shadow: inset 0 0 0 1px #8b5cf6;
}

.heat-cell-btn.warning {
  background: #f59e0b;
  box-shadow: 0 0 4px rgba(245, 158, 11, 0.8);
}

.heat-cell-btn.empty {
  background: var(--uf-bg-hover);
}

.heat-cell-btn.active {
  background: var(--uf-accent) !important;
  outline: 2px solid var(--uf-text-primary);
  outline-offset: 1px;
  box-shadow: 0 0 8px var(--uf-accent-glow);
  z-index: 40;
  position: relative;
  transform: scale(1.3);
}

.heat-hour-axis {
  display: flex;
  justify-content: space-between;
  font-size: 8px;
  font-family: var(--font-mono);
  color: var(--uf-text-muted);
  margin-top: 4px;
  padding: 0 2px;
  user-select: none;
}

.heat-legend-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10px;
  color: var(--uf-text-muted);
  padding-top: 4px;
  border-top: 1px solid var(--uf-border-subtle);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-box {
  width: 7px;
  height: 7px;
  border-radius: 2px;
}

</style>
