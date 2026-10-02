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

# 媒体页（PR-4）新增缺口

## G-7 `GET /cameras/{id}/live` 的 `quality` 参数被接受但完全忽略 🔴

**事实**：端点签名声明了 `quality: Literal["auto","high","low"] = "auto"`
（`cameras/api.py:2802-2806`），但下游的 `_select_live_stream(...)` 根本没有这个形参
（`cameras/api.py:2380-2387`）。码流选择实际由 `source`（`auto`/`sub`/`main`/`profile`）
与 `profile_id` 决定。

**影响**：如果前端按签名实现一个「画质：高/低」切换器，用户点了没有任何效果——这是典型的
「看起来能用」的假控件。`CameraLiveStreamView` 里也没有任何字段回显请求的 quality。

**当前处理**：`api/live.ts` **不发送** `quality`，并有契约测试断言 URL 里不含该参数。
分辨率选择改用 `source`，界面按 `describeLiveSource()` 展示 descriptor 里的真实
`source_role` / `profile_name` / `width`×`height` / `fps`——这是 spec 0020 §"Source and
protocol preference" 明确要求的（「UI 必须显示真实媒体路径，而不是通用的 SD/HD 标签」）。

**建议修法**：要么删掉 `quality` 参数，要么让它真正生效。保留一个不生效的 API 参数比没有
更糟。

---

## G-8 直播会话续期不重新签发 `hls_url`，30 分钟后必然失效 🔴

**事实**：`hls_url` 指向 ZLM 代理下的签名地址
`/zlm/{app}/{stream}/hls.m3u8?zn_exp=&zn_sig=&zn_sid=`，签名 TTL 固定 **30 分钟**
（`zlm/access.py:20`）。而 `POST /cameras/{id}/live/session/{sid}/keepalive` **只更新
media session 的过期时间并回一个 `expires_at`**（`cameras/api.py:3637-3642`），既不重签
URL，也没有任何「刷新直播 URL」的独立端点。

**影响**：一个整晚开着不关的监控页，到 30 分钟后所有瓦片会同时黑掉。若此时页面的续期定时器
还在跑，运维会看到「续期成功」但画面不动——比直接报错更难排查。

**当前处理**：待实现。传输层需要把「会话续期」与「URL 重取」当成两件事：keepalive 只用来
延长 media session 占用，而 HLS 签名过期必须靠**重新调用 `GET /cameras/{id}/live`**
（换一个新的 `media_session_id`，并释放旧的）来续命。UI 需要在签名过期前主动重取，而不是
等瓦片报错。

**建议修法**：让 keepalive 在 `expires_at` 临近时返回新的 `hls_url`（复用同一个
`media_session_id`），或在 `CameraLiveStreamView` 上给出明确的 `hls_expires_at`，让前端知道
何时必须重取。

---

## G-9 `transports` 声明支持 WebRTC，但响应里没有 WebRTC URL 🟡

**事实**：`CameraLiveStreamView.transports` 是 `["webrtc","hls"]`（或 `["hls"]`），
`transport` 恒为 `"hls"`，而唯一的 URL 字段是 `hls_url`。WebRTC 路径要靠
`POST /cameras/{id}/live/whep` 做 **SDP offer/answer 交换**（`cameras/api.py:3163+`），
不是一个可以直接交给浏览器的 URL。

**影响**：前端无法「按能力挑传输」。规范 0020 要求「后端返回能力/描述符，前端不硬编码单一
播放路径」，但当前 payload 不足以支撑——想走 WebRTC，前端必须自己实现 SDP 协商与 ICE。

**当前处理**：PR-4 的直播页只实现 HLS 传输路径（`hls_url` 可直接进 `<video src>` 或
hls.js）。WebRTC 留作后续独立批次。

---

## G-10 `POST /playback/timeline` 限 2–9 路，但布局支持 16 槽 🟡

**事实**：`PlaybackAlignedTimelineRequest.camera_ids` 校验为 2–9
（`recordings/api.py:1416-1440`），而直播预览墙的 `layout_slots` 合法值是 4/9/16。

**影响**：16 宫格回放墙必须拆成两次请求，且两次请求之间没有跨批次的绝对时间对齐保证。
spec 0006 的 tolerant 模式要求「所有轨道保持同一绝对时间区间，用于同步与后续的跳过决策」，
拆批之后这个保证只在批内成立。

**当前处理**：`api/playback.ts` 导出 `MAX_ALIGNED_CAMERAS = 9`，并有测试断言
`MAX_ALIGNED_CAMERAS < 16`，让调用方在写死 16 格时立刻失败而不是静默丢相机。

---

## G-11 `gap.reason` 存在两套词汇表 🟡

**事实**：`TimelineGapView.reason` 是严格的 8 值 `Literal`
（`not_scheduled|no_event|source_lost|runtime_restart|storage_failure|missing_media|purged|unknown`，
`recordings/schemas.py:19-28`），而 `PlaybackResolve` 的 `gap.reason` 是**裸 `str`**
（`schemas.py:271`），实测取值只有 `storage_failure` / `purged` / `missing_media` / `unknown`
四种。`pending.reason` 更极端——只有 `remote_restore_required` 一个常量取值。

**影响**：同一个「这段没画面」的语义，时间轴接口和解析接口用不同的类型强度表达。前端必须
为两者准备两套渲染路径，而裸字符串那一侧无法穷举。

**当前处理**：`gapReasonLabel()` 对未知取值降级为「原因未知」而不是渲染原始枚举值，并有测试
锁定（`playback.spec.ts`）。

**建议修法**：让 `PlaybackResolve` 的 `gap.reason` 复用同一个 `Literal`。

---

## G-12 `resolve` 返回的 `url` 不带 offset，只能靠浏览器 seek 定位 🟡

**事实**：`url` 恒为 `/api/v1/recordings/{segment_id}/media`（`recordings/api.py:1273-1275`），
不含 offset；`GET /recordings/{id}/media` 也没有任何 offset / Range 起点参数。

**影响**：拿到 `offset_ms: 15000` 之后，前端只能把 URL 塞给媒体元素、再在
`loadedmetadata` 之后写一次 `currentTime = 15`。这带来一个必须精确处理的分支：普通 MP4
时基从 0 开始，可以这么 seek；**fMP4 的时间戳原点非零**（实测约 123.5s），再减去一次就会
跳到 3 万秒之外。Vue 实现靠 `mediaTimebase.ts` 的 origin 追踪绕开，逻辑复杂且已发现失效路径
（见下）。

**建议修法**：给 `/media` 支持 `?offset_ms=`，或让 resolve 返回一个服务端已裁剪的 URL。

---

## G-13 预览墙的分辨率/帧率无任何接口暴露 🟡

**事实**：帧预算写死在服务端调度器里——4 槽 640px@5fps、9 槽 480px@3fps、16 槽
320px@2fps（`live_preview_wall.py:50-54`），没有任何端点返回这张表。

**影响**：前端无法知道每个槽位该按多大尺寸排版，只能硬编码一份并祈祷后端不改。属于典型
的双份真相源。

**当前处理**：`api/live.ts` 里 `PREVIEW_WALL_RESOLUTION` 硬编码这张表，并有测试锁定。
这是妥协，不是解决——后端一改就漂移。

---

## G-14 直播布局不校验 `camera_ids` 数量与槽位数一致 🟡

**事实**：`LayoutState` 只校验结构（`live_layouts.py:27-45`），不校验
`len(camera_ids) <= slots`；而 WebSocket 同步消息**强校验** `slot < layout_slots`
（`live_preview_wall.py:113`），违规直接 `close(1008)`。

**影响**：能保存、不能播。用户保存一个 16 路相机到 4 槽布局里，保存成功，播放时整面墙断开，
且 WS 只回一个 `fatal` 消息，没有任何定位到具体哪个槽位的诊断。

**建议修法**：写入侧加 `len(camera_ids) <= slots` 校验，让错误在保存时就暴露。

---

## G-15 预览墙 WebSocket 强制同源 Origin，跨源静默断开 🟡

**事实**：`same_origin_websocket()` 校验 `Origin` 的 scheme/host/port 与自身 URL **严格
一致**（`live_preview_wall_api.py:41-68`），不通过则 `close(1008)`，无错误消息体。

**影响**：任何非同源部署形态（分离域名、反代改写、某些开发环境）下，预览墙会静默不可用。
开发期 `vite` 代理 `/api` 虽能保持同源，但 `ws: true` 代理的 Origin 重写行为需要实测确认。

**当前处理**：待验证。契约测试已覆盖帧格式解析，WS 连接本身需要一次真实联调。

---

## 与 ADR-0014 的关系

ADR-0014 决策 4 冻结了 API 契约，本迁移不改后端。上面 G-1 / G-2 / G-3 都需要改后端，因此**不能在 PR-3 到 PR-6 之间顺手改**——那会让「契约冻结」失效。

处理方式：

1. 迁移期间前端按现状实现，用 UI 明说哪些字段拿不到（已做）
2. 上述缺口记在本文件，走独立的后端变更流程
3. 缺口修复后前端单独一次 PR 跟进

这样每一步都可验证，且前端迁移的「零后端改动」承诺保持成立。
