import { useState } from "react"
import { Check, Copy, Globe, Link2, ShieldAlert, Trash2 } from "lucide-react"

import type { ExportView } from "../../api/exports"
import { useCreateExportShare, useRevokeExportShare } from "../../lib/exportMutations"
import { useExportShares } from "../../lib/queries"
import {
  validateMaxDownloads,
  validateShareTtl,
} from "../../lib/exportValidation"
import { formatClock } from "../../lib/format"
import { Button, Input, Separator } from "../ui/primitives"
import { Callout, EmptyState, StatusDot } from "../ui/display"
import { useConfirm } from "../ui/Confirm"

/**
 * Share links on a completed export.
 *
 * Two things about the contract drive this whole panel.
 *
 * **The token is shown exactly once.** `POST /exports/{id}/shares` returns
 * `token` in the creation response and `GET /exports/{id}/shares` does not
 * include it — there is no endpoint that can read it back. So the row list
 * shows links that already exist, and the URL only exists in this panel
 * immediately after creation. Presenting it as a "manage links" list that can
 * always reveal the URL would be promising something the backend cannot do.
 *
 * **The link is not authenticated.** `GET /shared/exports/{token}/download`
 * depends on `HTTPBasic(auto_error=False)` and nothing else
 * (`exports/api.py:532-541`): no session, no permission check. The token is
 * the entire credential, and it is a bearer secret in a URL, so it lands in
 * browser history, proxy logs and chat pastes. That is why the warning is
 * stated as a property of the endpoint rather than as advice — whether a
 * deployment is actually reachable from the internet depends on its reverse
 * proxy, which this module cannot see. See G-19.
 */
export function SharePanel({ job }: { job: ExportView }) {
  const shares = useExportShares(job.id)
  const create = useCreateExportShare(job.id)
  const revoke = useRevokeExportShare(job.id)
  const confirm = useConfirm()

  const [password, setPassword] = useState("")
  const [ttl, setTtl] = useState("24")
  const [maxDownloads, setMaxDownloads] = useState("")
  const [created, setCreated] = useState<{ url: string; expiresAt: string } | null>(
    null,
  )
  const [copied, setCopied] = useState(false)

  const ttlHours = Number(ttl)
  const ttlError = ttl === "" ? "请填写有效期" : validateShareTtl(ttlHours)
  const capError = validateMaxDownloads(
    maxDownloads === "" ? null : Number(maxDownloads),
  )

  function submit() {
    if (ttlError || capError) return
    create.mutate(
      {
        expires_in_hours: ttlHours,
        max_downloads: maxDownloads === "" ? null : Number(maxDownloads),
        password: password === "" ? null : password,
      },
      {
        onSuccess: (share) => {
          setCreated({
            url: `${window.location.origin}${share.download_path}`,
            expiresAt: share.expires_at,
          })
          setCopied(false)
          setPassword("")
        },
      },
    )
  }

  return (
    <div className="space-y-3">
      <Callout tone="degraded" title="分享链接不需要登录即可下载">
        <p>
          该链接的凭证就是链接本身：后端的下载端点不校验会话，
          任何拿到链接的人都能下载这段录像。链接会出现在浏览器历史、
          代理日志和转发记录里。
        </p>
        <p className="mt-1">
          部署是否真的能被公网访问取决于反向代理配置，本页面无法判断。
          对外分享前请先确认这一点，并优先设置访问密码与下载次数上限。
        </p>
      </Callout>

      {created && (
        <div className="space-y-2 rounded-lg border border-status-online/30 bg-status-online/8 p-3">
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <Check className="size-3.5 text-status-online" />
            链接已创建，仅此一次可见
          </div>
          <code className="block break-all rounded bg-background px-2 py-1.5 font-mono text-[11px]">
            {created.url}
          </code>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard?.writeText(created.url)
                setCopied(true)
              }}
            >
              {copied ? <Check /> : <Copy />} {copied ? "已复制" : "复制"}
            </Button>
            <span className="text-[11px] text-muted-foreground">
              有效期至 {formatClock(created.expiresAt)}
            </span>
          </div>
        </div>
      )}

      <div className="space-y-2 rounded-lg border border-border p-3">
        <p className="text-xs font-medium">新建分享链接</p>
        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1">
            <span className="text-[11px] text-muted-foreground">
              有效期（小时，1–720）
            </span>
            <Input
              value={ttl}
              inputMode="numeric"
              onChange={(e) => setTtl(e.target.value)}
              aria-label="有效期小时数"
            />
          </label>
          <label className="space-y-1">
            <span className="text-[11px] text-muted-foreground">
              下载次数上限（可空）
            </span>
            <Input
              value={maxDownloads}
              inputMode="numeric"
              onChange={(e) => setMaxDownloads(e.target.value)}
              aria-label="下载次数上限"
            />
          </label>
        </div>
        <label className="block space-y-1">
          <span className="text-[11px] text-muted-foreground">
            访问密码（可空，留空则任何人都能下载）
          </span>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-label="访问密码"
          />
        </label>
        {(ttlError || capError) && (
          <p className="text-[11px] text-status-offline">{ttlError ?? capError}</p>
        )}
        <Button
          size="sm"
          onClick={submit}
          disabled={Boolean(ttlError || capError) || create.isPending}
        >
          <Link2 /> {create.isPending ? "创建中…" : "创建链接"}
        </Button>
      </div>

      <Separator />

      <div className="space-y-2">
        <p className="flex items-center gap-1.5 text-xs font-medium">
          <Globe className="size-3.5 text-muted-foreground" />
          已有分享（{shares.data?.length ?? 0}）
        </p>
        {shares.isPending ? (
          <p className="text-xs text-muted-foreground">读取中…</p>
        ) : !shares.data || shares.data.length === 0 ? (
          <EmptyState icon={<ShieldAlert />} title="尚未创建分享链接" />
        ) : (
          <ul className="space-y-1.5" aria-label="分享链接列表">
            {shares.data.map((share) => {
              const revoked = share.revoked_at
              const expired = Date.parse(share.expires_at) <= Date.now()
              const exhausted =
                share.max_downloads !== null &&
                share.download_count >= share.max_downloads
              const dead = Boolean(revoked) || expired || exhausted
              return (
                <li
                  key={share.id}
                  className="flex items-center gap-2 rounded-lg border border-border px-2.5 py-2"
                >
                  <StatusDot
                    tone={dead ? "unknown" : "online"}
                  />
                  <div className="min-w-0 flex-1 text-[11px] leading-relaxed">
                    <p>
                      {dead
                        ? revoked
                          ? "已撤销"
                          : exhausted
                            ? "下载次数已用尽"
                            : "已过期"
                        : "生效中"}
                      {share.password_protected && " · 有密码"}
                    </p>
                    <p className="text-muted-foreground">
                      {formatClock(share.expires_at)} 过期 · 已下载{" "}
                      {share.download_count}
                      {share.max_downloads !== null
                        ? `/${share.max_downloads}`
                        : ""}{" "}
                      次
                    </p>
                    {share.last_download_at && (
                      <p className="text-muted-foreground">
                        最近下载 {formatClock(share.last_download_at)}
                      </p>
                    )}
                  </div>
                  {!revoked && (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      title="撤销该链接"
                      disabled={revoke.isPending}
                      onClick={async () => {
                        // Revoking is what makes a leaked link safe again, so
                        // it is deliberately easy — but it is still a
                        // destructive act on something already sent out, and
                        // the operator may be clicking the wrong row.
                        const ok = await confirm({
                          title: "撤销分享链接",
                          message:
                            "撤销后该链接立即失效，已经拿到链接的人将无法再下载。",
                          confirmLabel: "撤销",
                          danger: true,
                        })
                        if (ok) revoke.mutate(share.id)
                      }}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
