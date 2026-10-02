import { useState, type FormEvent } from "react"
import { useNavigate } from "@tanstack/react-router"
import { AlertCircle, UserPlus } from "lucide-react"
import { Button } from "../components/ui/primitives"
import {
  AuthLayout,
  Field,
  PasswordInput,
  TextInput,
} from "../components/ui/form"
import { useAuthStore } from "../stores/auth"

/** Mirrors InitialAdministratorCreate.password: min_length=12, max_length=256. */
const MIN_PASSWORD = 12
const USERNAME_RE = /^[A-Za-z0-9_.-]+$/

export function SetupView() {
  const navigate = useNavigate()
  const create = useAuthStore((s) => s.createInitialAdministrator)
  const busy = useAuthStore((s) => s.busy)
  const globalError = useAuthStore((s) => s.error)

  const [username, setUsername] = useState("admin")
  const [displayName, setDisplayName] = useState("系统管理员")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [touched, setTouched] = useState(false)

  const errors = {
    username: !username
      ? "请输入用户名"
      : !USERNAME_RE.test(username)
        ? "只能包含字母、数字、下划线、点和连字符"
        : null,
    displayName: !displayName.trim() ? "请输入显示名" : null,
    email:
      email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)
        ? "邮箱格式不正确"
        : null,
    password:
      password.length < MIN_PASSWORD
        ? `密码至少 ${MIN_PASSWORD} 位`
        : password.length > 256
          ? "密码过长"
          : null,
    confirm: confirm !== password ? "两次输入不一致" : null,
  }
  const hasError = Object.values(errors).some(Boolean)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setTouched(true)
    if (hasError) return
    const ok = await create({
      username,
      display_name: displayName.trim(),
      email: email.trim() || null,
      password,
    })
    if (ok) await navigate({ to: "/" })
  }

  return (
    <AuthLayout
      title="初始化 zero-nvr"
      description="创建第一个管理员账号，创建后自动登录"
    >
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        {globalError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/8 px-3 py-2.5"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
            <p className="text-xs leading-relaxed">{globalError}</p>
          </div>
        )}

        <Field
          label="用户名"
          htmlFor="s-username"
          error={touched ? errors.username : null}
        >
          <TextInput
            id="s-username"
            value={username}
            autoComplete="username"
            onChange={(e) => setUsername(e.target.value)}
          />
        </Field>

        <Field
          label="显示名"
          htmlFor="s-display"
          error={touched ? errors.displayName : null}
        >
          <TextInput
            id="s-display"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </Field>

        <Field
          label="邮箱"
          htmlFor="s-email"
          hint="可选。用于密码重置与高危操作通知。"
          error={touched ? errors.email : null}
        >
          <TextInput
            id="s-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>

        <Field
          label="密码"
          htmlFor="s-password"
          hint={`至少 ${MIN_PASSWORD} 位`}
          error={touched ? errors.password : null}
        >
          <PasswordInput
            id="s-password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>

        <Field
          label="确认密码"
          htmlFor="s-confirm"
          error={touched ? errors.confirm : null}
        >
          <PasswordInput
            id="s-confirm"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </Field>

        <Button
          type="submit"
          className="w-full"
          disabled={busy || (touched && hasError)}
        >
          <UserPlus />
          {busy ? "创建中…" : "创建管理员并登录"}
        </Button>
      </form>
    </AuthLayout>
  )
}
