import { Link } from "@tanstack/react-router"
import { Lock, SearchX } from "lucide-react"
import { Button, Card, CardContent } from "../components/ui/primitives"
import { EmptyState, PageHeader } from "../components/ui/display"
import { navigation } from "../lib/navigation"
import { useAuthStore } from "../stores/auth"

export function ForbiddenView() {
  const user = useAuthStore((s) => s.user)
  const role = user?.roles[0] ?? "未知角色"

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="无权访问"
        description="当前账号的角色不包含该模块所需的权限。"
      />
      <Card>
        <CardContent className="pt-4">
          <EmptyState
            icon={<Lock />}
            title={`${role} 无法打开此模块`}
            description="权限按模块整体授予，而不是逐按钮判断。如果这是工作需要，请让管理员调整角色。"
            action={
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => history.back()}>
                  返回上一页
                </Button>
                <Link to="/">
                  <Button size="sm" variant="outline">
                    回到可访问的首页
                  </Button>
                </Link>
              </div>
            }
          />
        </CardContent>
      </Card>
    </div>
  )
}

export function NotFoundView() {
  return (
    <div className="space-y-4 p-5">
      <PageHeader title="页面不存在" />
      <Card>
        <CardContent className="pt-4">
          <EmptyState
            icon={<SearchX />}
            title="没有这个页面"
            description="地址可能拼错了，或者该模块尚未迁移到新版前端。"
            action={
              <Link to="/">
                <Button size="sm" variant="outline">
                  回到首页
                </Button>
              </Link>
            }
          />
        </CardContent>
      </Card>
      <p className="text-center text-xs text-muted-foreground">
        可用模块：
        {navigation
          .flatMap((g) => g.items)
          .map((i) => i.key)
          .join(" · ")}
      </p>
    </div>
  )
}
