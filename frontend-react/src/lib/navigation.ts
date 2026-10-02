import {
  Activity,
  Bell,
  Camera,
  Clock,
  FileVideo,
  Gauge,
  HardDrive,
  type LucideIcon,
  MonitorPlay,
  Settings,
  ShieldCheck,
  Users,
  Video,
} from "lucide-react"

export type NavItem = {
  key: string
  label: string
  icon: LucideIcon
  /** Prototype note: not all items are in the same maturity band. */
  badge?: "optional" | "not-configured"
  description: string
}

export type NavGroup = {
  label: string
  items: NavItem[]
}

/**
 * Navigation is grouped by product meaning, not by shadcn-admin's
 * generic Overview/Management/Others split. Monitoring is what the
 * operator does hourly; Management changes what gets recorded;
 * Storage and System are occasional.
 */
export const navigation: NavGroup[] = [
  {
    label: "监控",
    items: [
      {
        key: "live",
        label: "实时监控",
        icon: Video,
        description:
          "多路实时画面墙。WebRTC 优先、HLS 兜底；H.265 强制 HLS。布局可保存为个人视图。",
      },
      {
        key: "playback",
        label: "录像回放",
        icon: MonitorPlay,
        description:
          "按摄像机 + 时间轴检索。连续录制显示为色块，事件标记叠加，缺口显示原因。播放走直读本地文件。",
      },
      {
        key: "timeline",
        label: "事件时间轴",
        icon: Clock,
        description:
          "跨摄像机的全局事件流。用于回答『昨天傍晚到底有没有人』。",
      },
    ],
  },
  {
    label: "管理",
    items: [
      {
        key: "cameras",
        label: "摄像机",
        icon: Camera,
        description:
          "设备接入与码流绑定。一个机位可有多条码流，按用途绑定（录像/主码流/子码流/AI 检测/抓图/音频）。",
      },
      {
        key: "schedules",
        label: "录制计划",
        icon: Gauge,
        description:
          "决定每台机器录不录、录多久。录像全部由计划驱动，无手动录像。状态如实显示观测结果与阻塞原因。",
      },
      {
        key: "events",
        label: "事件",
        icon: Activity,
        description:
          "ONVIF 事件与 AI 检测事件的归一化视图。Frigate 为可选检测源。",
      },
      {
        key: "alerts",
        label: "告警规则",
        icon: Bell,
        description:
          "事件匹配规则：按摄像机、来源、类别、标签、置信度、时段过滤。命中后可保护录像不被自动清理。",
      },
    ],
  },
  {
    label: "存储",
    items: [
      {
        key: "storage",
        label: "存储",
        icon: HardDrive,
        description:
          "本地存储目标、云盘归档（OpenList）、保留策略、容量水位。先归档后删除是安全阀。",
        badge: "optional",
      },
      {
        key: "files",
        label: "文件",
        icon: FileVideo,
        description:
          "录像目录浏览与导出。单个片段导出为 mp4，带公网分享链接。",
      },
    ],
  },
  {
    label: "系统",
    items: [
      {
        key: "system",
        label: "系统设置",
        icon: Settings,
        description:
          "常规、时钟与 NTP、备份、通知渠道、AI 引擎、SecretStore 密钥环。",
      },
      {
        key: "users",
        label: "用户与权限",
        icon: Users,
        description:
          "三级角色：管理员 / 操作员 / 浏览者。浏览者只能看，不能导出或改设置。",
      },
      {
        key: "audit",
        label: "审计日志",
        icon: ShieldCheck,
        description: "敏感操作留痕：谁改了机位、谁删了录像、谁看过凭据。",
        badge: "not-configured",
      },
    ],
  },
]
