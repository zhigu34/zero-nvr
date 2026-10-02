# 前端模块地图（React + shadcn-admin）

配套 [ADR-0014](adr/0014-frontend-react-shadcn-admin-migration.md)，回答两个问题：

1. **有什么模块** —— 12 个一级页面，4 个语义分组
2. **每个模块页面实现什么功能** —— 逐页的区块、操作、数据来源、权限、迁移注意

## 真相源与阅读方式

| 内容 | 真相源 |
|---|---|
| 模块 key / 图标 / 分组 | `frontend-react/src/lib/navigation.ts` |
| 本文档 | 页面职责、边界、待裁决问题 |
| 端点是否存在 | `backend/app/api/v1/router.py` + 各模块 `api.py` |
| 功能实际怎么跑 | [`IMPLEMENTATION-MAP.md`](IMPLEMENTATION-MAP.md) |

本文档中所有端点均为实路径，已按 router 前缀还原（`storage` → `/api/v1/storage/*`，`backups` → `/api/v1/backups/*`，`audit` → `/api/v1/audit`，`system` → `/api/v1/system/*`，其余直接挂在 `/api/v1`）。

### 原型状态

`frontend-react/` 已实现本文档描述的**全部 12 个页面**，共约 7000 行，`npm run dev` 起在 5273 端口。

| 层 | 文件 | 规模 |
|---|---|---|
| 设计令牌 | `src/styles/theme.css` | shadcn-admin 原样移植 |
| 基础组件 | `src/components/ui/primitives.tsx` + `display.tsx` | 约 820 行 |
| 样例数据 | `src/lib/mock.ts` | 约 700 行 |
| 外壳与路由 | `src/components/AppShell.tsx` | hash 路由，PR-2 换 TanStack Router |
| 12 个页面 | `src/routes/*.tsx` | 188–741 行不等 |

原型是**可点击的静态 mock**：筛选、切换、展开、确认等交互都真的响应，但没有接 API。所有页面用 `PrototypeNote` / `Callout` 标明这一点，且刻意把本文档记录的真实缺陷做进界面（事件过滤两套真相源、时区设置不生效、备份失败、存储 97% 满、分享链接公网可达），而不是把界面画成一切正常的样子。

**主题切换必须作用在 `<html>` 上**：`theme.css` 在 `:root` 里声明了 `--sidebar: var(--background)` 这类别名，CSS 自定义属性的别名在声明它的元素上就已解析完成。若把 `.dark` 挂在内层容器，`--sidebar` 会继续继承已解析的亮色值——主区变暗、侧边栏不变。`src/hooks/use-theme.spec.tsx` 是这条约束的回归测试。

---

## 1. 全局约定

### 1.1 两种布局形态

shadcn-admin 的 `Main` 只有一种带 padding 的容器形态，但 NVR 前端有两种截然不同的页面：

| 形态 | 含义 | 适用 |
|---|---|---|
| `immersive` | 铺满视口、无内边距、无页面标题 | 实时监控、录像回放、文件、事件 |
| `standard` | 带 padding + 页头（标题 / 副标题 / 操作区） | 其余全部 |

**决策**：保留 Vue 端 `route.meta.layout` 的这套二分法，在 React 侧由根布局读取路由元数据决定，而不是全局统一。媒体页任何多余的内边距都是浪费像素。

### 1.2 三级角色

ADR-0014 决定 RBAC 收敛为固定三角色（迁移的前置工作，见 §5）：

| 角色 | 能力 |
|---|---|
| 管理员 Administrator | 全部，含用户/角色/密钥/配置导入导出 |
| 操作员 Operator | 查看 + 全部写操作（机位、计划、规则、导出），不能改用户与系统级配置 |
| 浏览者 Viewer | 只读，不能导出、不能改任何配置 |

权限**不按摄像机细分**（`principal_camera_scopes` / `camera-scope` 端点将随收敛移除）。

### 1.3 非导航路由

| 路由 | 形态 | 说明 |
|---|---|---|
| `/login` | 独立页，无 AppShell | cookie session 登录 |
| `/setup` | 独立页，无 AppShell | 首次初始化创建管理员，**由 `GET /api/v1/setup/status` 强制前置** |
| `*` | 重定向到 `/live` | 与现有 Vue 行为一致 |

`setup` 的强制跳转逻辑必须保留：未初始化时任何导航都重定向到 `/setup`。

---

## 2. 模块总览

| # | 分组 | 模块 | key | 路由 | 布局 | 状态 |
|---|---|---|---|---|---|---|
| 1 | 监控 | 实时监控 | `live` | `/live` | immersive | 在线 |
| 2 | 监控 | 录像回放 | `playback` | `/playback` | immersive | 在线 |
| 3 | 监控 | 事件时间轴 | `timeline` | `/timeline` | standard | **新增** |
| 4 | 管理 | 摄像机 | `cameras` | `/cameras` | standard | 在线 |
| 5 | 管理 | 录制计划 | `schedules` | `/recording-schedules` | standard | 在线 |
| 6 | 管理 | 事件 | `events` | `/events` | immersive | 在线 |
| 7 | 管理 | 告警规则 | `alerts` | `/alerts` | standard | **提级**（现为系统设置内 tab） |
| 8 | 存储 | 存储 | `storage` | `/storage` | standard | 在线（云盘归档可选） |
| 9 | 存储 | 文件 | `files` | `/files` | immersive | 在线 |
| 10 | 系统 | 系统设置 | `system` | `/system` | standard | 在线（10 tab → 6 tab） |
| 11 | 系统 | 用户与权限 | `users` | `/users` | standard | **提级**（现为系统设置内 tab） |
| 12 | 系统 | 审计日志 | `audit` | `/audit` | standard | **未接入**（后端有端点，前端无入口） |

### 角色可访问性（PR-2 实测，非推测）

逐模块核对后端 `require_permission` 调用点后的实际门槛，与「三级角色」一节对齐：

| 模块 | 可打开 | 可修改 | 依据 |
|---|---|---|---|
| 实时监控 / 录像回放 / 事件时间轴 | 浏览者 | 操作员 | `camera.view` / `recording.view` / `event.view` |
| 摄像机 / 录制计划 | 浏览者 | 操作员 | 读 `camera.view`，写 `camera.configure` |
| 事件 / 告警规则 | 浏览者 | 操作员 | `event.view` / `alert.manage` |
| 文件 | 浏览者 | 操作员 | 读 `recording.view`，写 `recording.export` |
| 系统设置 | 浏览者 | 管理员 | 读 `system.view`，写 `system.manage` |
| **存储** | **管理员** | 管理员 | 模块内**全部**端点都要 `storage.manage` |
| **用户与权限** | **管理员** | 管理员 | `user.manage` |
| **审计日志** | **管理员** | 管理员 | `audit.view`，Operator 角色不含此项 |

三个加粗项是核对权限调用点时才暴露的结果，与直觉不符：如果只看角色描述会以为操作员能看存储水位。`routes/router.spec.ts` 对这三项有专门断言。

### 分组逻辑

不是照抄 shadcn-admin 的 Overview / Management / Others，而是按**操作频率**划分：

- **监控** —— 每小时都在用。看现在发生什么、刚才发生了什么。
- **管理** —— 决定「什么会被录下来」。改动频率低但影响面最大。
- **存储** —— 容量与数据留存，偶尔看。
- **系统** —— 安装期配置，登录后基本不动。

这条轴线直接回应原问题：Vue 端 10 个系统 tab 平级堆叠，管理员分不清哪些是「每天的」哪些是「装一次的」。

---

## 3. 逐模块定义

### 3.1 实时监控 `/live`

**职责**：同时看多路摄像头。

**页面区块**
- 顶部工具条：布局选择器（个人视图 / 摄像机分组 / 全部）、布局编辑开关、快照全部、投屏
- 瓦片网格：自适应列数，虚拟滚动
- 瓦片叠加层：机位名、录制状态点、当前时间、音频开关、PTZ 控件、码流信息（分辨率/帧率/码率）
- 瓦片状态机：连接中 / 播放中 / 重连中 / 失败（失败必须显示原因与重试按钮，不允许静默黑屏）

**关键操作**
- 新建 / 保存 / 修改 / 删除个人布局
- 切换机位分组
- PTZ 移动与停止
- 单帧抓图
- 从该机位跳转到回放（带入当前时间）
- 单画面全屏、双画面对比

**数据来源**
```
GET|POST          /camera-groups, PATCH|DELETE /camera-groups/{id}
GET|POST          /live-layouts, PATCH|DELETE /live-layouts/{id}
GET               /cameras/{id}/live
GET               /cameras/{id}/live/preview.mjpeg
GET               /cameras/{id}/live/ice
POST              /cameras/{id}/live/whep
DELETE            /cameras/{id}/live/whep/{ticket}
GET               /cameras/{id}/live/diagnostics
POST              /cameras/{id}/live/compatibility
POST|DELETE       /cameras/{id}/live/compatibility/{lease_id}[/keepalive]
POST|DELETE       /cameras/{id}/live/session/{media_session_id}[/keepalive]
POST              /cameras/{id}/ptz/move, /cameras/{id}/ptz/stop
GET               /cameras/{id}/snapshot
```

**传输选择**（迁移时最容易出错的地方，规则不可简化）：
WebRTC/WHEP 优先 → 失败回退 HLS。**H.265 强制走 HLS**（浏览器 WebRTC 解码器普遍不支持 H.265）。子码流优先用于实时预览。逻辑来源是现有 `src/live/playback.ts` 190 行，直接移植。

**权限**：查看需登录；PTZ 需 Operator 以上。

**迁移注意**：现有 `LiveCameraTile.vue` **2591 行**，承担了 video 容器 / 传输 / 叠加 / 布局四种职责。必须拆成 `<TileContainer>` + `useWebRTCTransport` + `useHlsTransport` + 纯布局算法，否则 React 侧会原样复刻同一个 God component。

---

### 3.2 录像回放 `/playback`

**职责**：查过去发生了什么。

**页面区块**
- 左侧机位选择器（带分组、缩略图、健康状态点）
- 时间轴主区：连续录像色块、事件标记叠加、**缺口显示原因**（非简单留白）
- 播放控制：播放/暂停、逐帧、倍速（0.25–8x）、跳到上一/下一事件
- 片段列表：该时段所有片段，含本地/远端位置标识
- 底部：导出当前片段、跳到同一机位其他日期

**关键操作**
- 拖拽时间轴定位、按日期跳转
- 倍速与逐帧
- 全屏 / 画中画
- 从事件标记跳转到对应片段
- 导出选中片段

**数据来源**
```
GET               /cameras/{id}/timeline
POST              /playback/timeline
GET               /cameras/{id}/recordings
GET               /recordings/{segment_id}
GET               /recordings/{segment_id}/locations
GET               /recordings/{segment_id}/media
POST              /recordings/{segment_id}/playback/resolve
POST              /cameras/{id}/playback/resolve
```

**三级解析**（本地优先、远端回退）：本地磁盘 → 归档存储 → 备份副本。`GET /recordings/{id}/locations` 返回全部候选位置，前端按序探测。**回放不走 ZLM VOD**——`GET /recordings/{id}/media` 是 `FileResponse` 直读盘，全仓零引用 ZLM 的 `/record/` VOD 目录。

**权限**：查看需登录；导出需 Operator 以上。

**迁移注意**：现有 `PlaybackView.vue` **2813 行，零测试覆盖**，是本次迁移最大的风险点。必须先把播放时钟抽成纯逻辑模块 `PlaybackClock`（不依赖 DOM），补齐 vitest 用例，再搬进 React。playback 组件群共 6584 行。

---

### 3.3 时间轴 `/timeline`

**职责**：跨摄像机的横切视图——「门口那台和停车场那台，昨天 6 点到 8 点有没有异常，以及那段时间到底录上了没有」。

**为什么单列一页**：`EventsView` 是事件列表，时间轴页是**录像覆盖对照**。前者回答「发生了什么」，后者回答「那段时间有没有录到、为什么没录到」——后者只能从录像轨道上读出来，事件列表里没有这个信息。空缺段按后端给出的原因着色（不在计划内 / 信号丢失 / 服务重启 / 存储故障 / 已清理），这些原因指向完全不同的排查动作。

**页面区块**（PR-5f 实现）
- 范围选择：今天 / 最近 24 小时 / 最近 7 天 / 自定义（自定义按系统显示时区换算）
- 事件粒度选择：**按分桶大小标注**（逐个事件 / 5 分钟 / 1 小时）
- 机位多选侧栏（上限 9 台）
- 每机位一条轨道：录像段（按可用性着色）+ 空缺段（按原因着色）+ 事件标记条
- 点击轨道 → 侧栏显示该时刻的覆盖状态；「在回放中打开」带机位与时刻深链跳转

**数据来源**
```
GET               /cameras/{id}/timeline?from=&to=&detail=    单机位
POST              /playback/timeline                        2–9 机位合并为一次请求
```

> **D-4 已按证据结案**：本节原先记录「后端无聚合端点，密度条只能前端分桶」。核对后发现
> **`PlaybackTimelineService` 已经做了服务端分桶**（`recordings/timeline.py:398-548`），
> 按 1 小时 / 5 分钟把事件聚成带 `count` 与 `category_counts` 的标记。因此原方案
> (c)「后端新增密度聚合端点」**不需要做**，能力已存在，只是没写进本文档。

**权限**：查看需登录（`recording.view`）。

### 3.4 摄像机 `/cameras`

**职责**：设备接入与码流绑定。

**页面区块**
- 机位表格（TanStack Table）：名称、分组、协议、健康状态、在线码流数、时区偏差、启用状态
- 分组管理
- 添加向导：ONVIF 探测 / 手动录入 / 批量 CSV 导入
- 机位详情抽屉：基本信息、码流档案列表、**用途绑定**、健康与时钟、事件源配置

**码流用途绑定**（这是本页的核心，不是简单的「多码流列表」）：一个机位可有多条码流，每条码流按**用途**绑定，不同用途可以绑不同码流：

| 用途 | 期望码流 |
|---|---|
| 录像（长期存储） | 主码流，最高画质 |
| 实时预览 | 子码流，低延迟低带宽 |
| AI 检测 | 子码流或中间码流 |
| 抓图 | 静态快照能力 |
| 音频 | 含音频轨的码流 |

绑定后端端点：`GET|PUT /cameras/{id}/stream-bindings`。改动会让录像源切换，需二次确认。

**关键操作**
- ONVIF 探测 `POST /cameras/onvif/test`
- ONVIF 批量导入 `POST /cameras/onvif/import`
- 局域网设备发现 `POST /cameras/discovery` + `GET /cameras/discovery/{id}`（异步轮询）
- 码流档案刷新 `POST /cameras/{id}/onvif/refresh`
- 码流可用性校验 `POST /cameras/{id}/streams/{profile_id}/verify`
- 启用 / 停用 / 退役 / 恢复
- 单机位健康检查 `POST /cameras/{id}/probe`

**数据来源**
```
GET|POST          /cameras, GET|PATCH /cameras/{id}
POST              /cameras/test
GET               /cameras/{id}/health
GET               /cameras/{id}/clock
GET               /cameras/{id}/streams
POST              /cameras/{id}/enable, /disable, /retire, /restore, /probe
+ 分组 / 发现 / 导入 / 绑定 端点（见上）
```

**「退役」与「停用」是两件事**：停用 = 临时不录不推流，配置保留；退役 = 机位下线，录像保留但不再关联新录制。UI 必须用不同措辞，不能共用一个「删除」。

**权限**：查看需登录；全部写操作需 Operator 以上。

**迁移注意**：**萤石不能走本页的 ONVIF 接入**。萤石无 Linux SDK，局域网能力只覆盖 iOS/Android，事件只走公网 HTTPS WebHook（`INTEGRATIONS.md` 已记录）。它是**云事件源**，不是 ONVIF 设备。把它塞进「摄像机」页会误导用户以为本地直连可用。萤石接入应作为事件源配置（见 §3.6 与 §6 D-5）。

---

### 3.5 录制计划 `/recording-schedules`

**职责**：决定每台机器录不录、录多久。

**核心原则**：**录像全部由计划驱动，没有手动录像**。UI 上不应出现「开始录像」按钮。

**页面区块**
- 计划列表：机位、模式、时段、预录时长、保留天数、当前观测状态、**阻塞原因**
- 每周时段网格：可视化拖拽设定录制窗口
- 模式选择：连续 / 事件触发 / 仅事件
- 录像保护：按事件或手动锁定片段不被清理

**关键操作**
- 保存单机位策略 `PUT /cameras/{id}/recording-policy`
- 批量读取 `GET /recording-policies`
- 创建 / 修改 / 删除录像保护
- 临时手动触发录制（`POST /cameras/{id}/recording-triggers`，会生成一条带自动过期时间的 trigger）

**数据来源**
```
GET               /recording-policies
GET|PUT           /cameras/{id}/recording-policy
GET|POST          /cameras/{id}/recording-protections
PUT|DELETE        /recording-protections/{protection_id}
GET|POST          /cameras/{id}/recording-triggers
POST              /recording-triggers/{trigger_id}/stop
```

**状态必须如实显示观测结果与阻塞原因**，不能只显示「已启用」。机位离线、存储不足、码流未绑定都是真实的阻塞，UI 必须给出可操作的提示。

**关键认知**（避免在迁移时改错）：`arbiter.py:97-104` 的模式判定**不看 `event_active`**。recorder 早已以 prebuffer 模式常驻，事件只让预录片段被**提升**为正式录像。所以「事件模式」不会让 recorder 停止——实现里不要试图在 UI 上解释成「开了才录」。

**权限**：Operator 以上。

---

### 3.6 事件 `/events`

**职责**：归一化事件视图。

**页面区块**
- 事件表格：时间、机位、来源、类别、置信度、标签、缩略图、处理状态
- 详情抽屉：原始载荷、关联录像片段、快照
- 筛选：来源（ONVIF 事件 / AI 检测）、类别、时间范围、机位

**数据来源**
```
GET               /events
GET               /events/{id}
GET               /events/{id}/recordings
GET               /events/{id}/snapshot
```

**AI 检测事件源**（Frigate）为**可选**依赖，未配置时事件页仍需正常工作（只显示 ONVIF 来源）。不要在未启用时渲染 AI 相关筛选器。

**权限**：查看需登录。

---

### 3.7 告警规则 `/alerts`

**职责**：定义什么事件需要通知人、什么录像需要保护。

**提级说明**：现有 Vue 端 `AlertsView.vue`（936 行）**没有被任何路由使用**——`/alerts` 被重定向到 `/events`，规则实际实现在 `SystemView` 的 alerts tab 里。本模块是把死代码复活并提为一级导航。

**页面区块**（PR-5h 实现）
- 规则列表：名称、启用状态、严重度、匹配条件数、冷却
- 匹配条件编辑器：**12 个字段全覆盖**（后端白名单，见下）
- **只读参考区**：所选机位的录制事件过滤，逐字段复制
- 告警收件箱：未处理 / 已确认 / 已解决，可确认与标记解决

**数据来源**
```
GET|POST          /alert-policies, GET|PATCH|DELETE /alert-policies/{id}
GET               /alerts, GET /alerts/{id}
POST              /alerts/{id}/acknowledge
POST              /alerts/{id}/resolve
GET               /recording-policies            (只读参考用)
```

**最严重病灶 —— 两套真相源**：`recording_policies.event_filter_json`（录制策略内的事件过滤）与 `alert_policies.match_json`（告警规则）**字段重叠但完全独立配置、互不同步**。同一个「只关心 person 和 vehicle」的条件，用户要在两个页面各填一次，改一处另一处不动。

`recording_policies` 的事件过滤消费端是 `recordings/triggers.py:91-116` 的 `_event_matches`，由 `upsert_provider` 在 `:166-172` 调用，**且仅对新事件判定**（不追溯已录制片段）。

**迁移必须在动框架之前裁决这个**，见 §6 D-2 与
[`D-2-DECISION-MATERIAL.md`](D-2-DECISION-MATERIAL.md)。带着两套真相源换框架，
迁移后问题无法定位。

**PR-5h 的处置：D-2 未裁决，因此选一个不会错的形态。**
规则编辑器完整实现 12 个 key 的编辑（后端白名单 `alerts/service.py:27-40`），
但**不做任何自动同步**。录制过滤以只读参考呈现，逐字段提供复制，
且**只对 `labels` 与 `min_confidence` 开放**——这两项两侧语义一致；
`zones` 明确拒绝并写明原因（录制侧读 `metadata_json["zones"]`，告警侧读
`Event.zone`，同一事件会出现「录了但没告警」）。拒绝的判定放在
`lib/alertValidation.ts` 的 `importFromRecordingFilter` 里而不是组件里，
因此将来加「一键全部复制」也绕不过去。

**另一处必须处理的缺陷**：`PATCH /alert-policies/{id}` **整体替换** `match`，
服务端无字段级合并。旧 Vue 的 `buildMatch()` 从零重建，导致带 `severities`
的规则在 UI 里保存一次就丢字段且返回 200（**G-33**）。现由 `mergeMatch`
以服务端现有对象为基底合并，未知 key 透传。

**权限**：Operator 以上。

---

### 3.8 存储 `/storage`

**职责**：数据存在哪、存多久、满了怎么办。

**页面区块**
- 存储目标列表：容量水位（已用/总量）、写入速率、目标类型（本地盘 / OpenList WebDAV）、健康状态
- 云盘归档配置：OpenList 地址与凭据（凭据存 SecretStore，前端只存引用）
- 切换录像目标：`POST /targets/{source}/switch-recording`
- 保留策略：保留天数、每日归档时刻
- 备份策略与恢复：`/backups/*`，含 recovery-kit 状态

**关键操作**
- 新增 / 编辑 / 测试 / 删除存储目标 `POST /targets/{id}/test`
- 切换录像落盘目标
- 保留策略 CRUD
- 手动触发备份 `POST /backups/run`、校验备份 `POST /backups/{backup_id}/verify`
- 生成恢复套件 `GET /backups/recovery-kit/status`、`POST /backups/recovery-kit`

**数据来源**
```
GET|POST          /storage/targets, GET|PATCH|DELETE /storage/targets/{id}
POST              /storage/targets/{id}/test
POST              /storage/targets/{source_target_id}/switch-recording
GET|POST          /storage/retention-policies, GET|PATCH|DELETE /storage/retention-policies/{id}
GET|POST          /backups/policies, GET|PATCH /backups/policies/{id}
GET|POST          /backups                 (备份任务)
POST              /backups/run, /backups/{backup_id}/verify
GET|POST          /backups/recovery-kit/status, /backups/recovery-kit
```

**安全阀语义必须在 UI 上体现**：保留策略是**先归档后删除**（`storage/retention.py:596-633`）——归档失败则不删。UI 不能把「删除」呈现成直接 rm，破坏性操作必须说明「归档失败时本片段会保留」。

**凭据处理**：OpenList WebDAV → rclone 的配置由后端 `storage/service.py:430-469` 生成，前端只提交引用不提交明文。

**权限**：查看需登录；全部写操作需 Operator 以上。

**待裁决**（§6 D-3）：备份与恢复归属本页还是系统设置。本文档暂定归本页（数据安全语义内聚），但现有 Vue 端把它放在系统设置 tab 里。

---

### 3.9 文件 `/files`

**职责**：按机位浏览录像，并把一段时间范围导出为单个 mp4 或公开分享链接。

**页面区块**（PR-5e 实现后，已按真实契约修正）
- 机位选择 + 时间范围选择（时区显式，默认取系统显示时区）
- 片段列表：起止、时长、编码/容器、大小、触发原因、**时间基准**、完整性、保护标记
- 导出任务列表：状态、已耗时、下载、分享链接

**原型假设与真实契约的四处偏差**（PR-5e 逐条核对的结果）：

| 原型设计 | 真实契约 | 处理 |
|---|---|---|
| 目录树 机位→日期→小时，根节点「全部录像」跨机位 | 只有 `GET /cameras/{id}/recordings`，**无跨机位端点** | 改为按机位浏览（**G-25**） |
| 勾选 N 个片段 → 导出 N 个 mp4 | `ExportCreate` 是**单机位 + 时间范围**，一个范围一个 mp4 | 改为范围导出 |
| 进度条 62% | `ExportView` **无进度字段** | 改为状态 + 已耗时（**G-24**） |
| 逐行「存储位置」「分辨率」「保护锁」 | 位置在独立端点（N+1）；无分辨率；保护是机位时间窗 | 位置/分辨率不画；保护只读标记，**G-26 / G-27** |

**关键操作**
- 浏览 `GET /cameras/{id}/recordings`（keyset 分页）
- 创建导出 `POST /exports`（带 `Idempotency-Key`）
- 下载 `GET /exports/{id}/download`（仅 `COMPLETED` 且未过期）
- 取消 `DELETE /exports/{id}`
- 创建 / 撤销分享 `POST|DELETE /exports/{id}/shares`

**数据来源**
```
GET               /cameras/{id}/recordings
GET               /cameras/{id}/recording-protections     (只读标记，本地求交)
POST              /exports                                 (Idempotency-Key 必带)
GET               /exports, GET /exports/{id}
DELETE            /exports/{id}
GET               /exports/{id}/download
POST|GET          /exports/{id}/shares
DELETE            /exports/{id}/shares/{share_id}
GET               /shared/exports/{token}/download      (免登录)
```

**分享链接是公网可达的**，是全系统唯一不需要登录即可访问录像的路径（**G-19**）。
后端在创建响应里返回 `token` 与 `download_path`，**之后再无任何接口能读回**，
因此 UI 必须在创建时把完整 URL 显示出来并提示只此一次可见。
创建/撤销必须限 Operator 以上。

**已知契约缺口**：入队失败会留下一条永远不会被执行的记录，且用同一
`Idempotency-Key` 重试会拿回这条记录并返回 201（**G-23**）。前端已按
「作废幂等键 + 显式提示 + 提示取消」处理，但不能从根本上解决。

**权限**：浏览需登录；导出与分享需 Operator 以上。

---

### 3.10 系统设置 `/system`

**职责**：装一次、改一次的配置。

**现有 10 个平级 tab → 重组为 6 个**（这是本次重构的原始问题之一）：

| tab | 内容 | 数据来源 |
|---|---|---|
| **常规** | 站点名、显示时区、界面主题、语言 | `GET|PATCH /system/settings` |
| **时钟与 NTP** | NTP 服务器配置、全局时钟状态、单摄像机时钟健康、应用 NTP | `GET /system/camera-clock-health`、`POST /system/settings/camera-ntp/apply` |
| **通知渠道** | Apprise 目标增删改、发送测试、投递记录、安全邮件默认地址 | `/notification-targets/*`、`GET /notification-deliveries` |
| **AI 引擎** | Frigate 集成配置、连通性测试、事件回填 | `GET|PUT /system/integrations/frigate`、`POST /test`、`POST /backfill` |
| **密钥与安全** | SecretStore 密钥环查看与轮换 | `GET /system/secret-store`、`POST /system/secret-store/rotate` |
| **配置导入导出** | 校验 / 应用 / 导出 | `POST /system/configuration/import/validate`、`/apply`、`GET /system/configuration/export` |

**从本 tab 移出的三项**（重组的核心）：
- 用户权限 → 独立为「用户与权限」一级模块
- 告警规则 → 独立为「告警规则」一级模块
- 备份与恢复 → 归入「存储」（待裁决 D-3）

**保留的诊断类端点**（供本页顶部状态条使用，不单独成 tab）：`GET /system/health`、`GET /system/info`、`GET /system/update-info`、`GET /system/events/stream`。

**实现进度**（PR-5d 建立了平铺的 4 组表单；PR-6 补齐阶段按上表逐个转成 tab）：

| tab | 状态 |
|---|---|
| 系统设置（通用 / 时钟与 NTP / 运行时调优） | ✅ PR-5d |
| 通知渠道 | ✅ PR-6 补齐 1 |
| AI 引擎（Frigate） | ✅ PR-6 补齐 4 |
| 密钥与安全（SecretStore） | ✅ PR-6 补齐 3 |
| 配置导入导出 | ⬜ 未列入 13 项补齐清单，需确认是否保留 |
| ~~API 令牌~~ | ✅ 已迁至 `/account`（G-32） |

> **API 令牌已从系统设置页迁到 `/account`**，因为 `/api-tokens` 是当前登录用户
> 自己的资源，没有 `/users/{id}/tokens`，管理员无法代管。系统设置页挂一个
> 只能看自己令牌的 tab 会读成管理员面板。`/account` 路由**刻意不走角色门禁**——
> Operator 和 Administrator 看到的是同一页，给「改掉泄露的密码」加最低角色
> 会正好挡掉最需要它的人。

> tab 外壳放在「系统设置加载失败」的 guard **之外**：设置是三个嵌套分组一次读出，
> 部分响应会拖垮所有依赖它的分组，而通知目标、密钥环报告、Frigate 配置是三个
> 独立端点。「系统设置坏了」不应该同时意味着「看不到告警发不出去」。

**本轮另外两处归属**：
- **机位分组** → 摄像机页的「分组」tab（Vue 侧本就在 `cameras/CameraGroupsPanel.vue`）。
  用户/角色的范围编辑仍在「用户与权限」页——分组是资源，范围是授权，两者不合并。
- **备份与恢复** → 存储页的「备份与恢复」tab。**D-3 仍未裁决**（属本页还是系统
  设置），此处按模块图的默认「数据安全语义内聚」放在存储页；做成 tab 是为了让
  日后改归属的代价接近于零。

**摄像机页现在有四个 tab**：机位 / 接入设备 / 批量接入 / 分组。接入与批量**分开**
是因为批量是纯客户端的串行循环、不可预览（G-39），把它和逐步的向导放在一起会
让「先看一个再决定要不要全跑」这条路径变得含糊。

**回放页的操作与诊断是右侧面板，不是 tab**：两块内容都需要 stage 当前正在显示的
那个机位——对一个没在看的机位做手动触发或保护区间没有意义。tab 会把 stage 藏起来，
连带把选择上下文也带走。

**时区已知缺陷**：`display_timezone` 默认值是 `UTC` 而非 `Asia/Shanghai`，且 `recordings/reconciliation.py:276` 把 `tzinfo=UTC` 写死。UI 上暴露的时区设置目前不生效。**迁移时不要试图用前端时区转换来掩盖它**——应先修后端，修不好就在 UI 上如实标注该设置当前不生效。

**权限**：管理员。Operator 可见但只读。

---

### 3.11 用户与权限 `/users`

**职责**：谁能登录、能看到什么、能做什么。

**页面区块**
- 用户列表：用户名、角色、状态、最后登录
- 用户详情：基本操作（改密 / 重置密码 / 启用 / 停用）
- 角色列表：固定三角色及其能力矩阵
- API 令牌：创建、命名、最后使用时间、吊销
- 活动会话：查看、强制下线

**关键操作**
- 用户 CRUD、启停、重置密码
- 角色 CRUD
- 令牌创建 `POST /api-tokens`、吊销 `DELETE /api-tokens/{id}`
- 会话吊销 `DELETE /sessions/{id}`
- 修改自己的密码 `POST /auth/password/change`

**数据来源**
```
GET|POST          /users, GET|PATCH /users/{id}
POST              /users/{id}/disable, /enable, /password-reset
GET|POST          /roles, GET|PATCH /roles/{id}
GET               /permissions
GET               /sessions, DELETE /sessions/{id}
GET|POST          /api-tokens, DELETE /api-tokens/{id}
POST              /auth/password/change
POST              /auth/password-reset/request, /auth/password-reset/complete
GET               /auth/me, POST /auth/login, /auth/logout
GET               /setup/status, POST /setup/administrator
```

**收敛影响**：`GET /users/{id}/camera-scope`、`PUT /users/{id}/camera-scope`、`GET|PUT /roles/{id}/camera-scope` 这 4 个端点是**摄像头级授权**的实现，随 RBAC 收敛一并移除（ADR-0014 决策 6）。`GET /permissions` 返回的 19 个细粒度权限点也会收敛为 3 个角色。

**不要**在框架迁移的同时做这个收敛——权限是每个页面的守卫逻辑，两者同时改会让线上问题无法定位。顺序：先收敛（带后端测试），再迁框架。

**权限**：管理员。**普通用户不可访问**（但可改自己的密码）。

---

### 3.12 审计日志 `/audit` 【未接入】

**职责**：敏感操作留痕——谁改了机位、谁删了录像、谁看过凭据。

**状态**：后端端点存在且已脱敏，但**现有前端无任何入口**。导航项带「未接入」徽标。

**页面区块**
- 审计表格：时间、操作者、动作、资源类型、资源 ID、结果
- 详情抽屉：变更前后值 diff（**后端已脱敏**，前端不得二次加工）
- 过滤：操作者、动作、资源类型、结果、关联机位

**数据来源**
```
GET               /audit        (AuditPage)
GET /auth/me
```
支持过滤参数：`actor_id`、`action`、`resource_type`、`resource_id`、`camera_id`、`result`。

**凭据访问必须留痕**，这是本页存在的核心理由。SecretStore 的查看与轮换、API 令牌的创建都应产生审计记录。

**权限**：管理员。

---

## 4. 路由表

```text
/login                      独立页（无 AppShell）
/setup                      独立页（无 AppShell，setup/status 强制前置）
/                           → 重定向 /live
/live                        immersive
/playback                    immersive
/timeline                    standard
/cameras                     standard
/recording-schedules         standard
/events                      immersive
/alerts                      standard
/storage                     standard
/files                       immersive
/system                      standard
/users                       standard
/audit                       standard
*                            → 重定向 /live
```

路由实现采用 shadcn-admin 的文件路由（`src/routes/`），布局元数据放在路由定义里而非组件内。

---

## 5. 与现有 Vue 页面的映射

| 新模块 | Vue 页面 | 行数 | 变化 |
|---|---|---|---|
| 实时监控 | `LiveView.vue` | 1626 | 拆分 `LiveCameraTile.vue`(2591) 为容器 + 传输 hook |
| 录像回放 | `PlaybackView.vue` | 2813 | 抽 `PlaybackClock` 纯逻辑并补测试（当前零覆盖） |
| 事件时间轴 | — | — | **新增**，后端复用 `/events` |
| 摄像机 | `CamerasView.vue` | 1888 | 改用 TanStack Table |
| 录制计划 | `RecordingScheduleView.vue` | 2436 | 拆出时段网格组件 |
| 事件 | `EventsView.vue` | 1938 | 事件密度条可复用 |
| 告警规则 | `SystemView` alerts tab | — | **复活** `AlertsView.vue`(936，当前死代码) |
| 存储 | `StorageView.vue` | 2570 | 拆出容量水位 / 保留策略 / 备份三个区块 |
| 文件 | `FilesView.vue` | 1145 | 目录树改用 shadcn Tree |
| 系统设置 | `SystemView.vue` | 1458 | 10 tab → 6 tab，移出 3 项 |
| 用户与权限 | `SystemView` users tab | — | 移出并提级（`SystemAccessControlPanel.vue` 1305 行） |
| 审计日志 | — | — | **新增入口**，`GET /audit` 已就绪 |

### 顺带发现的死代码

迁移时可直接删除，不需要移植：

| 文件 | 行数 | 原因 |
|---|---|---|
| `views/DashboardView.vue` | 1022 | `router.ts:9` import 但无路由使用，`/dashboard` 重定向到 `/live` |
| `views/AlertsView.vue` | 936 | `router.ts:8` import 但无路由使用，`/alerts` 重定向到 `/events` |
| `views/WorkspaceView.vue` | 34 | 连 import 都没有的占位页 |

合计 **1992 行**。注意 `AlertsView` 的功能会以新形态复活（见 §3.7），不是直接扔掉——但它当前的实现不能复用，因为规则编辑器的实际形态应以 `GET /alert-policies` 的 schema 为准。

`styles.css:2950` 有一条注释引用 AlertsView 的 variant 命名，删除时需一并清理。

---

## 6. 待裁决问题

这些问题在动框架之前必须有结论，否则会带着未决语义重写。

### D-1：是否新增首页「概览」

**现状**：`/dashboard` 重定向到 `/live`，没有概览页。系统资源与健康信息（`DashboardView` 曾有 1022 行）现在埋在系统设置的 overview tab 里。

**选项**：(a) 不加，登录直达实时监控；(b) 新增「概览」一级页，含在线机位数、今日事件数、存储水位、异常告警、近期系统告警。

**建议**：(b)。shadcn-admin 以 Dashboard 为第一项，符合框架惯例；且 NVR 值班第一反应是「今天有没有事」，不是「看哪台机位」。内容可复用 `GET /system/health`、`/system/info`、`/events`、`/storage/targets`，无新端点。

### D-2：事件过滤的两套真相源

**现状**：`recording_policies.event_filter_json` 与 `alert_policies.match_json` 字段重叠、独立配置、互不同步。

**选项**：(a) 合并为单一 `event_filter` 实体，两个页面引用同一份；(b) 明确分工——录制策略只管「录不录」，告警规则只管「告不告」，删掉一边的过滤字段。

**建议**：(b)。两者的语义确实不同：录制过滤决定「哪些事件触发提升为正式录像」，告警过滤决定「哪些事件要通知人」。合并会让「录但不告警」无法表达。但必须删除重叠字段并做一次数据迁移，同时更新 `recordings/triggers.py:91-116` 的消费端。

**这是阻塞项**：ADR-0014 已定「RBAC 收敛先行」，本项应与之合并为同一个「迁移前置」批次。

### D-3：备份与恢复的归属

**现状**：现有 Vue 端把备份放在系统设置 tab；本文档暂定归入存储。

**选项**：(a) 归存储（数据安全语义内聚）；(b) 留在系统设置。

**建议**：(a)。备份与保留策略、存储目标共享「数据不丢」的心智模型，放一起用户才看得懂「归档 → 备份 → 保留 → 清理」的先后关系。

### D-4：事件时间轴是否独立成页 —— 已裁决

**结论**：(a) 独立成页，且**不需要**新增后端端点。

**依据**：PR-5f 实现时核对发现，`PlaybackTimelineService` 已经提供服务端分桶聚合
（`recordings/timeline.py:398-548`），`GET /cameras/{id}/timeline` 与
`POST /playback/timeline` 直接返回带录像段、空缺原因与聚合事件标记的完整轨道。
原判断「后端无聚合端点」有误——能力早已存在，只是未被本文档记录。

**遗留约束**（非阻塞）：`build()` 对区间内的片段与事件**没有 LIMIT**
（`timeline.py:562-590`），范围与粒度的组合完全由前端把关，见 **G-28**。

### D-5：萤石接入放在哪里

**现状**：萤石无 Linux SDK、局域网能力仅限手机端、事件只走公网 HTTPS WebHook。它是云事件源，不是可本地直连的摄像机。

**选项**：(a) 摄像机页只做 ONVIF/手动/批量，萤石作为「事件源」配置放系统设置；(b) 摄像机页增加独立「云摄像头」分区，明示走云中转。

**建议**：(a)。摄像机页的语义是「这台设备我能直连吗」，把需要公网 WebHook 的设备混进去会让用户对可用性产生错误预期。萤石配置归「事件源」，与 Frigate 并列。

---

## 7. 迁移批次

严格按 ADR-0014 的分批约束，**禁止 Big-Bang**。

| 批次 | 内容 | 前置 |
|---|---|---|
| **PR-0** | RBAC 收敛为三角色 + 裁决 D-2 事件过滤 | — |
| **PR-1** | 骨架 + theme.css + AppShell + 静态原型 | 已完成 |
| **PR-2** | 认证与外壳：登录、session、导航分组、权限守卫、布局形态二分 | PR-0 |
| **PR-3** | 只读页：事件 / 摄像机列表 / 存储列表（验证 TanStack Table 模式） | 已完成 |
| **PR-4** | 媒体页：实时监控 / 录像回放（传输层 + 容错 + 补测试） | 已完成 |
| **PR-5** | 写操作页：机位编辑 / 录制计划 / 告警规则 / 系统设置 / 文件导出 / 时间轴 / 用户 / 审计 | **已完成** |
| **PR-6** | 切换：删除 `frontend/`，`frontend-react/` 升为唯一前端。**应拆为「补齐 23 项缺失功能」+「切换」两段**，前置见 [`FRONTEND-PARITY-AUDIT.md`](FRONTEND-PARITY-AUDIT.md) | PR-5 |

迁移期间 Vue 应用必须保持可运行，两套前端由不同路径服务（`/` → Vue，`/next/*` → React）。

---

## 8. 相关文档

- [ADR-0014 — 前端栈迁移](adr/0014-frontend-react-shadcn-admin-migration.md) — 决策与后果
- [ADR-0013 — 前一版设计语言决策](adr/0013-frontend-design-language-shadcn-port.md) — 框架保留部分被 0014 取代
- [IMPLEMENTATION-MAP.md](IMPLEMENTATION-MAP.md) — 每个功能在代码里如何实现
- [INTEGRATIONS.md](INTEGRATIONS.md) — 第三方能力核实（萤石、Frigate 等）
