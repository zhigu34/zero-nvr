<script setup lang="ts">
import type { SegmentItem } from "./types"
import EmptyState from "../ui/EmptyState.vue"
import UiIcon from "../ui/UiIcon.vue"

defineProps<{
  filteredCount: number
  pagedSegments: SegmentItem[]
  selectedSegmentId: string | null
  loading: boolean
  selectedDate: string
  totalPages: number
  pageStartIndex: number
  pageEndIndex: number
  formatDuration: (seconds: number) => string
}>()

const currentPage = defineModel<number>("currentPage", { required: true })
const emit = defineEmits<{
  select: [segment: SegmentItem]
  jump: [segment: SegmentItem]
  download: [segment: SegmentItem]
  "toggle-lock": [segment: SegmentItem]
}>()
</script>

<template>
  <!-- Structured Recording File Table -->
  <div class="table-container">
    <div class="table-scroll-area">
      <table v-if="filteredCount > 0" class="files-table">
        <thead>
          <tr>
            <th>录像时段 (Time Range)</th>
            <th>时长</th>
            <th>文件大小</th>
            <th>编码规格</th>
            <th>存储分层状态</th>
            <th>保护状态</th>
            <th>健康诊断</th>
            <th class="th-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="s in pagedSegments"
            :key="s.id"
            :class="{ 'tr--active': s.id === selectedSegmentId }"
            @click="emit('select', s)"
            @dblclick="emit('jump', s)"
          >
            <td>
              <div class="file-timerange">
                <span class="range-dot" :class="s.protected ? 'range-dot--amber' : 'range-dot--blue'" />
                <span>{{ s.start }} ~ {{ s.end }}</span>
              </div>
              <div class="file-name-sub">{{ s.file }}</div>
            </td>
            <td class="font-mono text-xs">{{ formatDuration(s.durationSec) }}</td>
            <td class="font-mono text-xs font-bold text-white">{{ s.sizeFormatted }}</td>
            <td class="font-mono text-[11px] text-blue-300">{{ s.spec }}</td>
            <td>
              <span class="tier-tag" :class="s.tier === 'local' ? 'tier-tag--local' : (s.tier === 'remote' ? 'tier-tag--cloud' : 'tier-tag--both')">
                {{ s.tierLabel }}
              </span>
            </td>
            <td>
              <span v-if="s.protected" class="lock-badge">
                <UiIcon name="shield" :size="12" class="text-amber-400" />
                <span>已加锁</span>
              </span>
              <span v-else class="text-gray-500 text-[11px]">可轮转</span>
            </td>
            <td>
              <span :class="s.health === 'abnormal' ? 'text-red-400 text-[11px]' : 'text-emerald-400 text-[11px]'">
                <UiIcon :name="s.health === 'abnormal' ? 'close' : 'check'" :size="10" />
                {{ s.health === 'abnormal' ? '异常' : '正常' }}
              </span>
            </td>
            <td class="td-actions" @click.stop>
              <button type="button" class="row-btn" title="回放此片段" @click="emit('jump', s)">
                <UiIcon name="playback" :size="14" class="text-blue-400" />
              </button>
              <button type="button" class="row-btn" title="下载 Raw MP4" @click="emit('download', s)">
                <UiIcon name="download" :size="14" class="text-gray-300" />
              </button>
              <button
                type="button"
                class="row-btn"
                :class="{ 'text-amber-400': s.protected }"
                :title="s.protected ? '解除锁定' : '加锁保护'"
                @click="emit('toggle-lock', s)"
              >
                <UiIcon name="shield" :size="14" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Empty State -->
      <EmptyState v-else-if="!loading" surface-class="empty-state">
        <UiIcon name="folder" :size="44" class="text-white/20" />
        <strong class="text-sm text-gray-300">所选条件暂无录像片段</strong>
        <span class="text-xs text-gray-500">
          当前摄像机在 {{ selectedDate }} 没有检索到匹配条件的录像切片，请尝试重置筛选或切换日期
        </span>
      </EmptyState>
    </div>

    <!-- Table Footer Pagination -->
    <div class="table-footer">
      <span class="footer-info">
        共 {{ filteredCount }} 个录像片段 · 显示第 {{ pageStartIndex }} - {{ pageEndIndex }} 条 (双击任意行直接进入时光回放)
      </span>
      <div class="pagination-controls">
        <button
          type="button"
          class="page-nav-btn"
          :disabled="currentPage <= 1"
          @click="currentPage--"
        >
          ‹ 上一页
        </button>
        <span class="page-indicator font-mono font-bold text-white">{{ currentPage }} / {{ totalPages }}</span>
        <button
          type="button"
          class="page-nav-btn"
          :disabled="currentPage >= totalPages"
          @click="currentPage++"
        >
          下一页 ›
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Structured Table Container */
.table-container {
  flex: 1;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  border-radius: 14px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: var(--uf-shadow-sm);
}

.table-scroll-area {
  flex: 1;
  overflow-y: auto;
}

.files-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  text-align: left;
}

.files-table th {
  position: sticky;
  top: 0;
  background: var(--uf-bg-card-sub);
  color: var(--uf-text-muted);
  padding: 8px 12px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  font-family: var(--font-mono);
  border-bottom: 1px solid var(--uf-border);
  z-index: 10;
}

.files-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--uf-border-subtle);
  color: var(--uf-text-primary);
  cursor: pointer;
  user-select: none;
}

.files-table tr:hover td {
  background-color: var(--uf-bg-hover);
}

.tr--active td {
  background-color: var(--uf-accent-soft) !important;
}

.file-timerange {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--uf-text-primary);
}

.range-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.range-dot--blue { background-color: var(--uf-accent); }
.range-dot--amber { background-color: #f59e0b; }

.file-name-sub {
  font-size: 10px;
  color: var(--uf-text-muted);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.tier-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
}

.tier-tag--local {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.tier-tag--cloud {
  background: rgba(37, 99, 235, 0.15);
  color: var(--uf-accent);
  border: 1px solid rgba(37, 99, 235, 0.3);
}

.tier-tag--both {
  background: rgba(139, 92, 246, 0.15);
  color: #8b5cf6;
  border: 1px solid rgba(139, 92, 246, 0.3);
}

.lock-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.td-actions {
  text-align: right;
  white-space: nowrap;
}

.row-btn {
  background: transparent;
  border: none;
  padding: 4px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--uf-text-muted);
  transition: all 0.1s;
}

.row-btn:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

/* Table Footer Pagination */
.table-footer {
  height: 38px;
  background: var(--uf-bg-card-sub);
  border-top: 1px solid var(--uf-border);
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--uf-text-muted);
  flex-shrink: 0;
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-nav-btn {
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.12s;
}

.page-nav-btn:hover:not(:disabled) {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.page-nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 260px;
  gap: 8px;
  text-align: center;
  padding: 24px;
  color: var(--uf-text-muted);
}
</style>
