<script setup lang="ts">
import { computed } from "vue"

interface MonthDayStats {
  count: number
  bytes: number
  durationSec: number
  cloudCount: number
}

const props = defineProps<{
  selectedDate: string
  todayDate: string
  segmentsCount: number
  totalBytes: number
  totalDurationSec: number
  monthSegmentsMap: ReadonlyMap<string, MonthDayStats>
}>()

const emit = defineEmits<{
  "shift-month": [delta: number]
  "select-date": [date: string]
}>()

function formatDurationCompact(sec: number): string {
  if (!sec || sec <= 0) return ""
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (h >= 24) return "24h"
  if (h > 0 && m > 0) return `${h}h${m}m`
  if (h > 0) return `${h}h`
  if (m > 0) return `${m}m`
  return `${sec}s`
}

// Current month calendar days (7-column grid)
const currentYearMonthTitle = computed<string>(() => {
  const [year, month] = props.selectedDate.split("-").map(Number)
  return `${year} 年 ${month} 月`
})

const prevMonthName = computed<string>(() => {
  const [year, month] = props.selectedDate.split("-").map(Number)
  const prevM = month === 1 ? 12 : month - 1
  return `${prevM}月`
})

const nextMonthName = computed<string>(() => {
  const [year, month] = props.selectedDate.split("-").map(Number)
  const nextM = month === 12 ? 1 : month + 1
  return `${nextM}月`
})

// Genuine month summary calculations
const activeDaysInMonth = computed<number>(() => {
  const countedDates = new Set<string>()
  const ymPrefix = props.selectedDate.slice(0, 7)
  for (const [dateStr, info] of props.monthSegmentsMap) {
    if (dateStr.startsWith(ymPrefix) && info.count > 0) {
      countedDates.add(dateStr)
    }
  }
  if (props.segmentsCount > 0 && props.selectedDate.startsWith(ymPrefix)) {
    countedDates.add(props.selectedDate)
  }
  return countedDates.size
})

const monthTotalSegments = computed<number>(() => {
  let total = 0
  const ymPrefix = props.selectedDate.slice(0, 7)
  if (props.monthSegmentsMap.size > 0) {
    for (const [dateStr, info] of props.monthSegmentsMap) {
      if (dateStr.startsWith(ymPrefix)) {
        total += info.count
      }
    }
  } else {
    total = props.segmentsCount
  }
  return total
})

const monthTotalBytes = computed<number>(() => {
  let bytes = 0
  const ymPrefix = props.selectedDate.slice(0, 7)
  if (props.monthSegmentsMap.size > 0) {
    for (const [dateStr, info] of props.monthSegmentsMap) {
      if (dateStr.startsWith(ymPrefix)) {
        bytes += info.bytes
      }
    }
  } else {
    bytes = props.totalBytes
  }
  return bytes
})

const monthTotalStorageFormatted = computed<string>(() => {
  const bytes = monthTotalBytes.value
  if (bytes === 0) return "0 MB"
  const gb = bytes / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(1)} MB`
})

const monthArchiveRate = computed<string>(() => {
  if (monthTotalSegments.value === 0) return "—"
  let cloudSegments = 0
  for (const [_, info] of props.monthSegmentsMap) {
    cloudSegments += info.cloudCount
  }
  if (cloudSegments === 0) return "0% (仅本地)"
  return `${Math.round((cloudSegments / monthTotalSegments.value) * 100)}%`
})

const monthCalendarCells = computed(() => {
  const cells: Array<{
    dateStr: string
    dayNum: number
    isOtherMonth: boolean
    isToday: boolean
    count: number
    durationStr: string
  }> = []

  const [year, month] = props.selectedDate.split("-").map(Number)
  const firstDayOfWeek = new Date(year, month - 1, 1).getDay() // 0 = Sunday
  const daysInCurrentMonth = new Date(year, month, 0).getDate()
  const daysInPrevMonth = new Date(year, month - 1, 0).getDate()
  const todayStr = props.todayDate

  // Previous month trailing days
  for (let i = firstDayOfWeek - 1; i >= 0; i--) {
    const d = daysInPrevMonth - i
    const prevM = month === 1 ? 12 : month - 1
    const prevY = month === 1 ? year - 1 : year
    const dStr = `${prevY}-${String(prevM).padStart(2, "0")}-${String(d).padStart(2, "0")}`
    cells.push({
      dateStr: dStr,
      dayNum: d,
      isOtherMonth: true,
      isToday: dStr === todayStr,
      count: 0,
      durationStr: ""
    })
  }

  // Current month days
  for (let d = 1; d <= daysInCurrentMonth; d++) {
    const dStr = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`
    const isToday = dStr === todayStr

    let count = 0
    let durSec = 0
    if (dStr === props.selectedDate) {
      count = props.segmentsCount
      durSec = props.totalDurationSec
    } else if (props.monthSegmentsMap.has(dStr)) {
      const info = props.monthSegmentsMap.get(dStr)!
      count = info.count
      durSec = info.durationSec
    }

    cells.push({
      dateStr: dStr,
      dayNum: d,
      isOtherMonth: false,
      isToday,
      count,
      durationStr: formatDurationCompact(durSec)
    })
  }

  // Next month leading days to complete grid
  const totalCells = cells.length
  const remainder = totalCells % 7
  const needed = remainder === 0 ? 0 : 7 - remainder
  const targetTotal = Math.max(35, totalCells + needed)
  const finalNeeded = targetTotal - totalCells

  for (let d = 1; d <= finalNeeded; d++) {
    const nextM = month === 12 ? 1 : month + 1
    const nextY = month === 12 ? year + 1 : year
    const dStr = `${nextY}-${String(nextM).padStart(2, "0")}-${String(d).padStart(2, "0")}`
    cells.push({
      dateStr: dStr,
      dayNum: d,
      isOtherMonth: true,
      isToday: dStr === todayStr,
      count: 0,
      durationStr: ""
    })
  }

  return cells
})
</script>

<template>
    <section class="files-month-calendar">
      <div class="calendar-drawer-header">
        <div class="calendar-month-controls">
          <button type="button" class="month-nav-btn" @click="emit('shift-month', -1)">‹ {{ prevMonthName }}</button>
          <span class="month-title">{{ currentYearMonthTitle }} · 录像日历分布概览</span>
          <button type="button" class="month-nav-btn" @click="emit('shift-month', 1)">{{ nextMonthName }} ›</button>
        </div>
        <div class="calendar-drawer-stats">
          <span>月度录像天数: <b class="text-white">{{ activeDaysInMonth }} 天</b></span>
          <span>切片总量: <b class="text-white">{{ monthTotalSegments }} 段</b></span>
          <span>总存储数据量: <b class="text-white">{{ monthTotalStorageFormatted }}</b></span>
          <span>云端归档率: <b class="text-emerald-400">{{ monthArchiveRate }}</b></span>
        </div>
      </div>

      <!-- Calendar Grid: 7 columns (周日 ~ 周六) -->
      <div class="calendar-grid-7">
        <div class="cal-col-header">周日</div>
        <div class="cal-col-header">周一</div>
        <div class="cal-col-header">周二</div>
        <div class="cal-col-header">周三</div>
        <div class="cal-col-header">周四</div>
        <div class="cal-col-header">周五</div>
        <div class="cal-col-header">周六</div>

        <button
          v-for="d in monthCalendarCells"
          :key="d.dateStr"
          type="button"
          class="cal-day-cell"
          :class="{
            'cal-day-cell--other': d.isOtherMonth,
            'cal-day-cell--active': d.dateStr === selectedDate,
            'cal-day-cell--today': d.isToday,
            'cal-day-cell--has-data': d.count > 0
          }"
          @click="emit('select-date', d.dateStr)"
        >
          <span class="cal-day-num">{{ d.dayNum }}{{ d.isToday ? ' (今天)' : '' }}</span>
          <div v-if="d.count > 0" class="cal-day-count">
            {{ d.count }}段{{ d.durationStr ? ` · ${d.durationStr}` : '' }}
          </div>
          <div v-else-if="!d.isOtherMonth" class="cal-day-empty">无录像</div>
        </button>
      </div>
    </section>
</template>

<style scoped>
/* Month Calendar Drawer */
.files-month-calendar {
  background-color: var(--uf-bg-card);
  border-bottom: 1px solid var(--uf-border);
  padding: 14px 20px;
  animation: slide-down 0.2s ease-out;
  flex-shrink: 0;
}

@keyframes slide-down {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.calendar-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.calendar-month-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.month-nav-btn {
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
}

.month-nav-btn:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.month-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--uf-text-primary);
}

.calendar-drawer-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 11px;
  color: var(--uf-text-muted);
}

.calendar-grid-7 {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6px;
  text-align: center;
}

.cal-col-header {
  font-size: 10px;
  font-weight: 700;
  color: var(--uf-text-muted);
  padding: 4px 0;
}

.cal-day-cell {
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  border-radius: 10px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: all 0.15s;
  min-height: 48px;
  justify-content: center;
}

.cal-day-cell:hover {
  background: var(--uf-bg-hover);
  border-color: var(--uf-accent);
}

.cal-day-cell--other {
  opacity: 0.25;
  cursor: default;
}

.cal-day-cell--active {
  background: var(--uf-accent) !important;
  color: var(--text-on-accent);
  box-shadow: 0 0 12px var(--uf-accent-glow);
}

.cal-day-cell--today {
  outline: 2px solid var(--uf-accent);
}

.cal-day-num {
  font-size: 12px;
  font-weight: 700;
}

.cal-day-count {
  font-size: 10px;
  color: var(--uf-accent);
  margin-top: 2px;
  font-family: var(--font-mono);
}

.cal-day-cell--active .cal-day-count {
  color: var(--text-on-accent);
}

.cal-day-empty {
  font-size: 9px;
  color: var(--uf-text-muted);
  margin-top: 2px;
}
</style>
