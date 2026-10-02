import { useState, type FormEvent } from "react"
import { useNavigate } from "@tanstack/react-router"
import { AlertCircle, LogIn } from "lucide-react"
import { Button } from "../components/ui/primitives"
import {
  AuthLayout,
  Field,
  PasswordInput,
  TextInput,
} from "../components/ui/form"
import { useAuthStore } from "../stores/auth"

export function LoginView() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const busy = useAuthStore((s) => s.busy)
  const globalError = useAuthStore((s) => s.error)

  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [touched, setTouched] = useState(false)

  const missing =
    (touched && username.trim() === "") || (touched && password === "")

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setTouched(true)
    if (username.trim() === "" || password === "") return
    const ok = await login(username.trim(), password)
    if (ok) await navigate({ to: "/" })
  }

  return (
    <AuthLayout title="登录 zero-nvr" description="使用管理员分配的账号登录">
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
          htmlFor="username"
          error={touched && username.trim() === "" ? "请输入用户名" : null}
        >
          <TextInput
            id="username"
            name="username"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </Field>

        <Field
          label="密码"
          htmlFor="password"
          error={touched && password === "" ? "请输入密码" : null}
        >
          <PasswordInput
            id="password"
            name="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>

        <Button type="submit" className="w-full" disabled={busy || missing}>
          <LogIn />
          {busy ? "登录中…" : "登录"}
        </Button>

        <p className="text-center text-xs text-muted-foreground">
          连续登录失败会触发限流，锁定窗口 5 分钟。
        </p>
      </form>
    </AuthLayout>
  )
}
