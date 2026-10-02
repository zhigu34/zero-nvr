import { useState } from "react"
import { Check, KeyRound, RotateCw, Send, Upload, X } from "lucide-react"
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Select,
  Switch,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui/primitives"
import {
  Callout,
  Field,
  FormActions,
  KeyValue,
  PageHeader,
  StatCard,
  StatusDot,
  Tabs,
} from "../components/ui/display"
import {
  clockHealth,
  notificationTargets,
  secretStoreKeys,
  systemHealth,
} from "../lib/mock"

const TABS = [
  { key: "general", label: "常规" },
  { key: "clock", label: "时钟与 NTP" },
  { key: "notify", label: "通知渠道" },
  { key: "ai", label: "AI 引擎" },
  { key: "secret", label: "密钥与安全" },
  { key: "import", label: "配置导入导出" },
]

export function SystemView() {
  const [tab, setTab] = useState("general")

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="系统设置"
        description="装一次、改一次的配置。启用状态决定相关模块是否可用，未启用时不会出现在导航中。"
        actions={
          <Badge variant="outline">
            {systemHealth.version}
          </Badge>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="运行时长"
          value={systemHealth.uptime}
          tone="online"
        />
        <StatCard
          label="机位在线"
          value={`${systemHealth.camerasOnline}/${systemHealth.camerasTotal}`}
          tone="degraded"
        />
        <StatCard label="ZLM 推流" value={systemHealth.zlmStreams} unit="路" tone="online" />
        <StatCard
          label="Frigate"
          value={systemHealth.frigate.reachable ? "已连接" : "不可达"}
          tone={systemHealth.frigate.reachable ? "online" : "offline"}
          hint={`${systemHealth.frigate.latencyMs}ms · ${systemHealth.frigate.detectors[0]}`}
        />
      </div>

      <Card>
        <Tabs tabs={TABS} active={tab} onChange={setTab} className="px-2" />
        <CardContent className="pt-2">
          {tab === "general" && <General />}
          {tab === "clock" && <Clock />}
          {tab === "notify" && <Notify />}
          {tab === "ai" && <Ai />}
          {tab === "secret" && <Secret />}
          {tab === "import" && <ImportExport />}
        </CardContent>
        {tab !== "import" && <FormActions dirty={false} />}
      </Card>
    </div>
  )
}

function General() {
  const [dirty, setDirty] = useState(false)
  return (
    <div>
      <Field label="站点名称" hint="显示在顶栏与导出的配置文件中">
        <Input
          className="w-56"
          defaultValue="零一境 NVR"
          onChange={() => setDirty(true)}
        />
      </Field>
      <Field
        label="显示时区"
        hint="当前后端 reconciliation 仍以 UTC 写入时间戳，该设置对已录制片段的显示暂不生效"
      >
        <Select
          className="w-44"
          defaultValue="UTC"
          onChange={() => setDirty(true)}
        >
          <option value="UTC">UTC（当前默认值）</option>
          <option value="Asia/Shanghai">Asia/Shanghai</option>
          <option value="Asia/Tokyo">Asia/Tokyo</option>
        </Select>
      </Field>
      <Field label="界面主题">
        <Select className="w-44" defaultValue="system">
          <option value="system">跟随系统</option>
          <option value="light">浅色</option>
          <option value="dark">深色</option>
        </Select>
      </Field>
      <Field label="默认语言">
        <Select className="w-44" defaultValue="zh">
          <option value="zh">简体中文</option>
          <option value="en">English</option>
        </Select>
      </Field>
      <Field
        label="分片时长"
        hint="影响时间轴最小定位精度与单文件体积；已有录像不会重新切分"
      >
        <Select
          className="w-44"
          defaultValue="900"
          onChange={() => setDirty(true)}
        >
          <option value="300">5 分钟</option>
          <option value="900">15 分钟</option>
          <option value="1800">30 分钟</option>
        </Select>
      </Field>
      <FormActions dirty={dirty} />
    </div>
  )
}

function Clock() {
  return (
    <div className="space-y-4">
      <Callout tone="degraded" title="容器时区不一致">
        ZLM 容器为 {systemHealth.zlmTime}，zero-nvr 容器为 {systemHealth.containerTime}
        。事件时间戳以 UTC 存储，界面按显示时区换算；两者不一致会影响事件与录像的对齐。
      </Callout>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>NTP</CardTitle>
            <Button variant="outline" size="sm">
              <Check /> 应用到全部机位
            </Button>
          </CardHeader>
          <CardContent>
            <Field label="NTP 服务器">
              <Input className="w-56" defaultValue="ntp.aliyun.com" />
            </Field>
            <Field label="时区">
              <Input className="w-56" defaultValue="Asia/Shanghai" />
            </Field>
            <Field label="同步周期" hint="容器自身的时钟同步间隔">
              <Select className="w-44" defaultValue="3600">
                <option value="900">15 分钟</option>
                <option value="3600">1 小时</option>
                <option value="21600">6 小时</option>
              </Select>
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>机位时钟健康</CardTitle>
            <span className="text-xs text-muted-foreground">阈值 1000 ms</span>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <THead>
                <TR>
                  <TH>机位</TH>
                  <TH>偏差</TH>
                  <TH>状态</TH>
                </TR>
              </THead>
              <TBody>
                {clockHealth.map((c) => (
                  <TR key={c.camera}>
                    <TD className="font-medium">{c.camera}</TD>
                    <TD className="tabular-nums">{c.skewMs} ms</TD>
                    <TD>
                      <span className="flex items-center gap-1.5">
                        <StatusDot
                          tone={
                            c.state === "ok"
                              ? "online"
                              : c.state === "warn"
                                ? "degraded"
                                : "offline"
                          }
                        />
                        <span className="text-xs">
                          {c.state === "ok"
                            ? "正常"
                            : c.state === "warn"
                              ? "偏大"
                              : "超阈值"}
                        </span>
                      </span>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function Notify() {
  return (
    <div className="space-y-3">
      <Field label="安全邮件默认收件人" hint="用于密码重置与高危操作通知">
        <Input className="w-64" defaultValue="security@example.com" />
      </Field>
      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <THead>
            <TR>
              <TH>渠道</TH>
              <TH>类型</TH>
              <TH>启用</TH>
              <TH>最近投递</TH>
              <TH>结果</TH>
              <TH className="text-right">操作</TH>
            </TR>
          </THead>
          <TBody>
            {notificationTargets.map((n) => (
              <TR key={n.id}>
                <TD className="font-medium">{n.name}</TD>
                <TD className="text-muted-foreground">{n.kind}</TD>
                <TD>
                  <Switch aria-checked={n.enabled} />
                </TD>
                <TD className="text-muted-foreground">{n.lastDelivery}</TD>
                <TD>
                  <Badge
                    variant={
                      n.lastResult === "成功" ? "success" : n.lastResult === "—" ? "muted" : "danger"
                    }
                  >
                    {n.lastResult}
                  </Badge>
                </TD>
                <TD>
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon-sm" title="发送测试">
                      <Send className="size-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon-sm" title="删除">
                      <X className="size-3.5" />
                    </Button>
                  </div>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
      <Button variant="outline" size="sm">
        添加通知渠道
      </Button>
    </div>
  )
}

function Ai() {
  return (
    <div>
      <Field label="启用 Frigate" hint="可选依赖。未启用时事件页只显示 ONVIF 来源，不渲染 AI 筛选器">
        <Switch aria-checked />
      </Field>
      <Field label="服务地址">
        <Input className="w-64" defaultValue="http://frigate:5000" />
      </Field>
      <Field label="检测器" hint="OpenVINO 与 EdgeTPU 不可混用，切换后需重启容器">
        <Select className="w-44" defaultValue="cpu">
          <option value="cpu">OpenVINO · CPU</option>
          <option value="gpu">OpenVINO · GPU</option>
          <option value="edgetpu">EdgeTPU</option>
        </Select>
      </Field>
      <Field label="检测类别" hint="未勾选的类别不会产生事件">
        <div className="flex items-center gap-2">
          {["person", "vehicle", "animal", "package"].map((c) => (
            <Badge key={c} variant="secondary">
              {c}
            </Badge>
          ))}
        </div>
      </Field>
      <Field label="事件回填" hint="对历史录像重新跑一遍检测，用于补齐上线前的事件">
        <Button variant="outline" size="sm">
          <Upload /> 开始回填
        </Button>
      </Field>
      <KeyValue label="连通性">
        <span className="flex items-center gap-1.5 text-status-online">
          <StatusDot tone="online" />
          {systemHealth.frigate.latencyMs} ms
        </span>
      </KeyValue>
    </div>
  )
}

function Secret() {
  return (
    <div className="space-y-3">
      <Callout tone="degraded" title="凭据只存引用">
        前端永远不持有明文。SecretStore 中的密钥仅显示引用标识，轮换会写入审计日志。
      </Callout>
      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <THead>
            <TR>
              <TH>用途</TH>
              <TH>引用标识</TH>
              <TH>最近轮换</TH>
              <TH>最近读取</TH>
              <TH className="text-right">操作</TH>
            </TR>
          </THead>
          <TBody>
            {secretStoreKeys.map((k) => (
              <TR key={k.id}>
                <TD className="flex items-center gap-2 font-medium">
                  <KeyRound className="size-3.5 text-muted-foreground" />
                  {k.label}
                </TD>
                <TD className="font-mono text-xs text-muted-foreground">
                  {k.ref}
                </TD>
                <TD className="text-muted-foreground">{k.rotatedAt}</TD>
                <TD className="text-muted-foreground">{k.lastRead}</TD>
                <TD>
                  <div className="flex justify-end">
                    <Button variant="outline" size="sm">
                      <RotateCw /> 轮换
                    </Button>
                  </div>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
    </div>
  )
}

function ImportExport() {
  return (
    <div className="space-y-4">
      <Callout tone="degraded" title="导入会覆盖当前配置">
        先导出备份，再执行校验，确认无冲突后再应用。应用动作会写入审计日志。
      </Callout>
      <div className="flex flex-wrap gap-2">
        <Button size="sm">
          <Upload /> 校验配置文件
        </Button>
        <Button size="sm" variant="destructive">
          应用到当前系统
        </Button>
        <Button size="sm" variant="outline">
          导出当前配置
        </Button>
      </div>
      <div className="rounded-lg border border-border bg-muted/40 p-3">
        <p className="text-xs text-muted-foreground">
          导出内容包含机位、录制计划、告警规则、存储与保留策略、通知渠道；不含用户密码与
          SecretStore 密钥。
        </p>
      </div>
    </div>
  )
}
