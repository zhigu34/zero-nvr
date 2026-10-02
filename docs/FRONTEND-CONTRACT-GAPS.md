# 前端迁移中发现的接口契约缺口

按 [ADR-0014](adr/0014-frontend-react-shadcn-admin-migration.md) 的批次推进时，逐模块核对 `backend/app/api/v1` 得到的实际契约与原型假设之间的差异。

这些不是 bug，是**接口设计缺口**。原型阶段用 fixture 数据把它们盖住了，接真实数据时才暴露。每条都记录了影响面与建议的修法。

状态：🔴 阻塞或高影响 · 🟡 影响体验 · ⚪ 已记录不阻塞

---

## G-1 存储目标没有只读容量接口 🔴

**事实**：`GET /api/v1/storage/targets` 返回的 `StorageTargetView` 是

```text
{id, type, role, name, enabled, config, credentials_configured}
```

读路径上**任何位置都没有容量字段**。容量只在 `POST /storage/targets/{id}/test` 的 `StorageTargetTestView` 里返回，而那是一个主动探测目标、带副作用的 POST。

**影响**：一个「存储」页面天然要做的事是显示容量水位。用现有接口实现它只有两条路——

- 页面加载时对每个目标发一次探测 POST（把只读操作伪装成写操作，且目标多时是 N 次网络往返加磁盘 IO）
- 不显示容量（页面失去存在意义）

前端目前的选择是**后者**：容量位显示「尚未检测」，配一个用户主动点击的「检测容量」按钮。这让页面在修复前处于半残状态，但比画一条假水位线诚实。

**建议修法**：新增 `GET /storage/targets/{id}/stats`（或把 `free_bytes` / `total_bytes` / `used_percent` / `capacity_level` 加进 `StorageTargetView`），由后台定时任务采集后落库，读接口直接返回快照。探测仍然是 POST，但那是采集器的职责，不是页面的。

---

## G-2 事件列表不返回机位名 🟡

**事实**：`EventView.camera_id` 是 UUID，没有名称。机位名要从 `GET /api/v1/cameras` 单独取。

**影响**：任何显示「机位」列的事件页面都必须在客户端做一次 join。事件属于高频滚动页面，这意味着机位列表要么常驻缓存（可接受），要么每翻一页重取一次（不可接受）。事件来自非摄像机源时 `camera_id` 为 `null`，此时没有名字可显示。

**建议修法**：在 `EventView` 上加一个 `camera_name: str | null` 冗余字段。事件写入时机位名已经确定，冗余成本近乎为零，却省掉整条 join 链路。

---

## G-3 机位列表缺码流绑定与时钟偏差 🟡

**事实**：`GET /cameras` 返回 `CameraSummary`，其中没有

- 码流用途绑定（`RECORD` / `LIVE_HIGH` / `LIVE_LOW` / `AI_DETECT` / `SNAPSHOT` / `AUDIO`）——在 `GET /cameras/{id}` 的 `CameraDetail.bindings`
- 时钟偏差——在 `GET /cameras/{id}/clock`
- 录像占用

**影响**：机位列表是用户最常看的表格，但「这路码流绑给录像用了吗」「这路机器时钟准不准」恰恰是排障时最先要看的两列。补这两列意味着对每行发一次请求（N+1），10 路机位就是 10 次往返。

时钟偏差还有第二个问题：`GET /system/camera-clock-health` 提供全局视图，但 `CameraSummary` 里没有对应字段，导致列表页无法零成本展示。

**建议修法**：在 `CameraSummary` 上加 `clock_offset_ms: int | null` 与 `stream_bindings: dict[purpose, profile_id | null]` 两个浅层字段。机位数通常在几十量级，这个冗余远比 N+1 划算。

---

## G-4 `connectivity_status` 是裸字符串而非枚举 ⚪

**事实**：`CameraSummary.connectivity_status: str = "online"`，没有 `Literal` 约束。同类的还有 `events.source`、`events.category`、`events.severity`、`alerts` 的匹配字段。

**影响**：前端无法穷举合法取值。任何一处 `switch` 都必须带 default 分支，写漏了就是空白状态格而不是可见的降级状态。

**建议修法**：能枚举的字段一律加 `Literal`，或在后端暴露一个 `GET /meta/enums` 供前端拉取。当前前端已加 `normalizeConnectivity()` 把未知取值降级为 `unknown`（有明确文案），并有测试锁定。

---

## G-5 事件分页是游标式，没有总数 ⚪

**事实**：`GET /events` 用 `next_cursor` + `limit`(1–200)，不返回总数。

**影响**：事件页不能显示「第 3 页 / 共 1284 条」，只能「加载更多」。这对长尾事件流其实是**正确**的设计（总数需要额外扫描），前端已按此实现，测试锁定不得出现 `page=` 参数。

**建议**：不改。这是设计选择，不是缺口。

---

## G-6 `connectivity_status` 与 `enabled` 语义重叠 ⚪

**事实**：`CameraSummary` 同时有 `enabled`、`maintenance`、`retired_at`、`connectivity_status` 四个状态位，且没有说明它们的优先级关系。

**影响**：机位可以处于 `enabled=true` 且 `connectivity_status=offline`，也可以 `retired_at != null` 但 `connectivity_status=online`（最后一次探测的结果）。前端目前按「退役 > 维护 > 停用 > 连接状态」的顺序取一个展示值，但这是前端猜的，后端没有权威口径。

**建议修法**：在后端补一个归一化的 `effective_status` 字段，状态优先级由后端定义一次。

---

## 与 ADR-0014 的关系

ADR-0014 决策 4 冻结了 API 契约，本迁移不改后端。上面 G-1 / G-2 / G-3 都需要改后端，因此**不能在 PR-3 到 PR-6 之间顺手改**——那会让「契约冻结」失效。

处理方式：

1. 迁移期间前端按现状实现，用 UI 明说哪些字段拿不到（已做）
2. 上述缺口记在本文件，走独立的后端变更流程
3. 缺口修复后前端单独一次 PR 跟进

这样每一步都可验证，且前端迁移的「零后端改动」承诺保持成立。
