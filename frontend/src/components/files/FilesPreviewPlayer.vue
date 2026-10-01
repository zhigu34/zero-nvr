<script setup lang="ts">
import { ref, watch } from "vue"

import UiIcon from "../ui/UiIcon.vue"
import type { SegmentItem } from "./types"

const props = defineProps<{
  activeSegment: SegmentItem | null
  videoUrl: string | null
  selectionToken: number
}>()
const emit = defineEmits<{
  previous: []
  next: []
  "preview-status": [message: string]
}>()

const inspectorVideo = ref<HTMLVideoElement | null>(null)
const isPlaying = ref(false)
const autoAdvance = ref(true)

watch(() => props.selectionToken, () => {
  isPlaying.value = false
})

function togglePlayPreview(): void {
  if (!inspectorVideo.value) {
    isPlaying.value = !isPlaying.value
    emit("preview-status", isPlaying.value ? "正在播放录像片段预览" : "已暂停预览")
    return
  }
  if (inspectorVideo.value.paused) {
    inspectorVideo.value.play().catch(() => undefined)
    isPlaying.value = true
  } else {
    inspectorVideo.value.pause()
    isPlaying.value = false
  }
}

function onVideoEnded(): void {
  if (autoAdvance.value) {
    emit("next")
  }
}
</script>

<template>
  <!-- 1. Player Preview Section -->
  <div class="inspector-card-section">
    <div class="section-header">
      <span class="section-title">
        <span class="blue-dot" />
        <span>片段画面预览 (Preview)</span>
      </span>
      <span class="stream-badge">{{ activeSegment?.codec || 'H.264' }} 原画直放</span>
    </div>

    <!-- Video Player Stage -->
    <div class="player-stage group">
      <video
        v-if="videoUrl"
        ref="inspectorVideo"
        :src="videoUrl"
        class="stage-video"
        controls
        @ended="onVideoEnded"
      />
      <div v-else class="stage-placeholder">
        <UiIcon name="play" :size="36" class="text-white/30" />
        <span class="text-xs text-gray-300 font-mono">{{ activeSegment ? activeSegment.file : '未选定切片' }}</span>
        <span class="text-[10px] text-gray-500 font-mono">
          {{ activeSegment ? `${activeSegment.start} ~ ${activeSegment.end} (${activeSegment.durationSec}s)` : '' }}
        </span>
      </div>

      <!-- Video Floating Timecode OSD -->
      <div class="player-timecode-osd">
        {{ activeSegment ? `${activeSegment.start} - ${activeSegment.end}` : '--:--:-- - --:--:--' }}
      </div>

      <!-- Hover Controls Overlay -->
      <div class="player-overlay">
        <button type="button" class="overlay-btn" title="上一段" @click="emit('previous')">
          <UiIcon name="previous" :size="15" />
        </button>
        <button type="button" class="overlay-btn overlay-btn--main" title="播放 / 暂停" @click="togglePlayPreview">
          <UiIcon :name="isPlaying ? 'pause' : 'play'" :size="18" />
        </button>
        <button type="button" class="overlay-btn" title="下一段" @click="emit('next')">
          <UiIcon name="next" :size="15" />
        </button>
      </div>
    </div>

    <!-- Player Transport & Auto-advance Bar -->
    <div class="transport-bar">
      <div class="transport-btns">
        <button type="button" class="transport-btn" @click="emit('previous')">‹ 上一段</button>
        <button type="button" class="transport-btn transport-btn--primary" @click="togglePlayPreview">
          {{ isPlaying ? '暂停' : '播放' }}
        </button>
        <button type="button" class="transport-btn" @click="emit('next')">下一段 ›</button>
      </div>
      <label class="auto-advance-label">
        <input type="checkbox" v-model="autoAdvance" class="uf-checkbox" />
        <span>自动续播</span>
      </label>
    </div>
  </div>
</template>

<style scoped>
.blue-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: var(--uf-accent);
  box-shadow: 0 0 8px var(--uf-accent-glow);
  flex-shrink: 0;
}

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

.stream-badge {
  background: var(--uf-accent-soft);
  color: var(--uf-accent);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

/* Player Stage */
.player-stage {
  width: 100%;
  height: 190px;
  background-color: #000000;
  border-radius: 10px;
  overflow: hidden;
  position: relative;
  border: 1px solid var(--uf-border);
  display: flex;
  align-items: center;
  justify-content: center;
}

.stage-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.stage-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px;
  text-align: center;
}

.player-timecode-osd {
  position: absolute;
  top: 8px;
  left: 8px;
  background: rgba(0, 0, 0, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 2px 6px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: #ffffff;
  z-index: 10;
}

.player-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  opacity: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  transition: opacity 0.15s ease;
  pointer-events: none;
}

.player-stage:hover .player-overlay {
  opacity: 1;
  pointer-events: auto;
}

.overlay-btn {
  background: rgba(255, 255, 255, 0.15);
  border: none;
  border-radius: 50%;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  cursor: pointer;
  transition: background 0.12s;
}

.overlay-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.overlay-btn--main {
  width: 40px;
  height: 40px;
  background: var(--uf-accent);
  box-shadow: 0 4px 12px var(--uf-accent-glow);
}

.overlay-btn--main:hover {
  background: var(--uf-accent-hover);
}

.transport-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--uf-bg-card-sub);
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid var(--uf-border);
}

.transport-btns {
  display: flex;
  align-items: center;
  gap: 6px;
}

.transport-btn {
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.12s;
}

.transport-btn:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.transport-btn--primary {
  background: var(--uf-accent);
  border-color: var(--uf-accent);
  color: var(--text-on-accent);
  font-weight: 600;
}

.transport-btn--primary:hover {
  background: var(--uf-accent-hover);
}

.auto-advance-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--uf-text-muted);
  cursor: pointer;
  user-select: none;
}

.uf-checkbox {
  border-radius: 4px;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border-strong);
  accent-color: var(--uf-accent);
  cursor: pointer;
}

</style>
