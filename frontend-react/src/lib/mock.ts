/**
 * Static fixture data for the clickable prototype.
 *
 * Deliberately realistic: a table of placeholder rectangles tells you nothing
 * about whether the real screen will be readable. These rows carry the column
 * set, value ranges and status mix the real endpoints return, so layout
 * problems (long device names, 4-digit confidence, 88% capacity) show up here
 * instead of after the migration.
 *
 * Times are anchored to a fixed day so the screens never look stale or drift.
 */

export const TODAY = "2026-10-02"

/* ------------------------------------------------------------------ Types */

export type Camera = {
  id: string
  name: string
  group: string
  vendor: string
  model: string
  protocol: "ONVIF" | "RTSP" | "手动"
  health: "online" | "offline" | "degraded" | "unknown"
  recording: boolean
  mainStream: string
  subStream: string
  aiEnabled: boolean
  clockSkewMs: number
  lastSeen: string
  storageUsedPct: number
}

export type CameraEvent = {
  id: string
  time: string
  camera: string
  source: "ONVIF" | "AI 检测"
  category: "person" | "vehicle" | "animal" | "motion" | "intrusion" | "line"
  confidence: number
  thumbnail: string
  state: "new" | "acknowledged" | "resolved"
  hasRecording: boolean
}

export type RecordingSegment = {
  id: string
  camera: string
  start: string
  duration: string
  resolution: string
  codec: "H.265" | "H.264"
  size: string
  location: "本地" | "已归档" | "备份"
  protected: boolean
}

export type StorageTarget = {
  id: string
  name: string
  kind: "本地磁盘" | "云盘归档" | "备份"
  location: string
  totalGb: number
  usedGb: number
  writeMbps: number
  health: "online" | "degraded" | "offline"
  isRecordingTarget: boolean
}

export type RetentionPolicy = {
  id: string
  target: string
  retainDays: number
  archiveAfterHours: number
  archiveEnabled: boolean
  lastRun: string
}

export type BackupPolicy = {
  id: string
  name: string
  destination: string
  schedule: string
  lastRun: string
  lastResult: "success" | "failed" | "running"
  size: string
}

export type User = {
  id: string
  username: string
  displayName: string
  role: "管理员" | "操作员" | "浏览者"
  status: "active" | "disabled"
  lastLogin: string
  mfa: boolean
}

export type ApiToken = {
  id: string
  name: string
  prefix: string
  createdAt: string
  lastUsed: string
}

export type AuditEntry = {
  id: string
  time: string
  actor: string
  action: string
  resource: string
  result: "success" | "failed" | "denied"
  ip: string
}

export type Schedule = {
  id: string
  camera: string
  mode: "连续录制" | "事件触发" | "仅事件"
  window: string
  prebufferSec: number
  retainDays: number
  observed: "recording" | "idle" | "blocked" | "unknown"
  blockReason?: string
}

export type AlertPolicy = {
  id: string
  name: string
  enabled: boolean
  cameras: string
  conditions: string
  actions: string
  hits24h: number
}

/* ---------------------------------------------------------------- Cameras */

export const cameras: Camera[] = [
  { id: "cam-01", name: "前门人行入口", group: "一层", vendor: "海康威视", model: "DS-2CD2T47G2", protocol: "ONVIF", health: "online", recording: true, mainStream: "主码流 4M", subStream: "子码流 1M", aiEnabled: true, clockSkewMs: 42, lastSeen: "3 秒前", storageUsedPct: 71 },
  { id: "cam-02", name: "后院周界", group: "室外", vendor: "大华股份", model: "IPC-HFW3441T", protocol: "ONVIF", health: "online", recording: true, mainStream: "主码流 4M", subStream: "子码流 1M", aiEnabled: true, clockSkewMs: 118, lastSeen: "3 秒前", storageUsedPct: 71 },
  { id: "cam-03", name: "地下车库 B1 入口", group: "地下", vendor: "海康威视", model: "DS-2CD3T46WDV3", protocol: "ONVIF", health: "online", recording: true, mainStream: "主码流 6M", subStream: "子码流 1M", aiEnabled: false, clockSkewMs: 210, lastSeen: "5 秒前", storageUsedPct: 71 },
  { id: "cam-04", name: "电梯厅（东）", group: "一层", vendor: "萤石", model: "C6N", protocol: "RTSP", health: "degraded", recording: true, mainStream: "主码流 2M", subStream: "子码流 512k", aiEnabled: false, clockSkewMs: 1840, lastSeen: "12 秒前", storageUsedPct: 68 },
  { id: "cam-05", name: "收货月台", group: "仓库", vendor: "大华股份", model: "SD5A445", protocol: "ONVIF", health: "offline", recording: false, mainStream: "—", subStream: "—", aiEnabled: true, clockSkewMs: 0, lastSeen: "2 小时 14 分前", storageUsedPct: 0 },
  { id: "cam-06", name: "仓库主通道", group: "仓库", vendor: "海康威视", model: "DS-2CD2T87G3", protocol: "ONVIF", health: "online", recording: true, mainStream: "主码流 8M", subStream: "子码流 1M", aiEnabled: true, clockSkewMs: 63, lastSeen: "3 秒前", storageUsedPct: 71 },
  { id: "cam-07", name: "前厅收银台", group: "一层", vendor: "宇视", model: "IPC3614SR3", protocol: "ONVIF", health: "online", recording: true, mainStream: "主码流 4M", subStream: "子码流 1M", aiEnabled: true, clockSkewMs: 91, lastSeen: "4 秒前", storageUsedPct: 71 },
  { id: "cam-08", name: "西南角周界", group: "室外", vendor: "海康威视", model: "DS-2DE7425IW-AE", protocol: "ONVIF", health: "online", recording: true, mainStream: "主码流 6M", subStream: "子码流 1M", aiEnabled: false, clockSkewMs: 305, lastSeen: "3 秒前", storageUsedPct: 71 },
  { id: "cam-09", name: "员工通道", group: "一层", vendor: "手动录入", model: "unknown", protocol: "手动", health: "unknown", recording: false, mainStream: "未绑定", subStream: "未绑定", aiEnabled: false, clockSkewMs: 0, lastSeen: "从未连接", storageUsedPct: 0 },
  { id: "cam-10", name: "停车场出口", group: "室外", vendor: "大华股份", model: "DHI-ITC237", protocol: "ONVIF", health: "online", recording: true, mainStream: "主码流 4M", subStream: "子码流 1M", aiEnabled: true, clockSkewMs: 77, lastSeen: "3 秒前", storageUsedPct: 71 },
]

/* ----------------------------------------------------------------- Events */

export const events: CameraEvent[] = [
  { id: "ev-01", time: "14:52:08", camera: "前门人行入口", source: "AI 检测", category: "person", confidence: 0.94, thumbnail: "thumb-a", state: "new", hasRecording: true },
  { id: "ev-02", time: "14:51:33", camera: "地下车库 B1 入口", source: "ONVIF", category: "vehicle", confidence: 0.88, thumbnail: "thumb-b", state: "new", hasRecording: true },
  { id: "ev-03", time: "14:50:47", camera: "仓库主通道", source: "AI 检测", category: "person", confidence: 0.91, thumbnail: "thumb-c", state: "acknowledged", hasRecording: true },
  { id: "ev-04", time: "14:49:12", camera: "西南角周界", source: "ONVIF", category: "motion", confidence: 0.62, thumbnail: "thumb-d", state: "resolved", hasRecording: false },
  { id: "ev-05", time: "14:47:55", camera: "停车场出口", source: "AI 检测", category: "vehicle", confidence: 0.97, thumbnail: "thumb-e", state: "resolved", hasRecording: true },
  { id: "ev-06", time: "14:45:03", camera: "前厅收银台", source: "AI 检测", category: "person", confidence: 0.83, thumbnail: "thumb-f", state: "resolved", hasRecording: true },
  { id: "ev-07", time: "14:43:29", camera: "后院周界", source: "ONVIF", category: "animal", confidence: 0.71, thumbnail: "thumb-g", state: "resolved", hasRecording: true },
  { id: "ev-08", time: "14:41:17", camera: "前门人行入口", source: "AI 检测", category: "person", confidence: 0.89, thumbnail: "thumb-h", state: "resolved", hasRecording: true },
  { id: "ev-09", time: "14:38:40", camera: "西南角周界", source: "AI 检测", category: "intrusion", confidence: 0.79, thumbnail: "thumb-i", state: "acknowledged", hasRecording: true },
  { id: "ev-10", time: "14:35:02", camera: "地下车库 B1 入口", source: "ONVIF", category: "line", confidence: 0.55, thumbnail: "thumb-j", state: "resolved", hasRecording: true },
]

/* ------------------------------------------------------------- Recordings */

export const segments: RecordingSegment[] = [
  { id: "seg-01", camera: "前门人行入口", start: "14:30:00", duration: "00:15:00", resolution: "2688×1520", codec: "H.265", size: "412 MB", location: "本地", protected: false },
  { id: "seg-02", camera: "前门人行入口", start: "14:45:00", duration: "00:15:00", resolution: "2688×1520", codec: "H.265", size: "398 MB", location: "本地", protected: true },
  { id: "seg-03", camera: "后院周界", start: "14:15:00", duration: "00:30:00", resolution: "1920×1080", codec: "H.265", size: "655 MB", location: "本地", protected: false },
  { id: "seg-04", camera: "仓库主通道", start: "13:45:00", duration: "00:30:00", resolution: "3840×2160", codec: "H.265", size: "1.8 GB", location: "已归档", protected: false },
  { id: "seg-05", camera: "前厅收银台", start: "13:00:00", duration: "01:00:00", resolution: "1920×1080", codec: "H.264", size: "1.2 GB", location: "本地", protected: false },
  { id: "seg-06", camera: "停车场出口", start: "12:30:00", duration: "00:30:00", resolution: "1920×1080", codec: "H.265", size: "590 MB", location: "备份", protected: false },
  { id: "seg-07", camera: "地下车库 B1 入口", start: "12:00:00", duration: "01:00:00", resolution: "1920×1080", codec: "H.265", size: "1.1 GB", location: "已归档", protected: false },
  { id: "seg-08", camera: "西南角周界", start: "11:30:00", duration: "00:30:00", resolution: "1920×1080", codec: "H.265", size: "612 MB", location: "本地", protected: false },
]

/** Timeline blocks for the playback screen: gaps are real, not empty space. */
export const timelineBlocks = [
  { start: 0, end: 22, kind: "recorded" as const },
  { start: 22, end: 25, kind: "gap" as const, reason: "机位离线" },
  { start: 25, end: 58, kind: "recorded" as const },
  { start: 58, end: 62, kind: "gap" as const, reason: "存储写入阻塞" },
  { start: 62, end: 94, kind: "recorded" as const },
  { start: 94, end: 97, kind: "gap" as const, reason: "计划时段外" },
  { start: 97, end: 120, kind: "recorded" as const },
]

export const timelineEvents = [
  { at: 8, label: "person" },
  { at: 19, label: "vehicle" },
  { at: 31, label: "person" },
  { at: 44, label: "person" },
  { at: 57, label: "motion" },
  { at: 66, label: "person" },
  { at: 78, label: "vehicle" },
  { at: 91, label: "person" },
  { at: 108, label: "person" },
  { at: 116, label: "animal" },
]

/* ---------------------------------------------------------------- Storage */

export const storageTargets: StorageTarget[] = [
  { id: "st-01", name: "主录像盘", kind: "本地磁盘", location: "/data/recordings", totalGb: 4096, usedGb: 2908, writeMbps: 84.2, health: "online", isRecordingTarget: true },
  { id: "st-02", name: "云端归档", kind: "云盘归档", location: "OpenList · 阿里云盘", totalGb: 2048, usedGb: 612, writeMbps: 6.4, health: "online", isRecordingTarget: false },
  { id: "st-03", name: "外接备份盘", kind: "备份", location: "/mnt/backup-nas", totalGb: 8192, usedGb: 7940, writeMbps: 0, health: "degraded", isRecordingTarget: false },
]

export const retentionPolicies: RetentionPolicy[] = [
  { id: "rp-01", target: "主录像盘", retainDays: 30, archiveAfterHours: 24, archiveEnabled: true, lastRun: "今天 03:00" },
  { id: "rp-02", target: "云端归档", retainDays: 90, archiveAfterHours: 0, archiveEnabled: false, lastRun: "—" },
]

export const backupPolicies: BackupPolicy[] = [
  { id: "bp-01", name: "每日全量", destination: "/mnt/backup-nas/recordings", schedule: "每天 02:30", lastRun: "今天 02:30", lastResult: "failed", size: "7.4 TB" },
  { id: "bp-02", name: "每周快照", destination: "OpenList · 阿里云盘", schedule: "每周一 03:00", lastRun: "09-28 03:00", lastResult: "success", size: "612 GB" },
]

/* ------------------------------------------------------------------ Users */

export const users: User[] = [
  { id: "u-01", username: "admin", displayName: "系统管理员", role: "管理员", status: "active", lastLogin: "2 分钟前", mfa: true },
  { id: "u-02", username: "zhao.ops", displayName: "赵工（安保值班）", role: "操作员", status: "active", lastLogin: "38 分钟前", mfa: true },
  { id: "u-03", username: "li.security", displayName: "李工（安保主管）", role: "操作员", status: "active", lastLogin: "昨天 21:14", mfa: false },
  { id: "u-04", username: "wang.guest", displayName: "前台访客账号", role: "浏览者", status: "active", lastLogin: "10-01 09:02", mfa: false },
  { id: "u-05", username: "old.contractor", displayName: "施工方临时账号", role: "浏览者", status: "disabled", lastLogin: "09-12 16:40", mfa: false },
]

export const apiTokens: ApiToken[] = [
  { id: "tk-01", name: "grafana 面板", prefix: "znvr_a7f3…", createdAt: "2026-08-14", lastUsed: "6 分钟前" },
  { id: "tk-02", name: "移动端 App", prefix: "znvr_2b91…", createdAt: "2026-09-02", lastUsed: "2 小时前" },
  { id: "tk-03", name: "旧监控系统对接", prefix: "znvr_c04e…", createdAt: "2026-03-20", lastUsed: "2026-07-01" },
]

export const sessions = [
  { id: "se-01", device: "Safari · macOS", location: "192.168.1.24", lastSeen: "正在使用", current: true },
  { id: "se-02", device: "Chrome · Windows", location: "192.168.1.87", lastSeen: "14 分钟前", current: false },
  { id: "se-03", device: "zero-nvr iOS", location: "10.8.0.3", lastSeen: "昨天 22:30", current: false },
]

/* ------------------------------------------------------------------ Audit */

export const auditEntries: AuditEntry[] = [
  { id: "au-01", time: "14:58:02", actor: "admin", action: "auth.login", resource: "session", result: "success", ip: "192.168.1.24" },
  { id: "au-02", time: "14:52:11", actor: "zhao.ops", action: "export.create", resource: "seg-02", result: "success", ip: "192.168.1.87" },
  { id: "au-03", time: "14:40:55", actor: "li.security", action: "alert.acknowledge", resource: "ev-09", result: "success", ip: "192.168.1.31" },
  { id: "au-04", time: "13:18:20", actor: "admin", action: "recording-policy.update", resource: "cam-04", result: "success", ip: "192.168.1.24" },
  { id: "au-05", time: "11:02:47", actor: "wang.guest", action: "recording.delete", resource: "seg-11", result: "denied", ip: "10.8.0.51" },
  { id: "au-06", time: "10:44:03", actor: "admin", action: "secret-store.rotate", resource: "openlist-webdav", result: "success", ip: "192.168.1.24" },
  { id: "au-07", time: "09:31:19", actor: "zhao.ops", action: "camera.disable", resource: "cam-05", result: "success", ip: "192.168.1.87" },
  { id: "au-08", time: "昨天 23:15:40", actor: "system", action: "retention.sweep", resource: "st-01", result: "failed", ip: "—" },
  { id: "au-09", time: "昨天 21:04:12", actor: "li.security", action: "token.create", resource: "tk-03", result: "success", ip: "192.168.1.31" },
  { id: "au-10", time: "昨天 18:22:07", actor: "unknown", action: "auth.login", resource: "session", result: "failed", ip: "203.0.113.44" },
]

/* --------------------------------------------------------------- Schedule */

export const schedules: Schedule[] = [
  { id: "sc-01", camera: "前门人行入口", mode: "连续录制", window: "全天", prebufferSec: 30, retainDays: 30, observed: "recording" },
  { id: "sc-02", camera: "后院周界", mode: "事件触发", window: "全天 · 预录 30s", prebufferSec: 30, retainDays: 30, observed: "recording" },
  { id: "sc-03", camera: "地下车库 B1 入口", mode: "连续录制", window: "00:00–24:00", prebufferSec: 15, retainDays: 14, observed: "recording" },
  { id: "sc-04", camera: "电梯厅（东）", mode: "仅事件", window: "07:00–22:00", prebufferSec: 20, retainDays: 7, observed: "blocked", blockReason: "机位时钟偏差 1.8s，超出 ONVIF 容忍阈值" },
  { id: "sc-05", camera: "收货月台", mode: "连续录制", window: "08:00–18:00", prebufferSec: 30, retainDays: 30, observed: "blocked", blockReason: "机位离线（最后心跳 2 小时 14 分前）" },
  { id: "sc-06", camera: "仓库主通道", mode: "事件触发", window: "全天 · 预录 45s", prebufferSec: 45, retainDays: 30, observed: "recording" },
  { id: "sc-07", camera: "前厅收银台", mode: "连续录制", window: "06:00–23:00", prebufferSec: 15, retainDays: 30, observed: "recording" },
  { id: "sc-08", camera: "西南角周界", mode: "连续录制", window: "全天", prebufferSec: 30, retainDays: 30, observed: "recording" },
  { id: "sc-09", camera: "员工通道", mode: "仅事件", window: "08:00–20:00", prebufferSec: 0, retainDays: 7, observed: "unknown", blockReason: "未绑定任何码流" },
  { id: "sc-10", camera: "停车场出口", mode: "事件触发", window: "全天 · 预录 30s", prebufferSec: 30, retainDays: 30, observed: "recording" },
]

/* ------------------------------------------------------------- AlertRules */

export const alertPolicies: AlertPolicy[] = [
  { id: "ap-01", name: "夜间周界入侵", enabled: true, cameras: "后院周界 / 西南角周界", conditions: "person 或 animal · 置信度 ≥ 0.7 · 22:00–06:00", actions: "通知值班 + 保护录像", hits24h: 3 },
  { id: "ap-02", name: "车库车辆停留", enabled: true, cameras: "地下车库 B1 入口 / 停车场出口", conditions: "vehicle · 置信度 ≥ 0.85", actions: "通知值班", hits24h: 41 },
  { id: "ap-03", name: "收银台徘徊", enabled: true, cameras: "前厅收银台", conditions: "person · 停留 > 90s · 10:00–21:00", actions: "通知值班", hits24h: 0 },
  { id: "ap-04", name: "机位离线告警", enabled: false, cameras: "全部", conditions: "health = offline · 持续 > 5 分钟", actions: "通知值班", hits24h: 0 },
  { id: "ap-05", name: "设备目录变更", enabled: true, cameras: "—", conditions: "audit · action = camera.*", actions: "通知安保主管", hits24h: 1 },
]

/* ----------------------------------------------------------------- System */

export const notificationTargets = [
  { id: "nt-01", name: "值班群（钉钉）", kind: "Apprise · DingTalk", enabled: true, lastDelivery: "14:52:11", lastResult: "成功" },
  { id: "nt-02", name: "安保主管邮箱", kind: "SMTP · smtp.internal", enabled: true, lastDelivery: "今天 09:00", lastResult: "成功" },
  { id: "nt-03", name: "企业微信机器人", kind: "Apprise · WeCom", enabled: false, lastDelivery: "2026-09-18 22:14", lastResult: "—" },
]

export const secretStoreKeys = [
  { id: "sk-01", label: "OpenList WebDAV 凭据", ref: "ss://openlist-webdav", rotatedAt: "2026-10-02 10:44", lastRead: "今天 13:02" },
  { id: "sk-02", label: "Frigate API Key", ref: "ss://frigate-api", rotatedAt: "2026-08-19", lastRead: "2026-09-30" },
  { id: "sk-03", label: "SMTP 密码", ref: "ss://smtp-password", rotatedAt: "2026-07-02", lastRead: "2026-10-01" },
]

export const systemHealth = {
  version: "0.14.2 · test",
  uptime: "11 天 4 小时",
  camerasOnline: 8,
  camerasTotal: 10,
  recordingActive: 8,
  zlmStreams: 8,
  frigate: { enabled: true, reachable: true, detectors: ["CPU"] as const, latencyMs: 24 },
  zlmTime: "2026-10-02 14:58:11 CST",
  containerTime: "2026-10-02 06:58:11 UTC",
}

export const clockHealth = [
  { camera: "前门人行入口", skewMs: 42, state: "ok" as const },
  { camera: "后院周界", skewMs: 118, state: "ok" as const },
  { camera: "地下车库 B1 入口", skewMs: 210, state: "ok" as const },
  { camera: "仓库主通道", skewMs: 63, state: "ok" as const },
  { camera: "前厅收银台", skewMs: 91, state: "ok" as const },
  { camera: "西南角周界", skewMs: 305, state: "warn" as const },
  { camera: "停车场出口", skewMs: 77, state: "ok" as const },
  { camera: "电梯厅（东）", skewMs: 1840, state: "bad" as const },
]

/* -------------------------------------------------------------- Overview */

export const overviewStats = {
  camerasOnline: 8,
  camerasTotal: 10,
  recordingActive: 8,
  eventsToday: 37,
  eventsUnacknowledged: 4,
  storageUsedPct: 71,
  alertsToday: 6,
  offlineSince: "收货月台 · 2 小时 14 分",
}

export const hourlyEventCount = [
  { hour: "00", count: 1 }, { hour: "02", count: 0 }, { hour: "04", count: 0 },
  { hour: "06", count: 2 }, { hour: "08", count: 5 }, { hour: "10", count: 7 },
  { hour: "12", count: 6 }, { hour: "14", count: 9 }, { hour: "16", count: 4 },
  { hour: "18", count: 3 }, { hour: "20", count: 2 }, { hour: "22", count: 1 },
]

/* --------------------------------------------------------------- Helpers */

export const categoryLabel: Record<CameraEvent["category"], string> = {
  person: "人员",
  vehicle: "车辆",
  animal: "动物",
  motion: "移动侦测",
  intrusion: "区域入侵",
  line: "越线",
}

export const stateLabel: Record<CameraEvent["state"], string> = {
  new: "未处理",
  acknowledged: "已确认",
  resolved: "已处理",
}

export function formatGb(gb: number) {
  return gb >= 1024 ? `${(gb / 1024).toFixed(2)} TB` : `${gb} GB`
}
