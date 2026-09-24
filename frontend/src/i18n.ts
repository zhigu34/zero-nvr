import { computed, readonly } from "vue"
import {
  createI18n,
  useI18n
} from "vue-i18n"

export type AppLocale = "en-US" | "zh-CN"

const STORAGE_KEY = "zero-nvr.locale"

const messages = {
  "en-US": {
    brand: {
      videoSecurity: "video security",
      selfHostedNvr: "self-hosted NVR",
      firstRunSetup: "first-run setup"
    },
    nav: {
      dashboard: "Dashboard",
      live: "Live",
      playback: "Playback",
      events: "Events",
      alerts: "Alerts",
      cameras: "Cameras",
      storage: "Storage",
      system: "System"
    },
    route: {
      signIn: "Sign in",
      initialSetup: "Initial setup",
      dashboard: "Dashboard",
      live: "Live",
      playback: "Playback",
      events: "Events",
      alerts: "Alerts",
      cameras: "Cameras",
      storage: "Storage",
      system: "System"
    },
    shell: {
      primaryNavigation: "Primary navigation",
      coreOnline: "Core online",
      closeNavigation: "Close navigation",
      toggleNavigation: "Toggle navigation",
      openAccount: "Open account",
      account: "Account",
      signOut: "Sign out"
    },
    theme: {
      change: "Change theme",
      title: "Theme",
      system: "System",
      light: "Light",
      dark: "Dark"
    },
    language: {
      change: "Change language",
      title: "Language",
      english: "English",
      simplifiedChinese: "简体中文"
    },
    auth: {
      controlPlane: "Control plane",
      signIn: "Sign in",
      resetPassword: "Reset password",
      enterResetToken: "Enter reset token",
      signInDescription:
        "Use your local zero-nvr account. Camera credentials never leave the control plane.",
      resetRequestDescription:
        "Enter your username or email. The response is intentionally the same whether or not the account exists.",
      resetTokenDescription:
        "Paste the one-time token from your reset email and choose a new password.",
      username: "Username",
      password: "Password",
      signingIn: "Signing in…",
      orContinueWith: "or continue with",
      forgotPassword: "Forgot password",
      haveResetToken: "I have a reset token",
      usernameOrEmail: "Username or email",
      requesting: "Requesting…",
      sendResetToken: "Send reset token",
      backToSignIn: "Back to sign in",
      resetToken: "Reset token",
      newPassword: "New password",
      confirmPassword: "Confirm password",
      resetting: "Resetting…",
      passwordsDoNotMatch: "Passwords do not match.",
      resetRequestNotice:
        "If the account exists and password reset email is configured, a one-time token has been sent.",
      resetCompleteNotice:
        "Password reset complete. Sign in with your new password.",
      oidcFailed:
        "OIDC sign-in failed. Check the provider configuration or account access."
    },
    setup: {
      oneTimeBootstrap: "One-time bootstrap",
      createAdministrator: "Create the administrator",
      description:
        "zero-nvr ships without a default account or password. This form is available only before the first administrator exists.",
      username: "Username",
      displayName: "Display name",
      email: "Email",
      optional: "optional",
      password: "Password",
      confirmPassword: "Confirm password",
      minimumHint:
        "Minimum 12 characters. Emergency recovery remains available through the deploy.sh administrator recovery path.",
      creatingAdministrator: "Creating administrator…",
      createAdministratorAction: "Create administrator"
    },
    account: {
      close: "Close account",
      changePassword: "Change password",
      changePasswordDescription:
        "Changing your password revokes every previous session and keeps this browser signed in with a new session.",
      currentPassword: "Current password",
      newPassword: "New password",
      confirmNewPassword: "Confirm new password",
      changing: "Changing…",
      passwordMismatch: "New passwords do not match.",
      passwordChanged:
        "Password changed. Previous sessions were revoked.",
      activeSessions: "Active sessions",
      activeSessionsDescription:
        "Revoke browsers or devices you no longer use.",
      refresh: "Refresh",
      loadingSessions: "Loading sessions…",
      thisBrowser: "This browser",
      current: "Current",
      lastActive: "Last active {last} · expires {expires}",
      revoking: "Revoking…",
      revoke: "Revoke",
      noOtherSessions: "No other active sessions.",
      sessionRevoked: "Session revoked.",
      unknownIp: "Unknown IP",
      unknownClient: "Unknown client"
    },
    dashboard: {
      overview: "Overview",
      description: "Live operational state across video, events and storage.",
      refreshing: "Refreshing…",
      refresh: "Refresh",
      systemHealth: "System health",
      monitoredComponents: "{count} monitored components",
      cameras: "Cameras",
      disabledCount: "{count} disabled",
      allEnabled: "All enabled",
      events24h: "Events · 24h",
      recentActivityLoaded: "Most recent activity loaded",
      openAlerts: "Open alerts",
      criticalCount: "{count} critical",
      noCriticalAlerts: "No critical alerts",
      liveView: "Live view",
      playback: "Playback",
      events: "Events",
      recentActivity: "Recent activity",
      recentActivityDescription: "Latest provider-neutral events.",
      viewAll: "View all",
      noRecentEvents: "No recent events.",
      alerts: "Alerts",
      alertsDescription: "Items that may need attention.",
      noActiveAlerts: "No active alerts.",
      acknowledge: "Acknowledge",
      cameraInventory: "Camera inventory",
      cameraInventoryDescription:
        "Configured sources and current administrative state.",
      manage: "Manage",
      noCameras: "No cameras configured.",
      noLocation: "No location",
      manual: "manual",
      coreServices: "Core services",
      coreServicesDescription: "Capability health from the control plane.",
      system: "System",
      storageBackup: "Storage & backup",
      storageBackupDescription: "Recording destinations and recoverability.",
      storage: "Storage",
      localRecording: "Local recording",
      remoteArchive: "Remote archive",
      latestBackup: "Latest backup",
      never: "Never",
      noBackupSet: "No backup set",
      systemSource: "System",
      unknownCamera: "Unknown camera",
      status: {
        ok: "OK",
        error: "Error",
        failed: "Failed",
        completed: "Completed",
        open: "Open",
        acknowledged: "Acknowledged",
        resolved: "Resolved",
        warning: "Warning",
        critical: "Critical",
        info: "Info",
        healthy: "Healthy",
        degraded: "Degraded",
        unknown: "Unknown"
      }
    },
    live: {
      cameras: "Cameras",
      selectionSummary: "{selected} selected · {enabled} enabled",
      refreshCameras: "Refresh cameras",
      searchCameras: "Search cameras",
      cameraFilter: "Camera filter",
      all: "All",
      selected: "Selected",
      fillSlots: "Fill {slots}",
      clear: "Clear",
      cameraFallback: "Camera",
      gridSlot: "Grid slot {slot}",
      noSelectedCameras: "No cameras selected.",
      noCamerasFound: "No cameras found.",
      hideCameras: "Hide cameras",
      showCameras: "Show cameras",
      cameraFocus: "Camera focus",
      liveView: "Live view",
      liveCount: "{count} live",
      viewCount: "{count}-view",
      hiddenCount: "{count} hidden",
      networkSaving: "Network saving · preview quality",
      layoutName: "Layout name",
      saveNewLayout: "Save new layout",
      cancel: "Cancel",
      savedLayouts: "Saved live layouts",
      currentView: "Current view",
      saveChanges: "Save changes to this layout",
      saveAsNew: "Save current view as a new layout",
      defaultLayout: "Default layout",
      setDefaultLayout: "Set as default layout",
      deleteSavedLayout: "Delete saved layout",
      backToGrid: "Back to grid",
      gridLayout: "Grid layout",
      cameraLayout: "{count} camera layout",
      exitFullscreen: "Exit fullscreen",
      fullscreenLiveView: "Fullscreen live view",
      openCameraPicker: "Open camera picker",
      addCamera: "Add camera",
      noCameraSelected: "No camera selected",
      chooseCamera: "Choose an enabled camera to start monitoring.",
      selectCameras: "Select cameras",
      layoutSaved: "Layout saved",
      layoutUpdated: "Layout updated",
      defaultLayoutUpdated: "Default layout updated",
      deleteLayoutConfirm: "Delete the saved layout “{name}”?",
      layoutDeleted: "Layout deleted",
      tile: {
        reconnecting: "Reconnecting…",
        streamUnavailable: "Stream unavailable",
        paused: "Live view paused",
        connecting: "Connecting…",
        resumeWhenVisible:
          "Playback resumes automatically when this view is visible.",
        startingSecureSession: "Starting secure live session",
        retryNow: "Retry now",
        noLocation: "No location",
        compatibilityTranscode: "Compatibility transcode · {acceleration}",
        panUp: "Pan up",
        panLeft: "Pan left",
        panRight: "Pan right",
        panDown: "Pan down",
        zoom: "Zoom",
        ptzControls: "PTZ controls",
        stopManualRecording: "Stop manual recording",
        startManualRecording: "Start manual recording",
        downloadSnapshot: "Download snapshot",
        snapshot: "Snapshot",
        unmuteCamera: "Unmute camera",
        muteCamera: "Mute camera",
        unmute: "Unmute",
        mute: "Mute",
        focusCamera: "Focus camera",
        fullscreenCamera: "Fullscreen camera",
        fullscreen: "Fullscreen",
        relay: "TURN relay",
        direct: "Direct",
        sessionSeconds: "{seconds}s session",
        firstFrame: "{milliseconds} ms first frame",
        reconnectCount: "{count} reconnects",
        packetLoss: "{value}% loss",
        jitter: "{milliseconds} ms jitter",
        errors: {
          compatibilityLeaseMissing:
            "Compatibility stream did not return a lease.",
          compatibilityLeaseExpired:
            "Compatibility stream lease expired. Reconnecting automatically.",
          webRtcUnavailable: "WebRTC is not available in this browser.",
          videoUnavailable: "Live video element is unavailable.",
          mediaSessionUnavailable: "Live media session is unavailable.",
          webRtcInterrupted:
            "WebRTC was interrupted. Reconnecting automatically.",
          offerUnavailable: "WebRTC offer SDP is unavailable.",
          sessionSuperseded: "WebRTC session was superseded.",
          hlsUnsupported: "This browser cannot play the live HLS stream.",
          streamInterrupted:
            "Live stream was interrupted. Reconnecting automatically.",
          playbackFailed:
            "Live stream playback failed. Reconnecting automatically."
        }
      }
    }
  },
  "zh-CN": {
    brand: {
      videoSecurity: "视频安防",
      selfHostedNvr: "自托管 NVR",
      firstRunSetup: "首次初始化"
    },
    nav: {
      dashboard: "仪表盘",
      live: "实时监控",
      playback: "历史回放",
      events: "事件",
      alerts: "告警",
      cameras: "摄像机",
      storage: "存储",
      system: "系统"
    },
    route: {
      signIn: "登录",
      initialSetup: "首次初始化",
      dashboard: "仪表盘",
      live: "实时监控",
      playback: "历史回放",
      events: "事件",
      alerts: "告警",
      cameras: "摄像机",
      storage: "存储",
      system: "系统"
    },
    shell: {
      primaryNavigation: "主导航",
      coreOnline: "核心服务在线",
      closeNavigation: "关闭导航",
      toggleNavigation: "切换导航",
      openAccount: "打开账户",
      account: "账户",
      signOut: "退出登录"
    },
    theme: {
      change: "切换主题",
      title: "主题",
      system: "跟随系统",
      light: "浅色",
      dark: "深色"
    },
    language: {
      change: "切换语言",
      title: "语言",
      english: "English",
      simplifiedChinese: "简体中文"
    },
    auth: {
      controlPlane: "控制平面",
      signIn: "登录",
      resetPassword: "重置密码",
      enterResetToken: "输入重置令牌",
      signInDescription:
        "使用本地 zero-nvr 账户登录。摄像机凭据不会离开控制平面。",
      resetRequestDescription:
        "输入用户名或邮箱。无论账户是否存在，系统都会返回相同响应。",
      resetTokenDescription:
        "粘贴重置邮件中的一次性令牌，并设置新密码。",
      username: "用户名",
      password: "密码",
      signingIn: "正在登录…",
      orContinueWith: "或使用以下方式继续",
      forgotPassword: "忘记密码",
      haveResetToken: "我已有重置令牌",
      usernameOrEmail: "用户名或邮箱",
      requesting: "正在请求…",
      sendResetToken: "发送重置令牌",
      backToSignIn: "返回登录",
      resetToken: "重置令牌",
      newPassword: "新密码",
      confirmPassword: "确认密码",
      resetting: "正在重置…",
      passwordsDoNotMatch: "两次输入的密码不一致。",
      resetRequestNotice:
        "如果账户存在且已配置密码重置邮件，系统已发送一次性令牌。",
      resetCompleteNotice:
        "密码重置完成，请使用新密码登录。",
      oidcFailed:
        "OIDC 登录失败，请检查身份提供方配置或账户访问权限。"
    },
    setup: {
      oneTimeBootstrap: "一次性初始化",
      createAdministrator: "创建管理员账户",
      description:
        "zero-nvr 不提供默认账户或默认密码。此表单只会在首个管理员创建前开放。",
      username: "用户名",
      displayName: "显示名称",
      email: "邮箱",
      optional: "可选",
      password: "密码",
      confirmPassword: "确认密码",
      minimumHint:
        "密码至少 12 个字符。紧急情况下仍可通过 deploy.sh 的管理员恢复流程重置账户。",
      creatingAdministrator: "正在创建管理员…",
      createAdministratorAction: "创建管理员"
    },
    account: {
      close: "关闭账户面板",
      changePassword: "修改密码",
      changePasswordDescription:
        "修改密码会撤销此前的所有会话，并让当前浏览器使用新会话保持登录。",
      currentPassword: "当前密码",
      newPassword: "新密码",
      confirmNewPassword: "确认新密码",
      changing: "正在修改…",
      passwordMismatch: "两次输入的新密码不一致。",
      passwordChanged: "密码已修改，之前的会话已全部撤销。",
      activeSessions: "活动会话",
      activeSessionsDescription: "撤销不再使用的浏览器或设备会话。",
      refresh: "刷新",
      loadingSessions: "正在加载会话…",
      thisBrowser: "当前浏览器",
      current: "当前",
      lastActive: "最后活动 {last} · 到期 {expires}",
      revoking: "正在撤销…",
      revoke: "撤销",
      noOtherSessions: "没有其他活动会话。",
      sessionRevoked: "会话已撤销。",
      unknownIp: "未知 IP",
      unknownClient: "未知客户端"
    },
    dashboard: {
      overview: "概览",
      description: "查看视频、事件与存储的实时运行状态。",
      refreshing: "正在刷新…",
      refresh: "刷新",
      systemHealth: "系统健康",
      monitoredComponents: "已监控 {count} 个组件",
      cameras: "摄像机",
      disabledCount: "{count} 个已禁用",
      allEnabled: "全部已启用",
      events24h: "事件 · 24 小时",
      recentActivityLoaded: "已加载最近活动",
      openAlerts: "未处理告警",
      criticalCount: "{count} 个严重告警",
      noCriticalAlerts: "无严重告警",
      liveView: "实时监控",
      playback: "历史回放",
      events: "事件",
      recentActivity: "最近活动",
      recentActivityDescription: "最近的统一事件记录。",
      viewAll: "查看全部",
      noRecentEvents: "暂无最近事件。",
      alerts: "告警",
      alertsDescription: "可能需要处理的项目。",
      noActiveAlerts: "暂无活动告警。",
      acknowledge: "确认",
      cameraInventory: "摄像机清单",
      cameraInventoryDescription: "已配置的视频源及当前管理状态。",
      manage: "管理",
      noCameras: "尚未配置摄像机。",
      noLocation: "未设置位置",
      manual: "手动",
      coreServices: "核心服务",
      coreServicesDescription: "控制平面各能力的健康状态。",
      system: "系统",
      storageBackup: "存储与备份",
      storageBackupDescription: "录像目标与恢复能力。",
      storage: "存储",
      localRecording: "本地录像",
      remoteArchive: "远端归档",
      latestBackup: "最近备份",
      never: "从未",
      noBackupSet: "暂无备份集",
      systemSource: "系统",
      unknownCamera: "未知摄像机",
      status: {
        ok: "正常",
        error: "错误",
        failed: "失败",
        completed: "已完成",
        open: "待处理",
        acknowledged: "已确认",
        resolved: "已解决",
        warning: "警告",
        critical: "严重",
        info: "信息",
        healthy: "健康",
        degraded: "降级",
        unknown: "未知"
      }
    },
    live: {
      cameras: "摄像机",
      selectionSummary: "已选择 {selected} · 已启用 {enabled}",
      refreshCameras: "刷新摄像机",
      searchCameras: "搜索摄像机",
      cameraFilter: "摄像机筛选",
      all: "全部",
      selected: "已选择",
      fillSlots: "填充 {slots} 格",
      clear: "清空",
      cameraFallback: "摄像机",
      gridSlot: "网格位置 {slot}",
      noSelectedCameras: "尚未选择摄像机。",
      noCamerasFound: "未找到摄像机。",
      hideCameras: "隐藏摄像机列表",
      showCameras: "显示摄像机列表",
      cameraFocus: "摄像机聚焦",
      liveView: "实时监控",
      liveCount: "{count} 路实时",
      viewCount: "{count} 分屏",
      hiddenCount: "另有 {count} 路隐藏",
      networkSaving: "网络节省模式 · 预览画质",
      layoutName: "布局名称",
      saveNewLayout: "保存新布局",
      cancel: "取消",
      savedLayouts: "已保存的实时布局",
      currentView: "当前视图",
      saveChanges: "保存对此布局的修改",
      saveAsNew: "将当前视图另存为新布局",
      defaultLayout: "默认布局",
      setDefaultLayout: "设为默认布局",
      deleteSavedLayout: "删除已保存布局",
      backToGrid: "返回网格",
      gridLayout: "网格布局",
      cameraLayout: "{count} 路摄像机布局",
      exitFullscreen: "退出全屏",
      fullscreenLiveView: "实时监控全屏",
      openCameraPicker: "打开摄像机选择器",
      addCamera: "添加摄像机",
      noCameraSelected: "尚未选择摄像机",
      chooseCamera: "选择已启用的摄像机开始监控。",
      selectCameras: "选择摄像机",
      layoutSaved: "布局已保存",
      layoutUpdated: "布局已更新",
      defaultLayoutUpdated: "默认布局已更新",
      deleteLayoutConfirm: "确定删除已保存布局“{name}”吗？",
      layoutDeleted: "布局已删除",
      tile: {
        reconnecting: "正在重连…",
        streamUnavailable: "视频流不可用",
        paused: "实时画面已暂停",
        connecting: "正在连接…",
        resumeWhenVisible: "该视图重新可见时会自动恢复播放。",
        startingSecureSession: "正在建立安全实时会话",
        retryNow: "立即重试",
        noLocation: "未设置位置",
        compatibilityTranscode: "兼容转码 · {acceleration}",
        panUp: "向上转动",
        panLeft: "向左转动",
        panRight: "向右转动",
        panDown: "向下转动",
        zoom: "变焦",
        ptzControls: "PTZ 控制",
        stopManualRecording: "停止手动录像",
        startManualRecording: "开始手动录像",
        downloadSnapshot: "下载快照",
        snapshot: "快照",
        unmuteCamera: "开启摄像机声音",
        muteCamera: "静音摄像机",
        unmute: "开启声音",
        mute: "静音",
        focusCamera: "聚焦摄像机",
        fullscreenCamera: "摄像机全屏",
        fullscreen: "全屏",
        relay: "TURN 中继",
        direct: "直连",
        sessionSeconds: "会话 {seconds} 秒",
        firstFrame: "首帧 {milliseconds} ms",
        reconnectCount: "已重连 {count} 次",
        packetLoss: "丢包 {value}%",
        jitter: "抖动 {milliseconds} ms",
        errors: {
          compatibilityLeaseMissing: "兼容视频流未返回租约。",
          compatibilityLeaseExpired: "兼容视频流租约已过期，正在自动重连。",
          webRtcUnavailable: "当前浏览器不支持 WebRTC。",
          videoUnavailable: "实时视频组件不可用。",
          mediaSessionUnavailable: "实时媒体会话不可用。",
          webRtcInterrupted: "WebRTC 已中断，正在自动重连。",
          offerUnavailable: "WebRTC Offer SDP 不可用。",
          sessionSuperseded: "WebRTC 会话已被新的会话替代。",
          hlsUnsupported: "当前浏览器无法播放实时 HLS 视频流。",
          streamInterrupted: "实时视频流已中断，正在自动重连。",
          playbackFailed: "实时视频播放失败，正在自动重连。"
        }
      }
    }
  }
} as const

function normalizeLocale(value: string | null | undefined): AppLocale {
  return value === "zh-CN" ? "zh-CN" : "en-US"
}

function initialLocale(): AppLocale {
  if (typeof window === "undefined") return "en-US"

  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === "en-US" || stored === "zh-CN") return stored

  return window.navigator.language.toLowerCase().startsWith("zh")
    ? "zh-CN"
    : "en-US"
}

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: initialLocale(),
  fallbackLocale: "en-US",
  messages
})

function applyLocale(locale: AppLocale): void {
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale
  }
}

export function initializeLocale(): void {
  applyLocale(normalizeLocale(i18n.global.locale.value))
}

export function useAppLocale() {
  const { locale } = useI18n({ useScope: "global" })

  const appLocale = computed(() =>
    normalizeLocale(locale.value)
  )

  function setLocale(next: AppLocale): void {
    locale.value = next
    window.localStorage.setItem(STORAGE_KEY, next)
    applyLocale(next)
    window.dispatchEvent(
      new CustomEvent("zero-nvr:locale-changed", {
        detail: { locale: next }
      })
    )
  }

  return {
    locale: readonly(appLocale),
    setLocale
  }
}
