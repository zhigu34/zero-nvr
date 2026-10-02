import { useState, type FormEvent } from "react"
import { AlertCircle, X } from "lucide-react"
import { Button, Input } from "../components/ui/primitives"
import { Label } from "../components/ui/form"
import { changePassword, ApiError } from "../api/auth"
import { useAuthStore } from "../stores/auth"

const MIN_PASSWORD = 12

export function ChangePasswordDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const setUser = useAuthStore((s) => s.setUser)
  const [current, setCurrent] = useState("")
  const [next, setNext] = useState("")
  const [confirm, setConfirm] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  if (!open) return null

  function reset() {
    setCurrent("")
    setNext("")
    setConfirm("")
    setError(null)
    setDone(false)
    setBusy(false)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (next.length < MIN_PASSWORD) {
      setError(`新密码至少 ${MIN_PASSWORD} 位`)
      return
    }
    if (next !== confirm) {
      setError("两次输入的新密码不一致")
      return
    }
    setBusy(true)
    try {
      // The endpoint returns the updated user, so the header does not go
      // stale on display-name changes made elsewhere.
      const user = await changePassword({
        current_password: current,
        new_password: next,
      })
      setUser(user)
      setDone(true)
      setTimeout(() => {
        onClose()
        reset()
      }, 1200)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "修改失败")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-lg">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold">修改密码</h2>
          <Button variant="ghost" size="icon-sm" onClick={onClose} title="关闭">
            <X className="size-3.5" />
          </Button>
        </div>

        {done ? (
          <p className="rounded-lg border border-status-online/30 bg-status-online/8 px-3 py-2.5 text-xs text-status-online">
            密码已更新。
          </p>
        ) : (
          <form className="space-y-3" onSubmit={onSubmit} noValidate>
            {error && (
              <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/8 px-3 py-2">
                <AlertCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                <p className="text-xs leading-relaxed">{error}</p>
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="cp-current">当前密码</Label>
              <Input
                id="cp-current"
                type="password"
                autoComplete="current-password"
                className="h-9"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="cp-next">新密码</Label>
              <Input
                id="cp-next"
                type="password"
                autoComplete="new-password"
                className="h-9"
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">至少 {MIN_PASSWORD} 位</p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="cp-confirm">确认新密码</Label>
              <Input
                id="cp-confirm"
                type="password"
                autoComplete="new-password"
                className="h-9"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="ghost" size="sm" onClick={onClose}>
                取消
              </Button>
              <Button type="submit" size="sm" disabled={busy}>
                {busy ? "提交中…" : "确认修改"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
