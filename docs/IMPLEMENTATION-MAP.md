# zero-nvr 功能实现地图

> 本文回答一个问题：**每个功能在代码里到底是怎么跑起来的。**
>
> 与 [ARCHITECTURE.md](ARCHITECTURE.md) 的分工：那份是**设计态**（讲 ownership 边界、为什么这么分层，冻结于 ADR 0012），本文是**实现态**（讲某个功能点一下之后，依次经过哪些文件、哪些函数、哪张表）。所有结论均来自当前代码，标注 `文件:行号` 可直接跳转核对。

**核对方式**：本文行号对应 commit `72de319`（main）。若代码变动，以代码为准。

---

## 0. 三分钟速览

| 维度 | 事实 |
|---|---|
| 后端 | FastAPI，12 个业务模块，40 张表，143 个端点 |
| 前端 | Vue 3 + TS，13 个视图，路由守卫强制 `/setup` 初始化 |
| 部署 | 7 个容器，5 个可选 profile；默认只起 zero-nvr / worker / zlmediakit |
| 异步 | Huey 队列，API 只入队不干活；`dispatcher.py` 是纯入队边界 |
| 媒体真相源 | **ZLM**（拉流 + 落盘），zero-nvr 只管策略与元数据 |
| 元数据真相源 | SQLite（默认）/ PostgreSQL（可选） |

**四条贯穿全局的真相源规则**：

1. **媒体流**——ZLM 权威。zero-nvr 不碰 RTP，只调 ZLM HTTP API 建代理。
2. **录像文件**——ZLM 的 FileRecorder 权威，zero-nvr 不写视频字节（预录提升是唯一例外，见 §4.4）。
3. **录像元数据**——数据库权威。hook 收到封盘广播时**同步写库**，另有扫盘对账兜底。
4. **运行时状态**——**不落库**。在线/录制中一律实时问 ZLM（`getMediaList`），DB 不存"我现在在录"这种状态（ADR 0008）。

---

## 1. 启动链：进程起来的前 20 行决定了什么

入口 `backend/app/main.py` 的 `lifespan()`，顺序**不可交换**：

```text
ensure_runtime_directories()          # 建 data/cache/recordings 目录
database.initialize_runtime() + ping() # 连库
assert_database_schema_current()      # 非 test 环境：校验 DB schema 版本
AuthService.ensure_builtin_roles()     # 幂等，内置角色
      ↓
zlm_runtime_observation.rebuild()      # ① 问 ZLM 现在有哪些流在线/在录
runtime_reconciler.enqueue_all()       # ② 把所有 camera 排进对账队列
onvif_events.start()                   # ③ 起 ONVIF 事件订阅
frigate_mqtt.start()                   # ④ 起 Frigate MQTT 订阅
      ↓
yield（开始服务）
```

**为什么 ① 必须在 ② 之前**：对账任务需要先知道 ZLM 那边"真实状态是什么"，否则会把"ZLM 已在录"误判成"状态丢失"而反复重启录制器。`main.py:142` 先 rebuild，`:157` 再 enqueue，就是这个原因。

启动只做这一次。之后的状态更新靠 **ZLM webhook 主动推**（`internal/zlm_hooks.py:178`）。

> **注意**：没有基于 ONVIF 的周期性心跳。健康信号只有「启动一次 + ZLM webhook」两条路径。这两个概念容易混淆——`cameras/runtime_observation.py` 判的是**流在不在**，不是**摄像头通不通**。

---

## 2. 机位接入链：添加一台摄像头

### 2.1 三种添加方式

| 方式 | 端点 | 说明 |
|---|---|---|
| 手动 RTSP | `POST /api/v1/cameras` | 直接填 `rtsp://`，`api.py:617` |
| ONVIF 导入 | `POST /api/v1/cameras/onvif/import` | 填 IP + 账号密码，`api.py:723` |
| 网段扫描 | `POST /api/v1/cameras/discovery` | WS-Discovery 扫网段，`api.py:1222` |

前端入口统一在 `components/cameras/CameraOnboardingPanel.vue:69`（默认 ONVIF 模式），支持 CSV 批量导入（`:408`）。

### 2.2 密码怎么存（重要）

**RTSP URL 里的账号密码不进数据库明文字段**：

- RTSP 端点**只存 `host/port/transport`**，不存 path 和 query；整条 URI 加密后存 `secret_records` 表 —— `cameras/service.py:177-179`
- ONVIF 密码进 `SecretStore.create_json(kind="onvif_credential")` —— `onvif_onboarding.py:730-736`
- `camera_stream_profiles.stream_uri_ref` 只是一个**指针**，指向密文 —— `cameras/models.py:293`

所以查 `cameras` 表看不到任何密码。想看密文得去 `secret_records`，那已经是密文了。

### 2.3 ONVIF 探测做了什么

`integrations/onvif/adapter.py`（6 个文件，无独立 discovery.py，全在 adapter 里）：

```text
discover()  → WS-Discovery 扫网段              :932
  └ _discover_blocking() → ThreadedWSDiscovery :951
_inspect_profile() → GetStreamUri              :857
  ├ 读 VideoEncoderConfiguration/Resolution
  ├ gop_seconds = GovLength / fps              :887
  └ GetStreamUri(RTP-Unicast + RTSP)           :902
```

另有 `read_system_clock` `:584`（SNTP，喂给时钟投影）、`configure_ntp` `:653`、`ptz_move/stop` `:719/797`。

### 2.4 码流绑定：一个机位多条流 + 用途

这是**最容易踩坑的模型**，也是之前「保存失败: Camera has no RECORD stream binding」那个 bug 的根源。

```text
Camera (1) ──< CameraStreamProfile (N)   一条 profile = 一条实际码流
                │  adapter_profile_key: ONVIF token 或 manual-primary/secondary
                │  stream_uri_ref: → secret_records（加密 RTSP URI）
                │
Camera (1) ──< CameraStreamBinding (N)   把某条 profile 绑到某个「用途」
                   (camera_id, purpose) 唯一约束
```

**6 个合法用途**（DB CHECK 约束 `models.py:327`）：`RECORD` / `LIVE_HIGH` / `LIVE_LOW` / `AI_DETECT` / `SNAPSHOT` / `AUDIO`

新建机位时的默认绑定（`service.py:217-223`）：

| 用途 | 默认指向 |
|---|---|
| `RECORD` / `LIVE_HIGH` / `SNAPSHOT` | primary |
| `LIVE_LOW` / `AI_DETECT` | low |
| `AUDIO` | 不绑 |

**这就是为什么会报「无 RECORD 绑定」**——如果 ONVIF 探测没返回 secondary profile，或你手工把 RECORD 绑定删了，策略就无从下手。**改绑定的唯一入口是全量替换**：

```
PUT /api/v1/cameras/{id}/streams   →  replace_camera_stream_bindings   api.py:2073
                                        → CameraService.replace_bindings  service.py:508
```

没有单独的 POST/DELETE，PUT 会按 purpose 全量覆盖。切码流 = 改绑定，**不重建 profile**。

### 2.5 profile 怎么变成真的视频流

命名规则（`cameras/media_runtime.py`）：

```python
app        = "zero-nvr"                        # :62
stream     = f"profile-{profile_id.hex}"       # :87
proxy_key  = "__defaultVhost__/zero-nvr/profile-<hex32>"   # :28-32
```

拉流方式——**ZLM 主动去拉上游 RTSP**（不是我们转推）：

```text
ensure_streams()                      media_runtime.py:206
  └ is_media_online()                 :218     ← 先问 ZLM 在不在
  └ add_stream_proxy(                 :222-231
        enable_mp4=False,             ← 预览时不录
        enable_hls=True,
        retry_count=-1,               ← 无限重试，断线自动重连
        mp4_as_player=True)
```

`auto_close` 规则：绑定里含 `RECORD` 或 `AI_DETECT` 的流**常驻不自动关**（`:118-127`），其余没人看了就回收。

停止：`stop_streams()` `:391` → `close_stream(force=True)` `:404`。

### 2.6 实时预览：WebRTC + HLS 双轨

```text
GET /api/v1/cameras/{id}/live          api.py:2794
  ├ _select_live_stream()              :2816   按 source=auto|sub|main 选流
  ├ 签发 media session                 :2823   进程内 TTL 授权
  ├ ZlmMediaAccess.sign_url()          :2867
  └ 返回 { transports, hls_url, ice_servers }   :2895
```

**没有 HTTP-FLV 播放路径。** 前端选路逻辑在 `frontend/src/live/playback.ts`：

| 场景 | 优先协议 | 依据 |
|---|---|---|
| 主码流 | WebRTC | `playback.ts:152` |
| 子码流（`source_role==="sub"`） | HLS | `playback.ts:155` |
| H.265 编码 | **只能 HLS** | `playback.ts:124-130`（浏览器普遍不解 H.265） |

浏览器放不了原始编码时，才走 `cameras/live_transcode.py` 的 ffmpeg 转码兜底（app 名 `zero-nvr-compat` `:64`，FLV 推进 ZLM），带 lease 引用计数。

媒体请求都过 `backend/app/media_proxy.py` 的 `/zlm` 反代：`_ALLOWED_APPS` 只放行 3 个 app（`:15-19`），`_validated_media_path` 防路径穿越（`:40-51`），透传 Range/ETag 以支持拖动进度。

**media session 是进程内的**（`cameras/media_sessions.py:25`），**控制面重启即全部失效**（`:28-32`），前端需要重新取 URL。

### 2.7 设备时钟投影

摄像头 RTC 和服务器时间会有偏差，会直接影响录像时间轴。`cameras/clock_projection.py` 记这个偏移：

- 数据源：ONVIF `read_system_clock` + SNTP 字段（`modules/system/health.py:121-137` 解析 `STA_UNSYNC`/`offset`/`esterror`）
- 存储：**进程内 LRU**，`max_entries=4096` + 锁（`:35-38`），**不建历史表**（`:25-30` 明确注释）
- 读取：`GET /cameras/{id}/clock` → `api.py:1408`

---

## 3. 实时状态：为什么会看到「视频流未上线」

这是最近改过的部分。核心原则：**运行时状态不落库，实时问 ZLM**。

```text
ZlmRuntimeObservationService.rebuild()        runtime_observation.py:76
  └ 对每个 binding 调 get_media_list(
        app="zero-nvr", stream=f"profile-{hex}", schema="rtsp")   :97-101
      ├ 返回空  → stream_unregistered，recording_observed=False    :109-119
      └ 返回非空 → stream_registered                              :134
                   按 isRecordingMP4 判录制中                      :139-155
```

前端 `RecordingScheduleView.vue` 的 `getRuntimeStateInfo` 现在是**如实三态**，没有硬编码兜底：

| 观测结果 | 前端显示 |
|---|---|
| `recording === true` | 正在录制 |
| `stream_online === false` | 视频流未上线 |
| 流在线但 `recording === false` | 流已在线，录制器未运行 |
| 观测不到（`null`） | 无法获取状态 |

外加**优先于观测结果**的一层：`blockers`。机位不具备录制条件时（缺 RECORD 绑定、存储池未配置等），策略**照常保存**，用 `blockers` 回报原因，而不是拒绝保存。这是 `f74dc7b` / `4a31095` 两个提交修的行为。

> **设计意图**：`recording: bool | None` 里 `null` 专门表示"观测不到"，与"观测到没在录"（`false`）严格区分。混为一谈就会出现"看起来在录其实没录"。

---

## 4. 录像链：从策略到文件到时间轴

这是最复杂的一条链，分 5 段。

### 4.1 策略模型

`RecordingPolicyPut` 共 11 字段（`recordings/schemas.py:123-134`）：

| 字段 | 默认 | 作用 |
|---|---|---|
| `baseline_mode` | — | `continuous` / `schedule` / `disabled` |
| `schedule` | — | 周计划（JSON） |
| `schedule_timezone` | — | 计划时区 |
| `event_recording_enabled` | — | 事件录制开关 |
| `event_filter` | — | `{labels, zones, min_confidence}` |
| `segment_target_seconds` | 300 | 分片时长 |
| `pre_roll_seconds` | 10 | 事件前预录 |
| `post_roll_seconds` | 10 | 事件后补录 |
| `storage_target_id` | — | 存储目标 |
| `retention_policy_id` | — | 保留策略 |
| `enabled` | — | **总闸** |

`enabled` 与 `event_recording_enabled` 的关系（这是最容易混淆的一处）：

- `enabled` 是**总开关**。关掉它 → `baseline_should_record` 首行直接返回 False（`policy.py:172-173`），仲裁层直接 `mode="off"`（`arbiter.py:48-55`）
- `event_recording_enabled` 只管事件录制。**在 `enabled=true` 的前提下**，它决定 baseline 关掉时是否维持 prebuffer 录制（`arbiter.py:101-102`）

### 4.2 模式仲裁：一个需要看懂的判定树

`recordings/arbiter.py:97-104`：

```python
if baseline_active or manual_active:
    mode = "persistent"              # 持续录
elif policy.event_recording_enabled:
    mode = "prebuffer"               # 只滚动预录，等事件
else:
    mode = "off"
```

**关键细节：`event_active` 不参与 mode 判定。** 它只进 `reasons`（`arbiter.py:75-82, 92-93`）。

这意味着什么——**事件来临时并不会触发"开始录制"这个动作**。recorder 早就以 prebuffer 模式常驻在录了（5 秒一片滚动丢），事件真正的作用是让 `PrebufferPromotionService` 把已存在的预录片段**提升**成正式录像。理解这一点，§4.4 就通了。

`baseline_should_record`（`policy.py:165-208`）：continuous→True，disabled→False，schedule→按 `ZoneInfo(schedule_timezone)` 转本地时间匹配窗口。**跨午夜窗口**（`start >= end`）单独处理：当日 `>= start` 命中，或**前一日**且 `< end` 命中，归属于前一计划日（`:200-206`）。

`next_baseline_transition`（`:398-472`）只排**下一个**边界，扫未来 9 天收集候选 start/end 取最小值，含 DST 虚时间归一化（`:427-444`）。自调度：跑完用 `next_boundary` 给自己排下一次（`worker/tasks.py:949-953`）。

### 4.3 策略怎么变成 ZLM 动作

```text
RecordingRuntimeService.desired()              runtime.py:108-222
  ├ 无策略行           → None                    :133-134
  ├ 无 RECORD 绑定     → 409 recording_stream_binding_missing   :142-147
  └ max_second 分两支  :199-211
      ├ persistent → policy.segment_target_seconds    :201
      ├ prebuffer  → prebuffer_fragment_seconds(=5)   :205-207
      └ off        → 0
      ↓
zlm.start(app, stream, customized_path=target_root, max_second=...)   runtime.py:476
  → HTTP startRecord { type, vhost, app, stream, customized_path, max_second }
     integrations/zlm/adapter.py:642-661
```

**`RecorderModeTracker` 不落库**（`runtime.py:56-83`），是进程内按 `(app, stream)` 记模式。重启后的关键设计（`:449-460`）：控制面重启时 ZLM 的 recorder 还活着，所以 `known_mode is None` 时**不打断**它，返回 `assumed_existing_mode=True`。

`switch_profile()` 同理，先验证新流 online 才停旧的（`:263-275`）。

### 4.4 分片落盘与命名

ZLM 配置在 `scripts/render-zlm-config.sh` 生成：先从镜像 `cat` 出原始 `config.ini`（`:45-47`），再用 awk **定点改 13 个键**，其余原样透传（`:105`）。录像相关只改 2 处：

- `record.enableFmp4=1`（`:88-90`）→ fMP4 容器
- `on_record_mp4=<base>/record-mp4`（`:73-75`）→ hook 地址

**没改的**：`record.rootPath` 不在脚本里，`max_second` 全部经 `startRecord` API 逐流动态传入。

最终路径（ZLM FileRecorder 生成）：

```
<recordings>/record/zero-nvr/profile-<profile_id hex32>/YYYY-MM-DD/YYYY-MM-DD-HH-mm-ss-N.mp4
```

这个结构被 `reconciliation.py:296-322` **硬编码校验**：必须 5 段、`parts[0]=="record"`、`parts[1]=="zero-nvr"`，且目录日期必须等于文件名内日期，否则判 ambiguous。

**事件预录提升**（`recordings/prebuffer.py:314-341`）——这是 zero-nvr **唯一**自己搬视频字节的地方：

```text
ZLM 落盘到 tmpfs 挂载点（max_second=5s 滚动切片，延迟 GC）
  ↓ 事件发生
prepare()  按 fragments_for_camera / overlapping 取 pre-roll  :212-241
  ↓
shutil.copy2(source, partial)                     prebuffer.py:326
字节校验 copied_size != fragment.size_bytes → 删掉并 409  :327-334
replace_durably(partial, destination)            prebuffer.py:340  (fsync + rename)
  ↓
commit() 建 segment，completion_reason="PROMOTED_EVENT"  :411
```

目标已存在且尺寸相符 → 直接返回 receipt，不重复拷（`:296-312`）。「环形」不是自制 ring buffer，是**ZLM 按 max_second 滚动 + 延迟 GC**。

prebuffer 参数（`core/config/settings.py:40-42`）：`fragment_seconds=5`、`buffer_seconds=35`、`require_tmpfs=True`。挂载点启动时被强制校验 fs type 必须是 tmpfs（`prebuffer_mount.py:74-86`）+ 写探针（`:88-100`）。

### 4.5 hook 回收：ZLM 封盘 → 写库

ZLM 每次封盘广播 `kBroadcastRecordMP4`，zero-nvr 侧是 `POST /internal/hooks/zlm/record-mp4`（`internal/zlm_hooks.py:388`）：

```text
ZlmRecordMp4Hook 字段（zlm_hooks.py:78-85）
  vhost, app, stream, start_time, time_len, file_size, file_path
      ↓
按 file_path 是否在 prebuffer_root 之下分流    :410-416
  ├ 持久化分支 → RecordingCatalogService.ingest_finalized()  同步执行，session.commit()   :506-555
  │              附带 codec 探测回填                        :481-502
  └ prebuffer 分支 → 只记内存 tracker + 派发 worker 异步    :448-466
                    策略已失效的 stale fragment 直接丢弃     :439-446
```

`start_time` 是 **epoch float**，用 `fromtimestamp(..., tz=UTC)` 解析（`:396-399`），`raw_started + duration_ms = raw_ended`（`catalog.py:320-328`）。

**`ingest_finalized` 是幂等的**：同 `(storage_target_id, object_path)` 已存在且 size 一致 → `created=False`；size 不一致 → 409 `recording_location_conflict`（`catalog.py:289-318`）。

新分片先建为 `PROVISIONAL` + `HOOK_RAW`（`:351-352`），再用 `previous_segment_id` 把上一条 finalize 成 `FINAL`（`:330-336`）。这个两段式设计是为了处理「hook 乱序到达」。

### 4.6 扫盘对账：hook 漏了怎么办

hook 是**同步写库**，理论上不会漏。但 ZLM 崩溃、磁盘满、容器被杀都可能丢。所以有扫盘兜底——**是真正扫磁盘反推数据库**。

`recordings/reconciliation.py`：

```text
常量（:83-87）  recent_overlap=10min  initial_lookback=24h
               settle_seconds=30     partial_settle_seconds=90
      ↓
_identity()  path.relative_to(root)     :281-343
  ├ len(parts)==5 且 parts[0]=="record" 且 parts[1]=="zero-nvr"
  ├ 正则校验 profile-<hex> 与时间戳
  ├ 目录日期 == 文件名日期，否则 None → ambiguous
      ↓
_recover_file()  三分支                   :642-716
  ├ DB 有 + state==MISSING → 尺寸校验后改回 AVAILABLE = "relinked"   :664-701
  ├ DB 有 + 正常            → "known"                                 :702-706
  └ DB 无 → _identity 是 None → "ambiguous"                            :708-716
```

`catalog.py:51-52` 的 `expected_app="zero-nvr"` / `stream_prefix="profile-"` 是**归属声明**：不匹配的路径静默忽略（`ignore_reason="unmanaged_app"`，`:225-231`），避免扫到 ZLM 自己其他业务的录像。

### 4.7 时间轴

```text
TimelineService.build()                        timeline.py:553-612
  ├ 拉 RecordingSegment（started_at < end_at AND ended_at > start_at）  :572-576
  ├ 拉 Event
  ├ 查 policy
  └ 分桶：day→1h / hour→1min                  :415-420
  → PlaybackTimelineView { segments, recording_ranges, gaps, events }
```

**8 个 gap 原因码**（`schemas.py:19-28`），`_empty_reason` 产生前 4 个：

| 原因码 | 触发条件 | 位置 |
|---|---|---|
| `not_scheduled` | 策略缺失/未启用/schedule 窗口外/disabled 且无事件 | `timeline.py:243,246,284` |
| `no_event` | disabled+event_only 但无活跃 trigger | `:259-283` |
| `source_lost` | 证据事件 `is_source_loss`，或**前一条** segment 是 `source_lost` | `:298-333` |
| `runtime_restart` | 运行态重建造成的空洞 | `:335-342` |
| `storage_failure` / `missing_media` / `purged` / `unknown` | 另有分支 | — |

> **踩过的坑**：`reasonMap` 曾只映射 7 个码，漏了 `not_scheduled` 等，前端兜底 `replaceAll("_"," ")` 导致中文界面直接显示英文 "not scheduled"。已补齐 8 码并加守卫测试 `frontend/src/i18n.spec.ts`。

### 4.8 回放：直读盘，不经过 ZLM

```text
GET /api/v1/recordings/{id}/media            api.py:1286
  ├ 权限检查 recording.view                    :1294
  ├ 文件不存在 → 409 recording_media_missing    :1319-1321
  └ FileResponse(plan.file_path, media_type="video/mp4",
                 content_disposition_type="inline")   :1324-1329
```

**这个设计有个重要后果**：回放完全不依赖 ZLM 的 `/record/` VOD 目录（全仓零引用）。所以**在 hook 里重命名接管录像文件是安全的**——ZLM 自带的 VOD 会失效，但 zero-nvr 不用它。这正是录像重构 P1 阶段的技术前提。

### 4.9 异步任务全景

`dispatcher.py` 是**纯入队边界**（`:13-14` 注释原话），函数体内 lazy import `app.worker.tasks`（`:65-68`），保证 API 进程不因任务实现而膨胀。

| 任务 | 周期 | 位置 |
|---|---|---|
| `periodic_recording_capacity_guard` | 每 5 分钟 | `tasks.py:615-618` |
| ↳ 内部逐 camera 派发 `reconcile_camera_runtime` | — | `tasks.py:781-785` |
| `periodic_recording_catalog_reconciliation` | 每 5 分钟 | `tasks.py:1046` |
| `periodic_full_recording_catalog_reconciliation` | **每日 03:37** | `tasks.py:1056` |
| `periodic_retention_reconciliation` | 每小时 :23 | `tasks.py:1243` |
| `periodic_frigate_event_backfill` | 每 5 分钟 | `tasks.py:1364` |
| `expire_exports` / `schedule_backups` / `worker_heartbeat` | :17 / — / 每分 | `tasks.py:1407,1456,1544` |

> **常见误解**：`reconcile_camera_runtime` **不是** periodic 任务。它是 `@huey.task(retries=3, retry_delay=15)`（`tasks.py:379-380`），由容量 guard 每 5 分钟**批量派发**。"5 分钟"属于 guard，不属于它。

---

## 5. 事件链

### 5.1 三个事件源

| 源 | 入口 | source |
|---|---|---|
| ONVIF | `events/onvif.py` | `SOURCE="onvif"` `:44`，`source_instance_id=f"device:{device_id}"` `:61` |
| Frigate | MQTT + HTTP backfill | `events/frigate.py:107` / `:126` |
| 系统自产 | `events/system.py` | `SOURCE="system"`，category ∈ `source_connectivity`/`storage_health`/`runtime_health` `:30-35` |

**Frigate 是纯只读消费**：HTTP 适配器只发 GET，端点仅 `/api/version`(`:152`)、`/api/events`(`:181`)、snapshot(`:231`)。**不碰媒体管线**。

MQTT 方向：zero-nvr 是**订阅方**——paho `clean_session=False`，订阅 `{prefix}/events` qos=1（`integrations/frigate/mqtt_runtime.py:144,218`）。HTTP backfill 是持久恢复路径（`:32-36` 注释），因为 MQTT 断连期间的 MQTT 消息是丢的。

### 5.2 事件模型

`Event` 表（`events/models.py:26-103`）字段：`source` / `source_instance_id` / `source_event_id` / `camera_id` / `category` / `label` / `started_at` / `ended_at` / `confidence` / `severity` / `zone` / `snapshot_ref` / `correlation_id` / `metadata_json`。

- **幂等**：唯一索引 `(source, source_instance_id, source_event_id)`（`:29-37`），写入走 `EventService.upsert_provider_event`（`service.py:88`）
- **无 enum 约束**：`category`/`severity` 是自由字符串，枚举是**约定而非 DB 约束**
- metadata 入库前脱敏（`:106-114`）

### 5.3 事件怎么触发录像（这里有个反直觉点）

```text
Frigate MQTT 消息
  → FrigateEventIngestService._persist              events/frigate.py:45-85
  → EventService.upsert_provider_event              写 events 表
  → RecordingTriggerService.upsert_provider(        写 recording_triggers 表
        trigger_type="AI_OBJECT",
        label, confidence, zones)
  → AlertEvaluationService.evaluate_event           events/frigate.py:87-90
  → AlertEvaluationService 返回 trigger_changed
  → recording_tasks.reconcile_camera(camera_id)     mqtt_runtime.py:277-283
```

ONVIF 同构，`trigger_type="ONVIF_EVENT"`（`onvif.py:377-390`），最后 `reconcile_camera`（`onvif.py:477`）。

**`event_filter` 就在这一步被消费**——`RecordingTriggerService._event_matches`（`triggers.py:91-116`）：

```python
labels  → 精确匹配，label 不在白名单则不建 trigger
zones   → 交集非空
min_confidence → 低于阈值不建 trigger
```

调用于 `triggers.py:166-172`：**只在 `existing is None`（新事件）时判定**，已存在的 trigger 直接放行。

> ⚠️ **这里有个架构病灶**：`event_filter` 定义在**录像策略**上，但它的字段（labels/zones/min_confidence）与**告警策略的 `match_json`** 几乎完全重叠（见 §5.5）。同一件事有两套独立的过滤条件、两个独立配置入口、互不同步。这就是"事件源应该做成可插拔适配器、筛选逻辑下沉到事件源"这个重构方向的根因。

### 5.4 预录的完整生命周期

```text
持续态：ZLM 以 max_second=5s 往 tmpfs 滚动切片，35s 缓冲窗口，延迟 GC
   ↓ 事件到达（onvif.py:377 / frigate.py:45）
trigger 落库 recording_triggers
   ↓
PrebufferPromotionService.prepare()      prebuffer.py:261-356
  按 fragments_for_camera / overlapping 取 pre-roll
   ↓
copy2 + 字节校验 + replace_durably     prebuffer.py:326-340
   ↓
commit() → completion_reason="PROMOTED_EVENT"    :411
```

事件不直接调 prebuffer。是 ZLM 落盘 hook 发现文件在 `prebuffer_root` 之下，才走 prebuffer 分支派发 worker（`zlm_hooks.py:409-466`）。

### 5.5 告警：事件 → Alert

`AlertPolicy`（`alerts/models.py:25-63`）：`name` / `enabled` / `severity` / `match_json` / `action_json` / `cooldown_seconds`(0..604800)。

**匹配条件**（`alerts/service.py:622-680`）：`camera_ids`、`sources`、`categories`、`labels`、`zones`、`severities`（列表映射 `:639-652`）、`min_confidence`（`:654-660`）、`min_duration_seconds`（`:662-675`）、时间窗 `_time_match`（含 `days_of_week`/`time_start`/`time_end`/`timezone`，`:300-337`）。

**动作白名单**（`:43-51`）：`notification_target_ids` + `protect_recording` / `protect_before_seconds` / `protect_after_seconds` / `protect_expires_days`。

链路：`evaluate_event`(`:784`) → 遍历 enabled 策略 → `matches` → 冷却检查 `_cooldown_blocked`（同 policy+同 camera+`started_at` 落在 `[event.started_at-cooldown, event.started_at)`，`:682-718`）→ 幂等去重 `(policy_id, event_id)`(`:820-827`，DB 唯一约束 `alerts/models.py:69-73`) → 建 `Alert`。状态 `OPEN/ACKNOWLEDGED/RESOLVED`（`:84-87`）。

`protect_recording=true` 时按 before/after 秒数建 `RecordingProtection`（`service.py:884-936`），这就是 §6.4 的"保护不删"机制。

### 5.6 通知投递

**只有 2 种通道**：`NotificationTarget.kind IN ('apprise','smtp')`（`notifications/models.py:27-30`）。

> 一个有趣的工程细节：Apprise 适配器**旁路处理** `mqtt://`/`mqtts://`——因为 Apprise 插件依赖 paho-mqtt<2，而 Frigate 摄入用 2.x 版本冲突，所以单独用原生 paho 发布（`integrations/apprise/adapter.py:49-55`）。

`NotificationDelivery` 记录：`alert_id` / `purpose`(`alert|password_reset|security|system_test`) / `state`(`PENDING|SENDING|SENT|FAILED|SKIPPED`) / `attempt_count` / `last_error_code` / `correlation_id` 等。

**重试**：`deliver_notification` 是 `@huey.task(retries=3, retry_delay=30)`（`worker/tasks.py:1372-1373`）。投递前置 `SENDING` 且 `attempt_count += 1`（`delivery.py:186-189`），失败落 `_mark_failed`（`:205-221`）。target 缺失/禁用 → `SKIPPED` + `notification_target_unavailable`（`:105-116`）。

**escalation 未实现**——`escalat` 在整个 `backend/app` 零匹配。最接近的是 `cooldown_seconds`（抑制重复）和 `protect_recording`（保录像），都不是分级升级。spec 0014 里的 escalation 尚未落地。

---

## 6. 存储 / 保留 / 备份 / 导出

### 6.1 存储目标

`StorageTarget` 的 **DB 约束只有两种 type**：`local` / `rclone`；`role` 为 `recording` / `archive`（`storage/models.py:28-35`）。

> 注意与 ARCHITECTURE.md 的图示差异：图中画了 S3/OpenList，但**代码里 S3/OpenList 不是 StorageTarget 类型**。OpenList 是 compose 里的独立容器（§7），远端存储由 restic 后端承担。

`local_target_for_camera` 解析顺序（`storage/recording_resolver.py:28-111`）：

```text
policy.storage_target_id 指定的
  → 否则 type=local AND role=recording AND enabled 中 config.default_recording=true 的唯一项
  → 否则若候选恰好 1 个则用之
  → 否则报错
```

**6 个错误码及其触发条件**（这张表在排查问题时很实用）：

| 错误码 | 条件 | 行 |
|---|---|---|
| `recording_storage_target_missing` | 指定的 target id 查不到 | `:43-47` |
| `recording_storage_target_ambiguous` | >1 个 `default_recording` | `:66-70` |
| `recording_storage_target_unconfigured` | 解析结果 None | `:74-79` |
| `recording_storage_target_invalid` | type≠local / role≠recording / 已禁用 | `:80-89` |
| `recording_storage_path_unconfigured` | `config_json.path` 缺失或非 str | `:91-98` |
| `recording_storage_path_invalid` | 路径非绝对 | `:100-106` |

容量水位：`ensure_write_capacity`（`storage/capacity.py:220-229`）critical 时抛 507 `recording_storage_capacity_critical`；水位必须满足 `low < high < critical <= 99`（`:85-88`），否则 `storage_watermark_invalid`。

`RecordingLocation`（`storage/models.py:67-133`）记录 segment×target 的落位，state `AVAILABLE/ARCHIVING/FAILED/DELETING/DELETED/MISSING`，带 `checksum`/`verified_at`。

### 6.2 保留策略

`RetentionPolicy` 三类保留天数（`storage/retention.py:316-337`）：`ordinary_keep_days` / `event_keep_days` / `manual_keep_days`，事件类锚点用 `event_anchor`，按 priority 排序。

**两条删除保护**：

1. `_protected`（`:358-383`）：存在同 camera、时间区间与 segment 交集、且 `expires_at IS NULL OR > now` 的 `RecordingProtection` → `eligible_for_delete=False, reason="protected"`（`:545-558`）。这些保护记录由告警动作创建（`alerts/service.py:924-936`）
2. `_available_archive_exists`（`:385-410`）：rclone archive 里有 `AVAILABLE` 且 `verified_at` 非空的副本，才允许删本地

**调度**：`periodic_retention_reconciliation`（每小时 :23）→ `RetentionPlanner.actionable_plan(pressure=)`（`worker/tasks.py:1126-1230`）。**容量压力时** `reconcile_retention(False)` 被即时触发（`tasks.py:788-789`），`pressure=True` 走更激进删除。

### 6.3 备份

`BackupPolicy`（`backups/models.py:24-85`）：`repository_config_ref`→secret_records、`database_backend`、`schedule_json`、`retention_policy_json`、`verify_after_backup`、`include_deployment_config`。

**备份什么**：数据库快照 + 部署配置。**明确不备份录像**——`forbidden` 列表硬拒 `recordings_dir`/`prebuffer_dir`/`cache_dir`/`data_dir`（`backups/execution.py:164-168`）。

工具是 **restic**（`execution.py:400-408`）：

```text
ensure_repository
 → latest_snapshot_for_tag   幂等，避免重复快照   :415-419
 → backup
 → verify_snapshot + check   失败置 restic_check_failed 但快照保留   :431-437
 → forget(plan.retention)    :445-447
```

`BackupSet` 幂等键 `(backup_policy_id, schedule_slot)`，state `PENDING/RUNNING/COMPLETED/FAILED`。

### 6.4 导出（与备份的区别）

导出产物是**单个 mp4**：`{job.id}.mp4`（`exports/execution.py:112-113`），由 ffmpeg 合成（`:248-252`），`codec_mode` 决定是否重编码。

**本质区别**：

| | 备份 | 导出 |
|---|---|---|
| 面向 | 运维灾备 | 用户媒体交付 |
| 内容 | 数据库 + 配置（**不含录像**） | 录像片段 → mp4 |
| 工具 | restic | ffmpeg |
| 位置 | 远端仓库 | 本地文件 + 公网分享（`shares.py:263`） |

---

## 7. 部署形态

`docker-compose.yml`，7 个服务，5 个可选 profile：

| 服务 | 端口 | profile | 说明 |
|---|---|---|---|
| `zero-nvr` | `${ZERO_NVR_API_PORT:-8000}:8000` | 默认 | uvicorn |
| `zero-nvr-worker` | 无 | 默认 | `huey_consumer.py --workers 2` |
| `zlmediakit` | — | 默认 | 媒体层 |
| `frigate` | `127.0.0.1:8971` | `frigate` | 可选 |
| `mosquitto` | `127.0.0.1:1883` | `mqtt` | 可选 |
| `openlist` | `127.0.0.1:5244` | `openlist` | 可选 |
| `coturn` | `0.0.0.0:3478` + relay 49160-49200 | `turn` | 可选 |
| `postgres` | 无（仅网络内） | `postgres` | 可选 |

**默认只起 3 个**。依赖关系：worker → zero-nvr(healthy) → zlmediakit(healthy)。

关键环境变量（`:20-21`）：`ZERO_NVR_RECORDINGS_DIR=/recordings`、`PREBUFFER_DIR=/prebuffer`。

**启动命令**：

```bash
git pull && docker compose up -d --build
```

---

## 8. 前端

### 8.1 视图与路由

| 路径 | 视图 | 说明 |
|---|---|---|
| `/login` | `LoginView` | |
| `/setup` | `SetupView` | 首次初始化，**未完成时守卫强制跳转** |
| `/dashboard` | `DashboardView` | |
| `/live` | `LiveView` | 实时监控（默认落地页） |
| `/playback` | `PlaybackView` | 回放 |
| `/files` | `FilesView` | 文件 |
| `/events` | `EventsView` | 事件 |
| `/alerts` | `AlertsView` | 告警 |
| `/cameras` | `CamerasView` | 机位管理 |
| `/recording-schedules` | `RecordingScheduleView` | 录制计划 |
| `/storage` | `StorageView` | 存储 |
| `/system` | `SystemView` | 系统设置 |

路由守卫 `router.ts:154`：未完成 setup 一律跳 `/setup`；已登录访问 `/login` 跳 `/dashboard`。

### 8.2 API 层

`src/api/` 按域拆分 13 个文件，与后端模块基本一一对应。统一走 `client.ts`。

### 8.3 前端文件规模

前端最大的几个文件（全文 40974 行）：

| 文件 | 行数 |
|---|---|
| `views/PlaybackView.vue` | 2813 |
| `components/live/LiveCameraTile.vue` | 2591 |
| `views/StorageView.vue` | 2570 |
| `views/RecordingScheduleView.vue` | 2436 |
| `views/EventsView.vue` | 1938 |
| `views/CamerasView.vue` | 1888 |
| `components/system/SystemAccessControlPanel.vue` | 1720 |

没有极端异常值，但 2000+ 行的视图有 4 个，`LiveCameraTile.vue` 作为组件承担了较多职责（叠加/布局/状态渲染）。

---

## 9. 架构现状诊断

这部分是我在通读代码后发现的，**不是既有文档里的内容**。

### 9.1 确认健康的部分

- 媒体/元数据/状态的真相源划分清晰，没有第二个录像写入者
- 异步边界干净：`dispatcher.py` 纯入队，API 进程不执行重活
- 幂等设计到位：hook 写库、trigger 落库、告警去重、备份快照都有幂等键
- 错误码体系完备，6 个存储错误码覆盖了全部失败路径

### 9.2 明确的架构病灶

**① 事件过滤条件有两套真相源（最严重）**

`recording_policies.event_filter_json`（labels/zones/min_confidence）和 `alert_policies.match_json`（camera_ids/sources/categories/labels/zones/severities/min_confidence/min_duration/time window）语义高度重叠，字段都是 labels/zones/min_confidence，**但两套独立配置、互不同步、互不校验**。

后果：用户设了"只对 person 录像"，告警规则里还得再设一次"只对 person 告警"，两边不一致时行为不可预测。

**② `event_active` 不影响录制模式，导致语义冗余**

`arbiter.py:75-82` 算出 `event_active` 后只用于 `reasons`（`:92-93`），mode 判定（`:97-104`）完全不看它。这本身不是 bug（prebuffer 常驻是正确设计），但 `reasons` 里带着 "event" 会让人误以为模式由事件驱动。**代码注释和实际行为之间存在认知偏差。**

**③ 运行时状态与策略状态在 UI 上争夺同一块显示位**

`getRuntimeStateInfo`（blocker 优先 → 观测状态 → 兜底）这套优先级是最近三个提交才理顺的。逻辑正确但**脆弱**：新增一种状态类型时，容易忘记它在优先级链里的位置。

**④ escalation 完全未实现**

spec 0014 承诺了，代码零匹配。`alerts/` 1688 行里没有分级升级。

**⑤ 已知时区 bug（未修）**

`recordings/reconciliation.py:276` 写死 `tzinfo=UTC` 解析文件名，而 ZLM 生成的**文件名用的是本地墙钟时间**。结果：hook 路径（用 epoch `start_time`，`zlm_hooks.py:396`）正确，扫盘恢复路径**偏 8 小时**，同一时间轴上两种时间混排。

**⑥ 前端视图偏大**

4 个视图超过 2000 行（见 §8.3）。

### 9.3 建议的重构顺序

基于以上，优先级排序：

1. **先修时区 bug**（5）——数据正确性问题，且每过一天就多积累一批偏移 8 小时的元数据
2. **统一事件过滤**（1）——把过滤条件下沉到事件源，删掉 `event_filter`
3. **录像落盘命名接管**——利用 §4.8 发现的"回放不依赖 ZLM 目录"这一事实
4. **escalation**（4）——决定是补实现还是从 spec 移除

---

## 附录 A：40 张表速查

| 模块 | 表 |
|---|---|
| cameras (12) | `devices` `device_endpoints` `device_credentials` `discovery_sessions` `discovery_candidates` `cameras` `camera_stream_profiles` `camera_stream_bindings` `camera_groups` `camera_group_members` `principal_camera_scopes` `principal_camera_scope_entries` `live_view_layouts` |
| auth (8) | `users` `roles` `role_permissions` `user_roles` `user_sessions` `password_reset_tokens` `personal_api_tokens` `external_identities` `secret_records` |
| recordings (5) | `retention_policies` `recording_policies` `recording_protections` `recording_triggers` `recording_segments` |
| storage (2) | `storage_targets` `recording_locations` |
| alerts (2) | `alert_policies` `alerts` |
| events (1) | `events` |
| notifications (2) | `notification_targets` `notification_deliveries` |
| exports (2) | `exports` `export_share_tokens` |
| backups (2) | `backup_policies` `backup_sets` |
| system (1) | `system_settings` |
| audit (1) | `audit_events` |

## 附录 B：相关文档

| 文档 | 内容 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 设计态架构、真相源规则、部署拓扑 |
| [DOMAIN_MODEL.md](DOMAIN_MODEL.md) | 领域模型详解 |
| [INTEGRATIONS.md](INTEGRATIONS.md) | 外部集成 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 部署与运维 |
| [adr/](adr/) | 13 个架构决策记录 |
| [specs/](specs/) | 22 个功能规格 |
