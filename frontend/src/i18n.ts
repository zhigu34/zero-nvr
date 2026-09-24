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
