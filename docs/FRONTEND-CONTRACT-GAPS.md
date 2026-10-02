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

# 写操作页（PR-5）新增缺口

写操作与只读页的风险完全不同：只读页缺字段，最坏是界面上少一列；写操作缺语义，最坏是**用户以为保存成功了**。因此本节以「会不会让用户误判」排序。

## G-16 写操作没有乐观锁，并发编辑静默覆盖 🔴

**事实**：四个模块的视图 schema 都**没有** `version` / `updated_at` / `ETag`：
`CameraDetail`（`cameras/schemas.py:182`）、`RecordingPolicyView`（`recordings/schemas.py:155`）、
`SystemSettingsView`、`ExportView` 均如此。服务端内部确实有 `Camera.config_revision`
与 `fence_config_revision`（`cameras/service.py:60,67`，冲突抛 409 `camera_configuration_changed`），
但**它只用于服务端自身的长耗时操作防竞态，不出现在任何响应里**，客户端既读不到也传不了。

**影响**：两个浏览器同时编辑机位或录制计划，后保存的**静默覆盖**先保存的，没有任何冲突提示。
对「设置了什么录制计划」这种配置，静默覆盖的代价是排查很久的「录像怎么没按我设的跑」。

**当前处理**：前端无法解决。已在 `lib/save.ts` 的注释里写明这是**后端待办**而非前端妥协。
在修好之前，前端不做任何「假装有冲突检测」的 UI。

**建议修法**：在四个视图上补 `version: int`（或 `updated_at`），写接口接受 `expected_version`
不匹配即 409。这是独立的后端变更，走 ADR-0014 决策 4 的例外流程。

---

## G-17 写入可能「已保存但后续失败」，HTTP 503 🔴

**事实**：多个写端点在**数据库已提交之后**的异步动作失败时，返回 **503** 并在
`details` 里带一个 `*_persisted: true` 标志：

| 端点 | code | details 标志 |
|---|---|---|
| `POST /cameras/{id}/enable\|disable\|retire` | `camera_runtime_queue_unavailable` | `camera_persisted` |
| `PUT /cameras/{id}/stream-bindings` | `camera_runtime_queue_unavailable` | `configuration_persisted` |
| `PUT /cameras/{id}/recording-policy` | `recording_task_queue_unavailable` | `policy_persisted` |
| `PATCH /system/settings` | `recording_task_queue_unavailable` | `settings_persisted` |
| `POST /exports` | `export_task_queue_unavailable` | `export_persisted` |

**影响**：一个只会看 HTTP 状态码的客户端会把这些当成「保存失败」，于是重试——
但配置**已经写进去了**，重试是重复写入。反过来，如果客户端一律按成功处理，
用户看到的会是「保存成功」而运行时（媒体流/转码/录制协调）根本没跟着变。

**当前处理**：`lib/save.ts` 的 `failure` 回调可读取 `ApiError.details`，
写操作页据此区分「什么都没存」与「已存但运行时没跟上」，后者必须**明确告知用户**，
措辞不能是「操作失败」。

**建议修法**：这不是缺口而是可用但少见的契约。前端必须显式支持，建议在
`client.ts` 的 `ApiError` 上加一个 `persisted` 判定属性，避免每个写页各写一遍。

---

## G-18 录制「没生效」完全不报错，只能从 `runtime` 读出来 🔴

**事实**：`PUT /cameras/{id}/recording-policy` 会吞掉 `recording_stream_offline` 与
ZLM 的 `camera_stream_start_timeout`（`recordings/api.py:648,672`），**不抛错、不改状态码**，
改为在响应的 `runtime` 字段里体现：

```text
runtime.recording: bool | null      # null = 媒体运行时完全不可观测，不等于 false
runtime.stream_online: bool | null
runtime.blockers: list[str]         # 阻塞原因的错误码数组
```

**影响**：这是最容易产生「我明明设了连续录制却没有录像」的一类。HTTP 200、
保存成功提示、页面一切正常——但 `runtime.recording` 是 `false` 或 `blockers` 非空。
**只看 HTTP 状态码的实现会完全错过。**

**当前处理**：录制计划页必须把 `runtime` 当作一等公民渲染。`recording === null` 要显示
「不可观测」而不是「未录制」——把不可观测画成「未录制」会让用户去查一个不存在的问题。

**另注**：`runtime.blockers` 里的 `recording_storage_capacity_critical` 等错误码
与 G-1 的容量缺口相关：容量不探测就不知道是否已到临界。

---

## G-19 分享链接是公开可下载的凭证 🔴

**事实**：`GET /shared/exports/{token}/download` **没有 `require_permission`、没有 session 校验**
（`exports/api.py:532`）。token 是 `secrets.token_urlsafe(32)`，库里只存 sha256，
但**明文 token 本身就是凭证**。密码保护走 HTTP Basic，不是登录流程。

**影响**：把导出链接贴进任何聊天工具等于把录像公开。任何把它描述为「内部分享」的
界面文案都是错的。

**当前处理**：导出页的分享区必须**明说该链接对任何持有者公开**，并提示有效期。
另外 `expires_in_hours` 上限声明 720 小时，但实际取 `min(export.expires_at, ...)`，
而导出 24 小时就过期——**分享实际最长 24 小时**，界面不能承诺更长。

**建议修法**：若要真正的内部分享，需要分享端点也走 session 校验，或引入
「必须登录 + 归属校验」。这是安全设计变更，不是 bug 修复。

---

## G-20 保留天数不在录制计划里 🔴

**事实**：`RecordingPolicyPut` 只有 `retention_policy_id` 外键（`recordings/schemas.py:133`），
**没有天数字段**。实际天数在 storage 模块的 `ordinary_keep_days` / `alarm_keep_days`
（`storage/schemas.py:85–110`，0–36500 天）。

**影响**：录制计划页天然要显示「这段录像保留多久」，但按现有契约拿不到。要显示就得
再发一次 storage 请求并做 join，而 G-1 已经说明 storage 连容量都要靠主动探测。

**当前处理**：计划页显示保留策略的**名称/ID**，并明确提示天数在「存储与保留策略」中配置，
不在此处修改。**不编造天数。**

---

## G-21 `time_sync_mode` 与 `manufacturer`/`model` 有静默失效路径 🟡

**事实**：

1. `time_sync_mode != "ignore"` 时，所属 Device 的 `adapter_type` **必须为 `onvif`**，
   否则 400 `camera_time_sync_unsupported`（`cameras/service.py:405`）。
   也就是说 **manual_rtsp 机位只能设 `ignore`**，而 schema 允许三个值。
2. `manufacturer` / `model` / `form_factor` 在 `camera.device_id` 为 null 时
   **静默丢弃**（`cameras/service.py:438`）——不报错、不提示、返回 200。

**影响**：第 2 条尤其恶劣：用户填了厂商型号，保存成功，刷新后没了，没有任何痕迹。

**当前处理**：客户端预校验。编辑面板在 `adapter_type` 不是 onvif 时只提供 `ignore` 选项；
`device_id` 为空的机位直接不展示厂商/型号/形态字段，而不是提供一个会被静默丢弃的输入框。
**前端预校验不是妥协**：这里的 400 与静默丢弃都是后端在替前端做它不该做的判断。

**另注**：`retire` 会强制 `enabled=false`；`restore` **不会**恢复 enabled
（`cameras/service.py:494`），恢复后需要再点一次启用。界面必须说明这一点，
否则用户会以为恢复完就能用了。

### G-22 `CameraDetail` 不返回 `device_id`，厂商/型号无法安全编辑 🟡

**事实**：`CameraDetail` 只有两个额外字段——`streams` 与 `bindings`
（`cameras/schemas.py:182-185`），**没有 `device_id`**。而 G-21 的第 2 条说
`manufacturer` / `model` / `form_factor` 在 `camera.device_id` 为 null 时被静默丢弃
（`cameras/service.py:438`）。

**影响**：前端拿不到判断依据。一台没有关联设备记录的机位（例如手动 RTSP 接入），
填了厂商型号、点保存、返回 200、刷新后字段消失，**全程没有任何提示**。
提供一个「可能保存也可能不保存」的输入框，比不提供更糟。

**当前处理**：编辑面板**不提供**这三个字段，并在界面上说明原因。
`lib/cameraValidation.ts` 里的 `acceptsDeviceFields()` 已写好判定逻辑并有测试，
等后端在 `CameraDetail` 上补出 `device_id`（或一个 `device_linked: bool`）
就能直接接上。

**建议修法**：在 `CameraDetail` 上加 `device_id: uuid | null`。
更好的做法是让 `PATCH` 在会丢弃字段时返回 4xx 而不是 200——静默丢弃本身
就是应当修掉的契约问题（G-21 第 2 条）。

---

### G-23 导出排队失败会留下一条永远不会被执行的记录，且重试会骗过操作者 🔴

**事实**：`POST /exports` 先提交事务再入队，且**只在 `created` 为真时入队**
（`exports/api.py:195-225`）。因此任务队列不可用时：

```text
1. 事务提交          →  库里多一条 state=PENDING 的记录
2. 入队失败          →  没有任何 worker 会拿到这条任务
3. 返回 503          →  code=export_task_queue_unavailable
                        details={export_persisted: true, export_id: "..."}
```

而重试这一次请求（同一个 `Idempotency-Key`）会命中
`ExportService._existing_idempotent`，**返回这条卡住的记录并返回 201**
（`exports/service.py:57-71`）。任务始终没有入队。

**影响**：操作者看到 201、列表里出现一条「排队中」的导出、然后它永远停在
排队中。**看起来成功的重试比原本的 503 更糟**——它把一个明确的失败变成了
一个沉默的失败。`details.export_id` 的存在说明后端意识到这条记录要靠人去
收拾，但契约里没有任何办法让它重新入队。

**当前处理**：前端在收到 `export_persisted: true` 的 503 时**作废**幂等键并
明说「这条导出不会被自动执行，请取消后重新创建」；列表里 `PENDING` 超过 2 分钟
的记录会显式提示「再等下去不会自行完成」。逻辑在 `lib/exportIntent.ts`
（`strandedExportId` / `retryIsSafe`）与 `lib/exportMutations.ts`。

**建议修法**：三选一，从优到劣——

1. 入队失败时把状态置为一个独立的 `NOT_QUEUED`（而非 `PENDING`），并提供
   `POST /exports/{id}/retry` 重新入队
2. 入队失败时回滚事务（则 503 不带 `export_persisted`，语义变简单）
3. 保留现状但**响应里带 `queued: false`**，让前端能区分「已排队」与「已记录」

第 1 条最好：它同时解决了 G-24。

### G-24 `ExportView` 没有进度，也没有「是否已入队」 🔴

**事实**：`ExportView`（`exports/schemas.py:19-38`）有 `state` / `started_at`
/ `completed_at`，**没有进度百分比**，也**没有 `queued_at`**（只有 `created_at`）。
`created_at` 是事务写入时刻，`started_at` 是 worker 真正开始时刻。

**影响**：

- **进度**只能靠已耗时外推，那是「披着进度条外衣的编造数字」。前端不画进度条，
  改为显示状态与已耗时。
- **是否卡住**只能靠 `now - created_at > N 分钟` 猜测。一个正常排队 5 分钟的
  导出和一个（G-23 的）永远不会被执行的导出，在这个字段下无法区分。
  前端用「PENDING 超过 2 分钟就提示」作为近似判据，阈值是拍的。

**建议修法**：`ExportView` 增加 `queued_at: datetime | null` 与
`progress_percent: int | null`（worker 自己报，不让前端外推）。

### G-25 没有跨机位的录像片段列表接口 🟡

**事实**：`GET /cameras/{camera_id}/recordings` 是**唯一**的片段列表端点
（`recordings/api.py:1123`），必须带 `camera_id`。契约里没有
`GET /recordings?from=&to=` 这种跨机位查询。

**影响**：一个「文件」页面天然想做的是「全部录像」。这个根节点没有接口支撑。
旧 Vue 页面的 `buildTree()` 用 fixture 造了它，看起来能跑。

**当前处理**：React 版按机位浏览，左侧机位选择器取代跨机位树。
一次导出也只覆盖一个机位（`ExportCreate.camera_id` 是单值）。

**建议修法**：新增 `GET /recordings?from=&to=&camera_id=`（`camera_id` 可选），
复用 `RecordingCatalogQueryService.list_camera` 的过滤逻辑即可，
前端筛选逻辑不用动。

### G-26 片段没有分辨率，存储位置要 N+1 才能拿到 🟡

**事实**：`RecordingSegmentView`（`recordings/schemas.py:200-215`）有 `codec` /
`container` / `size_bytes`，**没有分辨率**。而「本地 / 已归档 / 备份」这个位置
语义在 `GET /recordings/{id}/locations` 上，每个片段一次请求。

**影响**：片段列表想显示两列都做不到——

- 分辨率：字段根本不存在
- 存储位置：一页 100 行 = 100 个请求

**当前处理**：两列都不画。保护状态改用**按机位一次取回**的保护时间窗在本地
求交（`api/protections.ts` 的 `overlapsProtection`），因为保护本来就是
「机位 + 时间窗」而不是逐片段字段。

**建议修法**：`RecordingSegmentView` 加 `width` / `height`（catalog 写入时
就有，`RecordingSegment` 表里有 stream 关联），并在列表响应里带一个
`locations: [{storage_type, storage_role, state}]` 摘要数组——
同一次查询 LEFT JOIN 出来，不增加往返。

### G-27 保护没有片段维度，只能靠时间重叠推导 🟡

**事实**：`RecordingProtectionCreate`（`recordings/schemas.py:284-288`）是
`{started_at, ended_at, reason, expires_at}`，作用域是**机位**，模型里
**没有 `segment_id`**。查询也只有 `GET /cameras/{id}/recording-protections`。

**影响**：旧 Vue 页面的逐片段「保护锁」开关在契约里不存在，而且**如果照搬会
产生误导**——同一时间窗内的所有片段会一起被锁上，而不是用户点的那一个。

**当前处理**：只做只读标记。「与保护时间窗重叠」在本地求交得出，
并用半开区间（`[start, end)`）——这一点在本项目已经咬过人
（见 PR-4 的 `previousPlayableInstant`）。半开语义由
`api/protections.spec.ts` 钉住。

**建议修法**：如果产品确实需要「锁这一段」，契约要么加 `segment_id`，
要么在 UI 上明确它是时间窗操作（后者成本为零）。

---

## 写操作的标度陷阱

同一批接口里「时长」有**三套单位**，混用会产生量级错误：

| 单位 | 字段 |
|---|---|
| **秒** | `segment_target_seconds` / `pre_roll_seconds` / `post_roll_seconds` / `prebuffer_fragment_seconds` / `gop_seconds`(float) |
| **毫秒** | `requested_duration_ms` / `actual_duration_ms` / `offset_ms` / `duration_ms` / `rtt_ms` |
| **小时** | `expire_in_hours`（分享有效期），而同模块的 TTL 用 `_seconds` |

注意 `segment_target_seconds` 是**秒**，而它最终落库的 `RecordingSegment.duration_ms`
是**毫秒**——**后端不做换算，换算发生在展示层**。同一份录制计划页上会同时出现
「目标分段 300 秒」和「本段实际 300000 毫秒」，必须分别格式化。

## 与 ADR-0014 的关系

ADR-0014 决策 4 冻结了 API 契约，本迁移不改后端。上面 G-16 / G-19 需要改后端，因此**不能在 PR-3 到 PR-6 之间顺手改**——那会让「契约冻结」失效。

处理方式：

1. 迁移期间前端按现状实现，用 UI 明说哪些字段拿不到（已做）
2. 上述缺口记在本文件，走独立的后端变更流程
3. 缺口修复后前端单独一次 PR 跟进

这样每一步都可验证，且前端迁移的「零后端改动」承诺保持成立。
