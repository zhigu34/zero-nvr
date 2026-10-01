import type { TimelineAvailability } from "../../api/playback"

export interface SegmentItem {
  id: string
  file: string
  start: string
  end: string
  startDate: Date
  endDate: Date
  durationSec: number
  sizeFormatted: string
  bytes: number
  type: "continuous" | "event" | "manual"
  tier: TimelineAvailability
  tierLabel: string
  storageNode: string
  isArchived: boolean
  archiveLabel: string
  spec: string
  audioSpec: string
  protected: boolean
  protectionId?: string
  health: "healthy" | "abnormal"
  healthLabel: string
  codec: string
  container: string
}

export interface HeatCell {
  hour: number
  minuteSlot: number // 0..11 (00, 05, 10, ... 55)
  timeLabel: string
  level: number // 0: 无, 1: 常规, 2: 动检/告警, 3: 云端/加锁
  count: number
  bytes: number
}

