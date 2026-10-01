<script setup lang="ts">
import type { SegmentItem } from "./types"
import UiIcon from "../ui/UiIcon.vue"

defineProps<{
  activeSegment: SegmentItem | null
  activeSegmentIndex: number
  segmentsCount: number
  formatDuration: (seconds: number) => string
}>()

const emit = defineEmits<{
  jump: [segment: SegmentItem]
  download: [segment: SegmentItem]
  "toggle-lock": [segment: SegmentItem]
  archive: [segment: SegmentItem]
  clear: []
}>()
</script>

<template>
  <!-- 3. Segment Metadata Inspector (当前片段详情 Inspector) -->
  <div v-if="activeSegment" class="inspector-card-section">
    <div class="section-header pb-2 border-b border-white/5">
      <span class="font-bold text-white text-xs">当前片段详情 (Inspector)</span>
      <span class="text-[10px] font-mono text-gray-400">片段 {{ activeSegmentIndex + 1 }} / {{ segmentsCount }}</span>
    </div>

    <div class="metadata-rows">
      <div class="meta-row">
        <span class="meta-label">文件名称:</span>
        <span class="meta-value inspector-filename font-mono text-[11px] truncate max-w-[240px]" :title="activeSegment.file">
          {{ activeSegment.file }}
        </span>
      </div>
      <div class="meta-row">
        <span class="meta-label">时间范围:</span>
        <span class="meta-value font-mono">{{ activeSegment.start }} ~ {{ activeSegment.end }}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">片段时长:</span>
        <span class="meta-value font-mono">{{ formatDuration(activeSegment.durationSec) }}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">视频流参数:</span>
        <span class="meta-value text-blue-300 font-mono">{{ activeSegment.spec }}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">音频参数:</span>
        <span class="meta-value text-gray-300 font-mono">{{ activeSegment.audioSpec }}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">文件大小:</span>
        <span class="meta-value font-mono font-bold text-white">{{ activeSegment.sizeFormatted }}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">存储节点:</span>
        <span class="meta-value text-emerald-400 font-medium">
          {{ activeSegment.storageNode }}
        </span>
      </div>
      <div class="meta-row">
        <span class="meta-label">归档状态:</span>
        <span class="meta-value font-medium" :class="activeSegment.isArchived ? 'text-blue-400' : 'text-gray-400'">
          {{ activeSegment.archiveLabel }}
        </span>
      </div>
      <div class="meta-row">
        <span class="meta-label">防删除保护:</span>
        <span class="meta-value" :class="activeSegment.protected ? 'text-amber-400 font-bold' : 'text-gray-400'">
          <UiIcon v-if="activeSegment.protected" name="shield" :size="11" />
          {{ activeSegment.protected ? '已加锁保护 (免除轮转)' : '未锁定 (按生命周期轮转)' }}
        </span>
      </div>
    </div>

    <!-- Single File Operational Actions -->
    <div class="inspector-action-buttons">
      <button
        type="button"
        class="action-btn action-btn--primary w-full"
        @click="emit('jump', activeSegment)"
      >
        <UiIcon name="playback" :size="15" />
        <span>跳转时光轴连续回放 (Time-Lapse)</span>
      </button>
      <div class="action-grid-2">
        <button type="button" class="action-btn" @click="emit('download', activeSegment)">
          <UiIcon name="download" :size="14" class="text-blue-400" />
          <span>下载 Raw MP4</span>
        </button>
        <button
          type="button"
          class="action-btn"
          :class="{ 'action-btn--warn': activeSegment.protected }"
          @click="emit('toggle-lock', activeSegment)"
        >
          <UiIcon name="shield" :size="14" class="text-amber-400" />
          <span>{{ activeSegment.protected ? '已保护锁定' : '加锁保护' }}</span>
        </button>
      </div>
      <div class="action-grid-2">
        <button type="button" class="action-btn" @click="emit('archive', activeSegment)">
          <UiIcon name="cloud" :size="14" class="text-cyan-400" />
          <span>提交远端归档</span>
        </button>
        <button type="button" class="action-btn action-btn--danger" @click="emit('clear')">
          <UiIcon name="delete" :size="14" class="text-red-400" />
          <span>清理片段</span>
        </button>
      </div>
    </div>
  </div>

  <!-- Empty state placeholder when no segments exist -->
  <div v-else class="inspector-card-section inspector-card--empty">
    <UiIcon name="play" :size="36" class="text-white/20" />
    <span class="text-gray-400 text-xs">未选定切片</span>
    <span class="text-gray-600 text-[11px]">从右侧列表或上方热力图选择切片</span>
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

.inspector-card--empty {
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

/* Metadata Inspector Rows */
.metadata-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 11px;
}

.meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.meta-label {
  color: var(--uf-text-muted);
}

.meta-value {
  color: var(--uf-text-primary);
  text-align: right;
}

.inspector-filename {
  font-weight: 600;
  color: var(--uf-text-primary);
}

.inspector-action-buttons {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--uf-border-subtle);
}

.action-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.12s;
}

.action-btn:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.action-btn--primary {
  background: var(--uf-accent);
  border-color: var(--uf-accent);
  color: var(--text-on-accent);
  font-weight: 700;
  box-shadow: 0 4px 14px var(--uf-accent-glow);
}

.action-btn--primary:hover {
  background: var(--uf-accent-hover);
}

.action-btn--warn {
  background: rgba(245, 158, 11, 0.15);
  border-color: rgba(245, 158, 11, 0.3);
  color: #f59e0b;
}

.action-btn--danger {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.25);
  color: #ef4444;
}

</style>
