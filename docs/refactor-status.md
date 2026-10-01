# 修复执行状态 — 按 `code-audit-report.md` 实施

对应审计：[code-audit-report.md](code-audit-report.md)（审计基线 `87d586c`）。
本文件记录**已实际落地的修复**、**刻意未做的项及原因**、以及**下一步建议**。

## 验证状态

| 检查 | 结果 |
|---|---|
| 后端 `pytest -o addopts='' -q`（backend/） | **626 passed, 4 skipped**（最新全量结果） |
| 前端 `npx vitest run`（frontend/） | **274 passed / 54 files** |
| 前端 `npx vue-tsc --noEmit` | clean |

早期变更规模快照见下方各轮记录；当前工作树继续增加了 `config_import` 分区模块、回放面板与文件管理组件。

---

## 一、非必要内容 — 已删除

| 项 | 处理 | 证据 |
|---|---|---|
| `.DS_Store` | 已删除 | 未追踪、`git check-ignore` 命中 |
| `__pycache__` ×33 + `backend/.pytest_cache` | 已删除（8.2 MB） | 可再生产；测试后自动重建且被 gitignore |
| `docs/superpowers/`（5 文件 821 LOC） | 已删除 | 全仓 0 引用；设计已落入已接受的 spec 0020 |
| `docs/zero_nvr_prototype.html` | 归档至 `docs/archive/`，并新增 `docs/archive/README.md` | 4,157 行 / 256 KB 静态原型，已被真实前端取代 |
| `docs/refactor_plan.md` | 已删除，仍有效的 backlog 迁入 `docs/ROADMAP.md` 的 **Phase 12** | 全仓 0 引用；自设门禁已被 255 次前端提交推翻 |
| `docs/plans/01-zlmediakit-media-plane.md` | 已删除（含 README 索引项） | 状态写 blocked，但冻结已完成、ZLM 已落地 1,629 LOC |
| ADR `0011` 重号 | **合并**：`0011-v1-architecture-freeze` 并入 `0012-v1-architecture-freeze-baseline`，保留全部独有内容与两条 Status | 二者为同一次冻结的两份声明；已核对独有内容（CI run、refinement 列表、Invariants 等） |
| spec `0002` 重号 | HA 那份重编号为 `docs/specs/0022-home-assistant-integration.md`，6 处引用与索引同步 | `docs/adr/` 现 0001–0012 各一次，`docs/specs/` 现 0001–0022 各一次 |

> 保留（经核验后不建议动）：`poc/`（被 2 个 CI workflow 驱动）、`scripts/` 全部 48 个脚本、`deploy.sh`、`release-manifest.json`。生成物追踪数仍为 0。

## 二、6 处已确认缺陷 — 全部修复

| # | 缺陷 | 修复 | 验证 |
|---|---|---|---|
| 1 | `status-pill--warning` / `--danger` 未定义 → 告警页状态胶囊无样式，**失败与跳过看起来一样** | 在 `frontend/src/styles.css` 用主题 `--warning`/`--danger` token 补齐两个变体 | 前端测试 + `vue-tsc` |
| 2 | FilesView / EventsView 共 6 个批量按钮只弹成功 toast、不调 API | 按你的决定**摘除按钮与桩处理函数**，只保留已实现的单条操作 | 前端测试 |
| 3 | worker 心跳用固定 `.tmp` 名且无 fsync → 并发竞争 / 掉电不持久 | 新增 `app/core/fs.py`；`write_worker_heartbeat` 改用 `atomic_write_text`（唯一临时名 + fsync + rename）。同时把 8 处原子写统一（原先 4 处缺 fsync） | `tests/test_core_fs.py`（含并发临时名唯一性、失败清理、mode、JSON 格式回归） |
| 4 | 时区归一 7 副本 / 3 套契约 / 2 个参数名；`events/system.py` 抛裸 `ValueError` → 500 | 新增 `app/core/time.py::require_utc/optional_utc`；7 处全部改为委托；`events/system.py` 现抛 `ApiError` 422 + `event_timezone_required` | 全量 pytest 绿 |
| 5 | 分页 `limit` 校验不一致；`next_cursor` 默认值在 7 个模型间漂移 | 新增 `app/core/pagination.py::normalize_page_limit`；6 个游标分页端点统一 `Query(ge=1, le=200)`；7 个 page 模型统一 `= None` | `tests/test_core_pagination.py` + 全量绿 |
| 6 | 3 个 toast 在卸载时泄漏 `setTimeout`（写入响应式状态却从不清除） | 3 处各自持有 timer handle，在 `onBeforeUnmount` 清理，并在下一次 `showToast` 时先清旧 timer | 前端测试 + `vue-tsc` |

## 三、Wave 1 纯抽取 — 已落地

### 后端（新增 6 个共享模块，均已验证）

| 模块 | 消除的重复 | 效果 |
|---|---|---|
| `app/core/pagination.py` | 游标分页 6 份副本（`*/query.py` 1,033 → 578 行，codec 逻辑零漂移） | 一份编解码 + 一份 limit 规则；修复 `next_cursor` OpenAPI 漂移 |
| `app/core/time.py` | 7 个 `_utc` / `_normalized_utc` / `_instant` 副本，3 套不兼容契约 | 严格/None 容忍两种契约 + 可传 error code |
| `app/core/fs.py` | 8 处原子写（4 处缺 fsync）+ 7 个命名路径包含副本 + 4 处 inline | 唯一临时名 + fsync + rename；`resolve_within` / `resolve_within_or_none` |
| `app/core/db/repository.py` | 25 处 get-or-404 样板（19 处 404 + 6 处 400/409/422） | 保留各调用点自己的 status/code/message |
| `app/core/http.py` | `_client_info` ×2 + `audit/service.py` 第三份 open-code | 截断长度（UA 512 / IP 64）集中一处 |
| `app/integrations/onvif/access.py` | `_read` ×3 逐字节相同 | zeep 形状兼容集中一处 |

其他后端去重：
- **`tests/factories.py`**：`make_app` / `make_database` 逐步迁移，**49 个测试文件**改为委托共享工厂，并清掉 85 个因此失效的 import。迁移脚本要求**语句序列与共享默认值逐行匹配**才改写，**23 个非规范实现被保守跳过**（保留原样）。
- **`storage/service.py`**：37 行结构双胞胎 `_ensure_default_recording_unique` / `_ensure_default_archive_unique` 合并为一个 `_ensure_default_target_unique`，两个命名包装保留（调用点不变）。
- **`system/settings.py`**：新增 `NamespaceSettingsStore`，3 个设置服务共用行加载/落库；6 处 `session.get` + 3 处 create-or-update 模板消除（`SystemSetting(` 构造从 4 处收敛到 1 处）。
- **`cli.py`**：21 处 `print(json.dumps(payload, sort_keys=True))` 收敛为 `_emit_json()`；两处几乎相同的「校验快照 → fsync → 移走 -wal/-shm → rename」收敛为 `_publish_sqlite_snapshot()`。CLI stdout 被现有测试断言，保持逐字节一致。

### 前端（Wave 1）

**本轮的编辑尝试被回退。** 我把前端 Wave 1 委派给了一个子代理执行 8 个步骤（格式化函数、toast、StatusPill、NoticeBanner、EmptyState、ConfirmDialog、composables、摘除假批量按钮）。它产出了可用的独立新文件，但**对既有文件的迁移出了问题**：编辑落在了错误位置，导致 4 个文件出现语法错误、11 个测试失败，且部分代码被拼接进了不相干的位置（例如把 `t(...)` 参数插进解构赋值中间）。

判断依据：这不是「编辑到一半」的中间态，而是跨多个文件的错位拼接；继续等待不会收敛。因此我**中断了该代理，把 `frontend/src` 整体回退到 HEAD**（同时删除它新建的未追踪文件），然后**亲自重做了其中有价值且可验证的部分**。

最终交付的前端改动（`frontend/src` 29 文件 `+738 / −1620`）：

| 项 | 文件 | 说明 |
|---|---|---|
| 缺陷 #1：补齐 `status-pill--warning` / `--danger` | `styles.css` | 这两个 class 被 `AlertsView.vue` 引用却从未定义，导致"待处理/投递失败"状态胶囊回退到灰色基础样式，**失败与跳过看起来一样**。已用主题里的 `--warning`/`--danger` token 补齐 |
| 缺陷 #2：摘除 6 个假批量按钮 | `views/FilesView.vue`、`views/EventsView.vue` | 按你的决定移除：FilesView 的 `batchExport`/`batchSyncArchive`/`batchDelete`/`batchProtect`（后者只改本地数组、刷新即丢），以及 EventsView 的 `batchProtectEvents`/`batchExportEvents`。连带移除仅供它们使用的选择状态、全选/勾选逻辑、`batch-bar` 模板、表头/行勾选列与 60+ 行相关 CSS。**保留了真正调用 API 的 `batchAcknowledgeEvents`（批量确认）**，也保留其按钮 |
| 缺陷 #6：修 3 处 toast 定时器泄漏 | `views/CamerasView.vue`、`views/FilesView.vue`、`views/RecordingScheduleView.vue` | 三处 `setTimeout` 会写入响应式状态却从不清除 → 已由 `useToast` 统一接管定时器（见下） |
| Wave 1：`utils/format.ts` 格式化函数归一 | 新增 `utils/format.ts` + `utils/format.spec.ts`（11 个测试）；迁移 `SystemView`、`DashboardView`、`AlertsView`、`System*Panel` ×3、`AccountPanel`、`StorageView` | `formatBytes` 两份**逐字节相同**已合并；`formatTime` 原先写了 **8 份**且 `Intl` option set 各不相同，现改为导出 `DATE_TIME_SECONDS` / `DATE_TIME_MINUTES` / `DATE_TIME_WITH_YEAR` / `DATE_TIME_WITH_YEAR_SECONDS` / `TIME_ONLY` 五个 preset，调用点保留同名薄包装使模板无需改动。**`StorageView` 的自适应精度版本刻意保留为独立函数** `formatBytesAdaptive`（0/1/2 位小数 + PB），因为合并它会**改变界面上显示的容量刻度**，属产品决定而非纯重构。顺带修掉一处真实缺陷：`AccountPanel.formatTime` 对空字符串会抛 `RangeError`（`Intl` 不接受 Invalid Date），共享实现改为返回 fallback |
| Wave 1：`useToast` | 新增 `composables/useToast.ts` + 4 个测试；迁移 `EventsView`、`CamerasView`、`FilesView`、`RecordingScheduleView` | 状态放在**模块作用域**而非组件内，这才是真正消除泄漏的一步：定时器写入的是模块级 ref，不再写入已卸载组件的 ref。各视图历史 dwell time（2500/3000/3200/4000ms）作为参数保留。**标记与 CSS 刻意不动**：4 个表面的定位与配色写在各自 scoped style 里（底部居中胶囊 / 右下横幅 / 右上带图标），把它们提升为一个 host 属于 CSS 迁移，需要视觉验证，留给样式归位那一步 |
| Wave 1：`useGlobalRefresh` | 新增 `composables/useGlobalRefresh.ts` + 4 个测试；迁移 **8 个视图**（Events/Alerts/Cameras/Dashboard/Storage/Live/System/Playback） | `AppShell` 派发的 `zero-nvr:refresh` 原先在 8 个视图里手写 `addEventListener`/`removeEventListener`，其中 5 个还额外写了一个只做 `void refresh()` 的纯包装函数（已删除）。**刻意不做首次加载**：多数调用方的首次拉取依赖其它状态（当前机位、路由参数），且有 3 个视图在同一个 `onMounted` 里还做别的事，把首次调用塞进来会重复请求或忽略这些条件 |
| Wave 1：`useFullscreen` | 新增 `composables/useFullscreen.ts`；迁移 `LiveView`、`PlaybackView`、`LiveCameraTile` | 三处各自实现 request/exit + `fullscreenchange` 监听。**「是否全屏」的判定做成可注入谓词**：网格与回放舞台只关心「有东西全屏」，而单个机位 tile 只关心「是不是我全屏」（`document.fullscreenElement === tile`），两者语义不同，不能假定其中一种 |
| Wave 1：`useDismissable` | 新增 `composables/useDismissable.ts` + 4 个测试；迁移 `ThemeControl`、`LanguageControl` | 这两个顶栏控件里有约 30 行逐字重复的「点外部 / 按 Esc 关闭」，现已合并。全仓只有它们有这个行为 —— 其它 popover 都没有（后续可用同一 composable 补齐） |
| Wave 1：`<NoticeBanner>` | 新增 `components/ui/NoticeBanner.vue` + 6 个测试；**迁移 22 处 banner、13 个文件** | `events-error`（8 处）与 `storage-notice`（6 处）等共 9 种 class 共用同一套 `div > UiIcon + span` 结构，图标名与尺寸每次重写（会话面板 14、页面级 15、Dashboard 16）。class 作为必需 prop 保留 —— 各表面的颜色/定位确实不同。**关键是 root 元素带调用方的 class**：Vue 会把父组件的 scope id 打到子组件根节点上，因此父视图的 scoped CSS 依然生效；这也是组件内除图标与文本外不能再有别的子节点的原因。已核实全部 banner CSS **只选中根元素**（无后代选择器），所以这次迁移不需要动 CSS |
| Wave 1：`useConfirm` + `<ConfirmDialog>` | 新增 `composables/useConfirm.ts` + `components/ui/ConfirmDialog.vue` + 6 个测试；**迁移全部 15 处 `window.confirm`（11 个文件）** | 原先的 `window.confirm` 会阻塞主线程、无法样式化/翻译，且部分浏览器会静默抑制它 —— 那样检查会**直接通过、操作未经确认就执行**。现改为 `await confirmAction({ message })`，弹窗在 `AppShell` 挂载一次。三个重要决定：**(1)** 没有 host（组件被单独测试时）回退到原生 `confirm`，而不是假定同意；**(2)** 新提示取代旧提示时，被取代的调用方 resolve `false`，绝不带着「没给出的答案」继续；**(3)** 按意图区分 —— 13 处删除/吊销/退休/轮换用 `danger` 样式，2 处（切换录制目标、应用配置导入）用普通样式，给它们套红色是错的。同时补了 `common.confirm`/`common.cancel` 两个 i18n key 与 `.button--danger` |
| Wave 1：`<StatusPill>` | 新增 `components/ui/StatusPill.vue` + 6 个测试；**迁移 11 个文件的 22 处**，并把 6 份 `statusClass`/`stateClass`/`deliveryClass` **改为返回类型化的 variant 名** | 此前每处都写 `<span class="status-pill" :class="…">`，variant 以裸字符串传递 —— 这正是 `--warning`/`--danger` 被引用却没有对应规则、却**长期无人发现**的原因：没样式的胶囊看起来像设计选择而不是 bug。现在 variant 是**封闭联合类型**，名字没有对应 CSS 规则就编译不过。`variant` 保持可选：有几处**故意**只渲染裸胶囊，给它们补上 `--muted` 会平白加上 0.7 透明度。6 份映射函数各自保留原有取值集合与兜底色调（DashboardView 的词汇比 SystemView 窄，AlertsView 未处理告警兜底是 `warning`、而投递失败才是 `danger`），只把返回类型从 class 字符串换成 variant 名 |
| Wave 1：`useAsyncResource` | 新增 `composables/useAsyncResource.ts` + 8 个测试；**迁移 17 个文件的 18 处** | `loading = true` / `error = null` / `try` / `catch` → `errorMessage` / `finally` 这套五连语句原先在 17 个组件里逐字重复，而且**漏掉 `finally` 就会让 spinner 永久卡住**。loader 采用**逐次调用传入**而非构造函数注入 —— 这正是前两次尝试失败的原因：`selectReadinessTarget(target)` 带参数、`refresh()` 在 `try` 之前先算出时间窗，把 loader 塞进构造函数会丢掉函数签名与这些局部变量。**4 处刻意保留原样**（DashboardView / FilesView / LiveCameraTile / TolerantPlaybackTile）：它们只共享 `loading`，错误处理契约并不相同（按权限聚合、catch 里重置多个状态字段、用 `failure` 而非 `error`），套用会强行改写错误语义 |
| Wave 1：`<ToastHost>` / `<EmptyState>` | 新增两个组件 + 4 个测试各；`<ToastHost>` 迁移 4 个 toast 表面，`<EmptyState>` 迁移 6 处 | 这两个我先前判为「必须等 Wave 4 的 CSS 归位」，本轮用与 `<NoticeBanner>` 相同的办法解决了：**根元素带调用方的 class、子元素通过 slot 留在调用方**。依据是我核实了这两族样式的真实形态 —— `<EmptyState>` 的规则确实**选中后代**（`.empty-state strong`、`.events-empty span`、`.unifi-empty-box strong` 等），而 scoped CSS 只能作用到子组件的根节点、到不了它内部；把子元素留在调用方后，这些后代规则依然匹配各自的视图作用域。`<ToastHost>` 同理：FilesView 的 `.toast-dot` 是**嵌套**元素，必须留在视图里才能保住 scoped 样式。**因此两者都不需要动 CSS**，原判断过于保守 |
| 文档跟进：原型路径引用 | `views/CamerasView.vue`、`layouts/AppShell.vue` | 原型归档到 `docs/archive/` 后，命名了路径的注释成了失效引用；已更正，并让 AppShell 中按行号引用原型的注释也能定位到文件 |

前端新增测试：11 个新 spec（`utils/format`、6 个 composable、`NoticeBanner`/`StatusPill`/`EmptyState`/`ToastHost`），共 **66 个新用例**；`views/FilesView.spec.ts` 中原用于验证批量选择栏的用例改为**反向断言**「不存在无后端实现的批量操作 UI」。

### 前端 Wave 2：`<DrawerDialog>`

新增 `components/ui/DrawerDialog.vue` + 6 个测试；**迁移 5 个抽屉、3 个文件**（StorageView 3 个、CameraGroupsPanel、CameraDetailPanel）。

做法上沿用了 Wave 1 验证过的原则：**组件渲染遮罩层，面板通过 slot 留给调用方**。这不是风格偏好 —— 抽屉的样式同样**选中后代**（`.unifi-drawer__header strong/span`、`.storage-editor__header strong/span`、`.storage-editor__form > label`），而 scoped CSS 到不了子组件内部；把 `aside.unifi-drawer` 留在调用方，这些规则才继续生效。渲染出的 DOM 与改动前逐字节一致。

顺带补上了原先手写抽屉**普遍缺失**的行为：Escape 关闭（且只在打开时监听，避免关着的抽屉吞掉 Escape）、可关闭遮罩点击、以及通过 `@dismiss` 把「关闭意味着什么」交回调用方（通常是清空 open 标志与编辑对象）。

**为什么没继续迁移 `system-drawer`（8 处）：** 那是一个 `position: fixed`、**无遮罩**的独立 `aside`，本身已是最小结构，套一层 `DrawerDialog` 只会多包一层 div 并可能影响布局；它们共享的只是全局样式表里的一个类名，不构成可抽取的重复结构。

### 前端 Wave 3：巨型视图拆分（进行中）

先做 `SystemView`（审计列为 3,466 行 / 12 个 tab 块）：**全部 tab 已完成拆分，视图 3,466 → 1,480 行**（−1,986）。

12 个 tab 块中，5 个（`validation`/`users`/`tokens`/`oidc`/`alerts`）本来就是单行委托，其余 **7 个已抽成独立组件**：


| tab | 原行数 | 父组件绑定数 | 结果 |
|---|---|---|---|
| `overview` | 96 | 6 | 抽成 `SystemOverviewTab.vue` + 8 个测试；其专属的 `storageHealth*` / `healthMessage` 读取器一并迁移 |
| `general` | 229 | 5 | 抽成 `SystemGeneralTab.vue` + 6 个测试（markup 由脚本逐行搬移，非手抄） |
| `ai` | 152 | 13 | 抽成 `SystemAiTab.vue` + 8 个测试；`addFrigateMapping` / `removeFrigateMapping`（只改传入数组）随 markup 迁入 |
| `time` | 332 | 15 | 抽成 `SystemTimeTab.vue` + 9 个测试；`healthDetail` 与 3 个 NTP 列表助手（`add`/`remove`/`moveTimeNtpServer`）随 markup 迁入 |
| `backup` | 656 | 33 | 抽成 `SystemBackupTab.vue` + 12 个测试 —— **这一项连 CSS 一起搬**（5 组 `backup-recovery-card*` 规则）。同时把**隐藏的 file input 连同它的 template ref 一起搬进组件**：原来输入框渲染在视图里、ref 却在视图脚本里，「校验导入」按钮要跨组件去点它；现在组件自己持有 input，只把 `File` 交给父组件。`backupPolicyName` 与 `latestBackupByPolicy`（都是对 props 的纯查询）也随 markup 迁入 |
| `notifications` | 184 | 18 | 抽成 `SystemNotificationsTab.vue` + 10 个测试；列表与编辑抽屉都在这个 tab 内，2 处内联状态赋值（`notificationPanelOpen = false`）改为 `@close-panel` 事件；顺手把手写的 enabled 芯片换成 `<StatusPill>` |
| `audit` | 129 | 11 | 抽成 `SystemAuditTab.vue` + 7 个测试 —— **这一项连 CSS 一起搬**：`audit-toolbar`/`audit-filter`/`audit-empty`/`audit-load-more` 这 9 组规则 + 1 个 media query 原本是 `SystemView` 的 scoped 规则，而它们样式化的元素全部迁入新组件，所以规则随 markup 一起移进新组件的 scoped 样式（选择器与类名不变，作用域语义不变）；`audit-list*` 本来就是全局的，留在 `styles.css` |

**关键前置发现（决定了这些拆分是否安全）：** 我先核实了 tab 用到的 78 个 class 归谁定义 —— **67 个是全局**（`styles.css`），其余是 `SystemView` 的 scoped 规则：`audit-*` 5 个（已随 `audit` tab 一起迁走）与 `backup-recovery-card*` 3 个。**判据是「规则样式化的元素迁不迁」**：元素全部迁入新组件时，规则随 markup 一起搬进新组件的 scoped 样式即可（选择器、类名、作用域语义都不变）；元素留在原地时不能搬。据此 `overview`/`general` 是「纯全局样式」，`audit` 是「连 CSS 一起搬」，三者都无需改动共享样式表。

**拆 `time` tab 时新增的 spec 抓到一个真实缺陷：** 生成的 `SystemTimeTab.vue` 用了 `<StatusPill>` 但漏了 import，而 **`vue-tsc` 没有报错**（未解析的组件在类型层面不报），是运行时 `[Vue warn]: Failed to resolve component: StatusPill` 暴露的。已修正，并补了一道静态检查：逐个 tab 比对「模板里用到的 PascalCase 标签」与「脚本里 import 的组件」，确认 5 个 tab 全部一致（`SystemAiTab`/`SystemAuditTab`/`SystemGeneralTab`/`SystemOverviewTab`/`SystemTimeTab` 均 ok）。结论：**`vue-tsc` 不能替代渲染级测试**，这类缺陷只能靠挂载测试或运行时告警发现。

**拆完后做了一次死代码清理。** 我写了个检查：对每个顶层绑定，统计它在「声明之外」的脚本引用数与模板引用数，两者都为 0 即判为死代码。第一次跑出 29 个「死」绑定，但那是检查本身的 bug —— 我用 `src.index("</template>")` 取模板，而它命中的是**第一个内层 `</template>`**（tab 的 `<template v-if>` 闭合标签），模板被截断到只剩开头。改用 `rindex` 取 SFC 的模板块后，真正的死代码是 **4 个 formatter**（`stateLabel`/`pretty`/`formatTime`/`statusVariant`）—— 正是先前「留给其它 tab 用」而保留在视图里的那几个；如今所有 tab 都拆走了，它们成了死代码，已连同 3 个只被它们使用的 import 一起删除。**清理后：SystemView 91 个顶层绑定，死代码 0；7 个 tab 组件各自的局部声明也全部有引用。**

**SystemView 现在是一个 tab 编排器**：脚本 1,283 行（所有 tab 共用的 state 与 handler），**模板仅 184 行**（原约 1,400 行），样式 58 行。脚本体积是下一层的目标 —— 那需要把每个 tab 自己的 state 一并搬进对应组件（比本轮的表现层抽取深一层）。

**新增 `composables/useSystemFormatters.ts`**：`stateLabel` / `pretty` / `formatTime` / `statusVariant` 被 5-6 个 tab 共用且都依赖 i18n，所以做成 composable 而非普通 util（普通 util 拿不到 `t`/`te`/`locale`），既避免往每个 tab 里塞 4 个 formatter prop，也避免在 7 个 tab 里各抄一份。

**剩余 tab 的实测依赖数**（供下一轮按风险排序）：`audit` 11、`ai` 13、`time` 15、`notifications` 15、`backup` **33**（657 行，最缠结）。`validation`/`users`/`tokens`/`oidc`/`alerts` 已经是单行委托，无需处理。

### 前端 Wave 4（起步）：i18n 归位 + 一处真实缺陷

**更正审计第 8 条。** 原报告称「`i18n.ts` 中约 26 处把中文句子当翻译 key 传入」，实测**不成立**：原判据的正则会把 `showToast(`中文…`)` 的结尾 `t(` 误当成 i18n 调用（`showToast` 以 `t` 结尾且紧跟 `(`）。排除标识符前缀后，真正的 ``t(`…`)`` 只剩 **2 处**，且都是**合法的动态 key**（`system.alertRules.severity.${value}`、`live.tile.errors.media.${key}`）。已在 `docs/code-audit-report.md` 第 64 行标注并追加「勘误」章节。**仍然成立的部分**是：22 处 `showToast(`中文 ${…}`)` 与约 299 处模板硬编码中文，en-US 用户确实会看到中文。

**已修复** 22 条 toast 文案 → 真 i18n key：`cameras.toast.*`(5)、`events.toast.*`(4)、新建 `files.toast.*`(10)、新建 `schedules.toast.*`(3)，en / zh 各一套。

**顺带修掉一个真实且用户可见的缺陷。** `StorageView.vue` 的保留策略表头写的是 `{{ t("storage.mode") || "清理模式" }}` —— `storage.mode` **这个 key 不存在**，而 vue-i18n 缺 key 时返回的是 **key 本身**（非空字符串），于是 `|| "清理模式"` 这个兜底**永远不会触发**，运维在表头上看到的是字面量 `storage.mode`。同一张表还有两处硬编码中文表头。三处均已修复，并补上 `storage.mode` / `storage.webdavRequired` / `storage.actions`。

**新增回归门禁 `frontend/src/i18n.spec.ts`（5 个用例）**：静态引用的 key 在 en/zh 都必须存在、en 与 zh 必须完全对齐、不存在 `t("…") || "…"` 这种死兜底、以及本轮新增 key 的双语齐备。此前这类缺陷**没有任何测试覆盖**（这也解释了 `storage.mode` 为何能长期存在）。编写时的一个约束：应用 `tsconfig` 只引入 `vite/client`（无 `@types/node`），所以 spec 不能用 `node:fs`，改用 Vite 的 `import.meta.glob(..., { query: "?raw", eager: true })` 读源码 —— 既有类型可用，也无需新增依赖。

### 前端 Wave 3 续做：`CameraOnboardingPanel`（第一个分支已抽出）

先做了一次**可拆分性筛选**，方法是统计每个视图模板里的 class「归谁定义」——全局 `styles.css` 还是该文件自己的 `<style scoped>`：

| 视图 | 模板 class 数 | 全局 | scoped | scoped 占比 |
|---|---|---|---|---|
| `CameraOnboardingPanel` | 37 | **34** | **0** | **0%** |
| `PlaybackView` | 107 | 46 | 49 | 46% |
| `CameraDetailPanel` | 54 | 1 | 42 | 78% |
| `CamerasView` | 94 | 2 | 72 | 77% |
| `FilesView` | 128 | 1 | 94 | 73% |
| `EventsView` | 109 | 2 | 102 | 94% |

**判据：scoped 占比为 0 的视图可以像 `SystemView` 那样纯表现层拆分，无需碰任何 CSS。** `CameraOnboardingPanel` 正是这种情况（37 个 class 里 34 个全局、**scoped 为 0**），且它是第二大前端组件。

> 反例说明了这个判据为什么重要：`StorageView` 的保留策略区用到 14 个 scoped class，其中 `unifi-btn` / `unifi-icon-btn` / `unifi-status-badge` 等**被同一视图的其它区块共用**。要拆这一区，就必须先把这些共用规则提升为全局样式 —— 而 scoped 规则编译后是 `.unifi-btn[data-v-x]`（特异度 0,2,0），提升后变成 `.unifi-btn`（0,1,0），**与模板里的工具类（`flex`/`text-right` 等）可能由「原本稳赢」变成「取决于源码顺序」**。这需要浏览器验证，因此 `StorageView` 的拆分排在 Wave 4 的 CSS 归位之后。

**第 6 轮抽出 `CameraOnboardingManualFlow.vue`**（132 行模板 + 6 个测试）：手动 RTSP 模式的分步表单（描述 → 码流 → 探测/创建）。表单字段用 `defineModel` 双向绑定，因此**父组件的脚本一行未改**（父组件是 8 个独立 ref，改成「传一个响应式表单对象」会牵动创建载荷的十来处代码，比这次抽取本身更大）。

**顺带修掉一个自己引入的缺陷。** 我最初在子组件里**重抄**了一份 `WorkingAction` 联合类型，结果漏掉了 `"import"`，`vue-tsc` 报 “Two different types with this name exist”。这正是重复类型的典型失败模式，所以没有就地补齐了事，而是新建 `components/cameras/onboarding.ts` 存放 `OnboardingMode` / `OnboardingWorkingAction`，父子共同 import（父侧用 `as` 别名，文件其余部分无需改动）。

**实测 `CameraOnboardingPanel` 剩余部分**：ONVIF 分支 384 行、**41 个父绑定**，大到一个组件抽不动；但可按状态簇分解为 批量导入（≈15 个绑定：`batch*`）、连接参数（≈7 个：`onvif*`）、设备发现（≈6 个：`discovery`/`useCandidate`/…）、探测与配置文件（≈7 个：`inspection`/`selectedProfiles`/…）。建议下一轮从**批量导入簇**开始。

**第 7 轮抽出 `CameraOnboardingBatchStep.vue`**（159 行模板 + 7 个测试）：批量导入簇 —— 选择发现到的设备、套用统一模板、逐设备填凭据覆盖、一次性导入。

接口设计上做了三件事，而不是照抄一份 markup：

1. **纯派生逻辑随组件迁入**：`batchCandidates`、`canBatchImport` 只依赖本步骤的输入（`discovery` + 选中的 id），`batchResultMap` 只依赖 `batchResults`，三者都搬进了子组件；父组件里那个已无人引用的 `batchResultMap` 随之删除（死代码扫描发现的）。
2. **共用函数作为回调 prop 传入**：`batchCredential`（惰性创建并写入父组件的 `batchOverrides`）、`candidateName`、`batchStateLabel` 仍被父脚本的其它部分使用（导入载荷、发现区、文件导入区），因此不搬迁，而是以函数 prop 传入 —— 避免在两边各留一份实现。
3. **把三处重复定义的类型收敛到共享模块**：`BatchResult` / `BatchResultState` / `BatchCredentialOverride` 原本声明在父组件内，`BatchTimeSyncMode` 只是内联在 `ref<...>` 里。子组件一开始按猜测写了 `"inherit" | "managed"`，`vue-tsc` 立刻报出与父组件真实联合类型（`"monitor" | "manage_ntp" | "ignore"`）不符。这正是第 6 轮那次 `WorkingAction` 漂移的同一模式，所以处理方式一致：全部移入 `components/cameras/onboarding.ts`，父子共同 import。

**`CameraOnboardingPanel`：1,881 → 1,595 行**；ONVIF 分支 384 → 246 行。剩余可拆的是**连接参数簇**（`onvif*`，约 7 个绑定）与**探测/配置文件簇**（`inspection`/`selectedProfiles`/`identity*`，约 7 个）。

**第 8 轮抽出 `CameraOnboardingDiscovery.vue`（37 行 + 6 个测试）与 `CameraOnboardingConnection.vue`（43 行 + 4 个测试）**：ONVIF 第一步里的「发现设备」与「连接参数」两个独立区块。
`discoveryStateLabel` 随发现区块迁入（它是唯一调用方）；三个异步动作（`runDiscovery`/`useCandidate`/`inspectDevice`）仍留在父组件（它们持有 `working` 标志与请求生命周期），以事件暴露；四个连接字段用 `defineModel`，父组件的 ref 原样保留。

**`CameraOnboardingPanel`：1,595 → 1,532 行**（累计 1,881 → 1,532）。

#### 一次真实事故与恢复过程（值得记录）

我在同一个脚本里连续替换两个区块：先替换发现区块，再按**替换前**记下的行号替换连接区块。发现区块由 37 行缩到 7 行，后面的行号整体前移，于是第二次替换落在了错误位置 —— 把 `<CameraOnboardingConnection />` 插进了一个 `<input>` 标签中间，并覆盖掉了 43 行（包括**第二步 `chooseProfiles` 的开头**）。

恢复方式：`git show HEAD:frontend/src/components/cameras/CameraOnboardingPanel.vue` 取出**未经改动的原始文件** —— 被破坏的那两个区块（连接参数、第二步开头）从第 6 轮起就没被改过，所以 HEAD 版本对它们而言是可信来源；按原始行号精确重建这两段后写回。

**验证这次恢复是否完整的方法**（比“测试通过”更强）：把原始文件与本轮结果里所有「步骤标题」抽出来对比。原始有 10 个步骤标题，当前父组件只剩 6 个 —— 差的 4 个恰好是 `batchOnboarding`（第 7 轮抽成 `CameraOnboardingBatchStep`）与 `describeCamera`/`configureStreams`/`verifyBeforeCreating`（第 6 轮抽成 `CameraOnboardingManualFlow`）。把父组件与两个已抽组件的标题取并集，正好 10 个、且与原始集合完全一致 —— 说明没有内容在事故中丢失。

**教训：同一批编辑中若前面的编辑会改变行数，后续编辑必须重新定位，而不能复用先前算出的行号。**（此前几轮的抽取都是「一次一区块、改完立即验证」，所以没有暴露这个问题。）

**第 9 轮抽出 `CameraOnboardingInspection.vue`（89 行 + 7 个测试）**：ONVIF 第二步 —— 设备摘要、身份冲突提示、配置文件勾选。
`profileSummary` 随组件迁入（唯一调用方）；`confirmExistingIdentity` 与 `selectedProfiles` 用 `defineModel`；`inspection` 作为 prop。父组件的 `identity` / `identityConflict` / `identityRequiresConfirmation` 三个 computed **不迁**（父组件的导入动作标签与载荷逻辑要读它们），本区块直接读 `inspection.identity`。

**`CameraOnboardingPanel`：1,527 → 1,433 行**（累计 **1,881 → 1,433**）。模板从约 750 行降到 **345 行**，只剩三个分支的骨架与 5 个子组件引用；脚本 1,083 行。

**`CameraOnboardingPanel` 的拆分进度：已抽出 5 个组件** —— 手动模式、批量导入、发现、连接参数、探测/配置文件。本轮仍用第 8 轮确立的**完整性检查**收尾：抽取后把父组件与全部子组件的「步骤标题」取并集，与原始文件对比 —— 10 个标题完全一致（missing 空、extra 空），证明没有内容丢失。

**剩余唯一内联区块**：`batch_file` 分支（178 行 / 17 个绑定：`fileBatch*` 加上与批量导入共用的 `batchGroupId`/`batchRecordingMode`/`batchStorageTargetId`/`batchTimeSyncMode` 等）。它与第 7 轮抽出的批量导入簇形状相近，可复用同一批 model，是下一轮的首选目标。

**第 10 轮抽出 `CameraOnboardingBatchFile.vue`（178 行 + 8 个测试）**：CSV 批量导入分支 —— 下载模板、选文件、审阅解析结果、执行导入。**这是 `CameraOnboardingPanel` 最后一个内联分支，至此该组件拆分完毕。**

接口处理与第 7 轮同源：`fileBatchReadyCount` / `fileBatchInvalidCount` 只依赖 `fileBatchRows`，**随组件迁入**；`canFileBatchImport` 依赖 `fileBatchCompleted` 与 `working`，且**父组件的载荷守卫要读它**，因此留在父组件并作为 prop；`batchStateLabel` 以回调 prop 传入（与批量导入步骤一致）；四个批量设置沿用 `defineModel`，与 ONVIF 批量导入步骤**共用同一组父级 ref**。文件输入框随组件迁入，父组件只收到 `File`（`handleBatchFile(event: Event)` → `handleBatchFile(file: File)`）。

**类型再次收敛到共享模块**：`FileImportKind` / `FileImportRow` / `FileBatchResult` 原本声明在父组件内，现移入 `components/cameras/onboarding.ts`。加上第 7、9 轮移入的 `Batch*` / `Onboarding*` 类型，该模块现在是这个组件族唯一的类型来源。

**`CameraOnboardingPanel`：1,433 → 1,248 行**（累计 **1,881 → 1,248**）。模板 **345 → 186 行**；脚本 1,057 行 —— 也就是说这个文件现在的形态是「共享 state + handler 的脚本」加上一个只负责编排 6 个子组件的模板。

**完整性检查（沿用第 8 轮的方法）：** 原始 10 个步骤标题 与 「父组件 + 6 个子组件」的并集**完全一致**（missing 空、extra 空）。死代码扫描发现并删除了已迁走的 `fileBatchInvalidCount`。

#### 本轮修正了一个分析工具缺陷

我用来统计「某区块引用了哪些父级符号」的脚本，一直用 `\{\{([^}]*)\}\}` 提取插值。这对 `{{ t("k", { a: x, b: y }) }}` 这种**含对象字面量**的插值会**在第一个 `}` 处截断**，从而漏掉 `fileBatchReadyCount` / `fileBatchInvalidCount` 两个符号。改成按嵌套花括号配平来提取后，符号数从 17 变成 19。此前几轮的抽取仍然成功，是因为漏掉的绑定最终由 `vue-tsc` 在接线时暴露出来；但这说明**分析脚本本身也需要验证**。

### 后端 Wave 2（起步）：为 `config_import` 补上缺失的 golden-file 测试

审计把「`config_import` 12-section 注册表拆分」列为后端最大收益项，但**前置条件是先补 golden-file 测试** —— 我核实了这一点：

- `backend/app/modules/system/config_import.py` **3,452 行**，`_FORBIDDEN_KEYS` / `_KNOWN_SECTIONS` / 4 个 dataclass / `ConfigurationImportService`；
- 拆分前它在 `tests/` 里**一次都没有被引用**（`grep -rl config_import tests/` 为空）。

**本轮新增 `backend/tests/test_configuration_import.py`（43 个用例）**，锁定 `validate()` 的既有行为：

1. **信封契约**：`format` / `format_version`（错误详情要回显版本号）/ `secrets_included` 必须显式为 `False`（缺失、`True`、字符串 `"false"` 都拒绝）；
2. **禁止字段**：遍历全部 17 个 `_FORBIDDEN_KEYS`，并断言嵌套路径以 JSON pointer 形式回传（`$.sections.general.password`、`$.sections.cameras.items[0].rtsp_url`）；
3. **区段形状**：`cameras` / `devices` 必须是对象信封（其行列表在**同名键**下，不是 `items`），其余区段是列表；未知区段会被列出；
4. **引用完整性**：断链引用要给出路径（`$.sections.recording.policies[0].camera_id`）；
5. **凭据清单**：`credentials_configured` / `url_configured` 标记产生 `rclone_config` / `apprise_url` 等凭据需求，并在 warnings 里提示「需另行提供」；
6. **版本漂移警告**与「哪些内容故意不导入」的固定文案。

**写这批测试的过程本身发现了 4 处我原本猜错的事实**（这正是 characterization test 的价值）：

- 输入键是 **`application_version`**，而它填充的 dataclass 字段叫 `source_application_version` —— 两种拼写不会互通，另一种会被**静默忽略**（已专门加一个用例把这个不对称钉住）；
- `cameras` / `devices` 的行列表键分别是 **`cameras`** 和 **`devices`**（我原本以为是 `items`），`stream_profiles` 与摄像头是**平级**而非嵌套，且每个 profile 必须回指一个摄像头；
- `storage_targets` 带 `username` **不会**产生凭据需求，真正的触发标记是 `credentials_configured: true`；
- 拒绝是按**字段名精确匹配**：`password` 被拒，但 `password_reset` 是合法的导出标记。

**后端测试：538 → 581 passed**（`validate()` 无需数据库会话，所以这批测试没有引入任何 fixture 复杂度）。

**第 12 轮：为 `apply()` 补测试，并修掉它掩盖的两个真实缺陷。**

上一轮为 `validate()` 建了 43 个用例；`apply()`（约 2,160 行，需要 DB 会话）仍无覆盖。本轮用 `tests/factories.make_test_database` 补上，并在探测其行为时发现两个**同源缺陷**：

> `validate()` 校验不足 → `apply()` 用未加保护的取值 → 畸形 bundle 让 API 返回 **500** 而不是 **400**。

**(1) 非 UUID 的资源 id**。逐个区段实测：`roles` 用任意字符串 id 是**合法**的（它按 source id 映射，不解析 UUID），但 `devices` / `cameras` / `storage_targets` / `alert_policies` / `notification_targets` / `backup_policies` 会走到 `_source_uuid()`，而 `validate()` **不会**检查 id 格式 —— 于是 `{"id": "local"}` 通过预检，随后 `apply()` 抛出**未捕获的 `ValueError: badly formed hexadecimal UUID string`**，API 侧 `except Exception: rollback; raise` 直接把它变成 500。

修法：把 `_source_uuid()` 的裸 `ValueError` 换成模块自己的 `configuration_import_invalid`（`status_code=400`）。**一处改动覆盖全部 9 个调用点**，且不必枚举「哪些区段需要 UUID」—— 避免了误伤 `roles` 这类合法接受任意 id 的区段。

**(2) `oidc_providers` 缺少 `key`**。`apply()` 用 `str(item["key"])` 匹配已存在的提供方（因为 OIDC 提供方是按 key 而非 UUID 匹配的），而 `validate()` 不要求 `key`，因此缺 key 的条目会以**未捕获的 `KeyError`** 变成 500。修法：在 `validate()` 的 oidc 分支要求 `key` 为非空字符串，并给出 JSON pointer 路径 `$.sections.oidc_providers[0].key`。

**回归测试经过了反向验证**：把 `_source_uuid()` 临时改回旧写法后，**恰好这 7 个新用例失败**（6 个参数化 + 1 个 HTTP 端到端），其余 45 个照常通过；恢复修复后 52 个全通过。这正是回归测试应有的信号。

端到端用例断言的是用户可见结果：`POST /api/v1/system/configuration/import/apply` 携带 `{"id": "local"}` 的存储目标，返回 **400** 且 `error.code == "configuration_import_invalid"`、`error.details == {"id": "local"}`（修复前是 500）。

**后端测试：581 → 590 passed。** `validate()` 与 `apply()` 现在都有覆盖，`config_import` 拆分的前置条件已经满足。

**第 13 轮：继续拆分 `config_import`。** 保持 `ConfigurationImportService.validate/apply` 对外接口不变，将 `validate()`、共享信封规则与 `apply()` 分到独立模块；公开入口 `config_import.py` 现为 19 行。再将 `apply()` 中的通用设置与时间设置、角色、设备、通知目标四组处理分别抽到 `config_import_settings.py`、`config_import_roles.py`、`config_import_devices.py`、`config_import_notifications.py`，应用主模块现为 1,764 行。角色列表在后续相机权限范围映射中仍会使用，已通过显式返回值保留这一依赖。新增 4 个导入行为用例，覆盖旧设置字段与显式时间设置合并、Frigate 手动应用、未匹配设备与端点、未匹配通知目标。后端全量 **594 passed、4 skipped**；前端 **240 passed**、typecheck 通过。

**第 14 轮：按依赖顺序完成 `config_import` 的第二层拆分。** 应用主流程现为 243 行；相机、码流、分组、角色相机权限、存储、保留与录制、OIDC、备份、告警都各有处理模块。验证主流程现为 32 行，依次调用信封/区段读取、跨区段引用校验、凭据需求与警告汇总；引用校验又分为设备、相机、录制/OIDC、Frigate/告警四组，主流程约 102 行。保持原有执行顺序、错误码和 JSON 路径；新增 7 个行为用例锁定未映射的相机、分组、录制、告警与需本地凭据的资源。`test_configuration_export.py` 的导出/导入端到端用例也通过。前端 Wave 3 从 `PlaybackView` 抽出 `PlaybackCameraPanel`（列表搜索及刷新、选择、同步事件），沿用原有全局 CSS；新增 2 个组件用例。全量结果：后端 **602 passed、4 skipped**，前端 **242 passed / 42 files**，typecheck 通过。

**第 15 轮：继续缩小录制导入与回放页。** 将 `config_import_recording.py` 的保留策略应用抽到 `config_import_retention.py`，保留策略先建立 `retention_map`、录制策略后消费的顺序不变；两个模块分别为 179 行和 234 行。导出/导入端到端用例增加保留策略目标 ID 和更新动作的断言。前端将回放诊断面板迁到 `PlaybackDiagnosticsPanel.vue`，保留父视图中的时钟与媒体状态计算，原全局 CSS 不变；补 2 个组件用例覆盖单路媒体、多路同步阻塞及关闭事件。`PlaybackView` 现为 **4,194 行**。全量结果：后端 **602 passed、4 skipped**，前端 **244 passed / 43 files**，typecheck 通过。

**第 16 轮：拆出设备匹配与回放操作面板。** `config_import_devices.py` 将 UUID、硬件 ID、手动 RTSP 端点三种匹配路径抽到 `config_import_device_matching.py`；前者现 162 行，匹配模块 121 行。新增两个导入成功用例，验证唯一硬件 ID 匹配和端点匹配后的元数据更新，同时确认原端点仍由本地保留。前端将 `PlaybackView` 的保护/导出/分享操作面板、对应 scoped CSS 一并迁到 `PlaybackActionPanel.vue`；父视图保留请求、轮询与表单状态，子组件通过 model 和事件连接，补 2 个组件用例覆盖保护区间与导出分享操作。`PlaybackView` 现为 **3,593 行**。全量结果：后端 **604 passed、4 skipped**，前端 **246 passed / 44 files**，typecheck 通过。

**第 17 轮：抽出分享编辑区与凭据需求收集。** 将 `PlaybackActionPanel` 中的分享表单、一次性链接、现有分享列表及其 scoped CSS 迁到 `PlaybackShareEditor.vue`；父面板仅传递 model 并转发关闭、保存、复制、撤销事件。两个组件现分别为 433 行和 308 行，新增 2 个分享组件用例。后端将预检中按区段收集凭据需求的逻辑迁到 `config_import_credentials.py`；`config_import_summary.py` 现为 130 行，凭据模块 129 行。新增综合用例锁定设备、码流、存储、通知、OIDC、Frigate 和备份的 9 条需求及其顺序。全量结果：后端 **605 passed、4 skipped**，前端 **248 passed / 45 files**，typecheck 通过。

**第 18 轮：细分引用校验与回放历史列表。** 将 `config_import_refs_cameras.py` 中相机组层级、成员及角色相机权限的引用校验迁到 `config_import_refs_groups.py`，仍在相机、码流和绑定校验之后执行；两个模块现分别为 147 行和 98 行。新增 3 个参数化用例，锁定错误码与 JSON 路径。前端把保护区间、导出历史列表及其 scoped CSS 迁到 `PlaybackActionHistory.vue`；`PlaybackActionPanel.vue` 缩至 299 行，新增 2 个组件用例覆盖编辑、移除、分享和下载动作。全量结果：后端 **608 passed、4 skipped**，前端 **250 passed / 46 files**，typecheck 通过。

**第 19 轮：独立导入信封校验和回放操作表单。** `config_import_document.py` 将格式、版本、密钥声明、禁用字段及未知区段的校验迁到 `config_import_envelope.py`，仍在任何区段形状读取之前执行；两个模块现分别为 235 行和 56 行。新增 5 个组合错误用例锁定校验优先级。前端将保护/导出表单及其 scoped CSS 迁到 `PlaybackActionForm.vue`，通过 6 个 model 与父面板共享输入状态；`PlaybackActionPanel.vue` 缩至 171 行，新增 2 个表单组件用例。全量结果：后端 **613 passed、4 skipped**，前端 **252 passed / 47 files**，typecheck 通过。

**第 20 轮：抽出相机元数据更新与回放顶栏。** `config_import_cameras.py` 将已匹配相机的元数据更新和变更检测迁到 `config_import_camera_metadata.py`，保留启停变化才进入录制 reconcile 的契约；两个模块现分别为 155 行和 97 行。新增用例验证首次更新及重复应用的 `matched` 与空 reconcile。前端把相机/日期弹出菜单、同步与缩放控制、操作入口及其 scoped CSS 一并迁到 `PlaybackTopBar.vue`；父视图继续持有日期、播放和导航状态，子组件只保留弹出菜单状态并发出事件。`PlaybackView` 现为 **2,955 行**，顶栏组件 713 行（其中大量为原 scoped CSS）；新增 2 个组件用例。全量结果：后端 **614 passed、4 skipped**，前端 **254 passed / 48 files**，typecheck 通过。

**第 21 轮：抽出相机匹配与回放控制栏。** `config_import_cameras.py` 将“源 UUID 优先，否则映射后的设备 ID + 频道键”匹配路径迁到 `config_import_camera_matching.py`；两个模块现分别为 129 行和 39 行。新增导入成功用例覆盖源设备和相机 ID 都与本地不同、按硬件 ID 映射设备后再按频道匹配相机的路径。前端把播放/静音/倍速、诊断开关、保护/导出入口与 codec 显示迁到 `PlaybackControls.vue`，操作状态和媒体播放处理仍由父视图持有，唯一 scoped 样式也随组件迁移。`PlaybackView` 现为 **2,838 行**，控制栏组件 169 行；新增 3 个组件用例。全量结果：后端 **615 passed、4 skipped**，前端 **257 passed / 49 files**，typecheck 和 compileall 通过。

**第 22 轮：抽出码流资料匹配。** `config_import_camera_streams.py` 将资料的源 UUID/本地相机与 adapter key 双路径匹配、必须保留本地 `stream_uri_ref` 的判定，以及源资料到本地资料的 ID 映射迁到 `config_import_stream_profiles.py`；现分别为 154 行和 103 行。新增成功用例覆盖不同源资料 ID 按相机与 key 匹配、本地流地址凭据保留、绑定首次更新和下一次请求匹配。测试按 API 实际事务边界在首次导入后提交；测试数据库的 `database.session()` 本身不会自动提交。全量结果：后端 **616 passed、4 skipped**，前端 **257 passed / 49 files**，typecheck 和 compileall 通过。

**第 23 轮：抽出码流绑定。** `config_import_camera_streams.py` 现为 39 行，只按“资料先匹配、绑定后替换”的顺序编排；绑定分组、资料映射完整性检查、`replace_bindings` 调用和 reconcile 判定迁到 `config_import_stream_bindings.py`（147 行）。新增用例证明同一相机的两个绑定中只要有一个资料未映射，两个绑定都按 `stream_profile_unmapped` 跳过，且相机配置不变。全量结果：后端 **617 passed、4 skipped**，前端 **257 passed / 49 files**，typecheck 和 compileall 通过。

**第 24 轮：抽出相机组落库。** `config_import_camera_groups.py` 保留成员/父组依赖解析、乱序多轮推进及跳过判定；源 UUID/名称匹配和 `CameraGroupService.create/update` 迁入 `config_import_camera_group_records.py`，两个模块现为 135 行和 87 行。新增成功用例验证“子组先出现、父组后出现”仍按父组先落库，再将成员映射到现有本地相机。全量结果：后端 **618 passed、4 skipped**，前端 **257 passed / 49 files**，typecheck 和 compileall 通过。

**第 25 轮：抽出录制策略应用。** `config_import_recording.py` 现为 57 行，保留“保留策略先建立 ID 映射、录制策略后消费”的编排；录制策略的相机/存储/保留映射、值转换、变更检测和 reconcile 判定迁到 `config_import_recording_policies.py`（209 行）。新增用例覆盖首次应用后的策略字段与 reconcile，以及下一次请求的 `matched` 和空 reconcile。全量结果：后端 **619 passed、4 skipped**，前端 **257 passed / 49 files**，typecheck 和 compileall 通过。

**第 26 轮：抽出告警策略依赖映射。** 将告警条件中的来源相机 ID、动作中的来源通知目标 ID 到本地 ID 的映射迁到纯函数 `config_import_alert_dependencies.py`（86 行）；保留缺任一依赖就跳过整条策略的行为。新增成功用例同时覆盖现有相机和按名称匹配的本地通知目标，确认告警策略存储的是本地 ID。全量结果：后端 **620 passed、4 skipped**，前端 **257 passed / 49 files**，typecheck 和 compileall 通过。

**第 27 轮：抽出告警策略落库。** `config_import_alerts.py` 现为 67 行，负责顺序迭代和跳过/应用结果；源 UUID、同名匹配、`AlertPolicyService.create/update` 迁到 `config_import_alert_policy_records.py`（89 行）。新增用例验证来源 ID 不同但名称相同时更新现有策略、不创建重复记录。全量结果：后端 **621 passed、4 skipped**，前端 **257 passed / 49 files**，typecheck 和 compileall 通过。

**第 28 轮：抽出文件管理月历。** `FilesView.vue` 的月历日格、月度统计、时长格式化及整段 scoped CSS 迁到 `FilesMonthCalendar.vue`；父视图仍负责真实时间线加载、换月与选日后的状态更新。`FilesView` 从 2,490 行降到 **2,154 行**，新组件 376 行（含原样式）。新增 2 个组件用例验证统计、35 格日历和事件，另补 1 个父视图集成用例验证展开、换月、选日后收起。全量结果：后端 **621 passed、4 skipped**，前端 **260 passed / 50 files**，typecheck 和 compileall 通过。

**第 29 轮：抽出文件管理表格与分页。** 将 `FilesView.vue` 的切片目录表格、空状态、分页栏及其 scoped CSS 迁到 `FilesSegmentTable.vue`，并将两组件共用的 `SegmentItem` 类型放到 `components/files/types.ts`。父视图仍负责真实数据加载、筛选、分页计算、选中状态和单条操作；子组件只渲染并转发选择、跳转回放、下载、加锁事件及当前页更新。预览播放器仍使用的 `.uf-checkbox` 样式留在父视图。`FilesView` 从 2,154 行降到 **1,844 行**，新表格组件 332 行。新增 2 个组件用例覆盖行操作不误触选择、分页更新及空状态，另补 1 个父视图集成用例验证点击行更新检视器、双击跳转回放。全量结果：后端 **637 passed、4 skipped**（相较第 28 轮增加的测试并非本轮新增），前端 **263 passed / 51 files**，typecheck、compileall 和 `git diff --check` 通过。

**第 30 轮：抽出保留策略匹配与落库。** `config_import_retention.py` 保留来源 UUID 读取、相机/相机组作用域映射、缺失依赖跳过及结果汇总；按来源 UUID → 名称 → 作用域匹配本地记录、构造值并调用保留策略服务创建/更新的逻辑迁入 `config_import_retention_records.py`。两个模块现分别为 **97 行**和 **105 行**。新增成功用例验证来源 ID 和名称都不同时，已有 `GLOBAL` 作用域仍被更新而非重复创建；临时移除作用域匹配后该用例因冲突而失败，恢复并抽取后通过。全量结果：后端 **638 passed、4 skipped**，前端 **263 passed / 51 files**，typecheck、compileall 和 `git diff --check` 通过。

**第 31 轮：抽出录制策略依赖映射。** 将来源相机、存储目标、保留策略 ID 到本地 ID 的映射及首个未映射原因迁入纯函数 `config_import_recording_dependencies.py`（39 行）；`config_import_recording_policies.py` 现为 **146 行**，继续负责值转换、写库、变更检测和 reconcile。新增跨区段成功用例验证：来源保留策略 ID 与本地 ID 不同时，导入先按作用域匹配保留策略，录制策略最终引用本地 ID；临时清空该引用后用例按预期失败。导入/导出定向用例与全量测试通过：后端 **639 passed、4 skipped**，前端 **263 passed / 51 files**，typecheck、compileall 和 `git diff --check` 通过。

**第 32 轮：抽出录制策略落库与变更检测。** 将录制策略字段转换、按相机查找已有策略、逐字段变更判断及 `RecordingPolicyService.put` 迁入 `config_import_recording_policy_records.py`（49 行）；`config_import_recording_policies.py` 现为 **69 行**，只保留依赖映射、跳过结果、reconcile 和应用结果编排。扩充既有回归用例，覆盖首次创建、重复匹配，以及已有策略字段改变后仍报告 `updated` 并触发 reconcile；临时禁用字段比较后用例按预期失败。全量结果：后端 **639 passed、4 skipped**，前端 **263 passed / 51 files**，typecheck、compileall 和 `git diff --check` 通过。

**第 33 轮：抽出文件管理片段检视器。** 将 `FilesView.vue` 的当前片段元数据、单条操作和无片段提示迁入 `FilesSegmentInspector.vue`（234 行，含 scoped CSS）；父视图保留选中状态、业务 API 和 toast，并通过事件接回回放、下载、加锁、归档及清理提示。共享于播放器与热力图的卡片/标题规则继续留在父视图，子组件为自身根节点保留同样规则，避免 scoped CSS 越界后失效。`FilesView` 从 1,844 行降到 **1,662 行**。新增 3 个组件用例覆盖详情、事件和空状态，另补 1 个父视图集成用例验证加锁仍调用录制保护 API；临时断开事件绑定后该用例按预期失败。全量结果：后端 **639 passed、4 skipped**，前端 **267 passed / 52 files**，typecheck、compileall 和 `git diff --check` 通过。

**第 34 轮：抽出 24 小时录像热力图。** 将 288 个 5 分钟槽位的计算、覆盖/告警/加锁等级展示、坐标轴、图例与对应 scoped CSS 迁到 `FilesHeatmap.vue`（298 行），并将父子组件共用的 `HeatCell` 类型放入 `components/files/types.ts`。父视图仍负责点击槽位后的最近片段选择和 toast；共享于播放器的卡片、标题及蓝点规则在热力图组件内保留同样样式，避免 scoped CSS 迁移造成视觉差异。`FilesView` 从 1,662 行降到 **1,420 行**。新增 2 个组件用例覆盖槽位等级、容量提示、活动槽位及点击事件，另补 1 个父视图集成用例验证点击后选择最近片段；临时断开事件绑定后该用例按预期失败。全量结果：后端 **639 passed、4 skipped**，前端 **270 passed / 53 files**，typecheck、compileall 和 `git diff --check` 通过。

**第 35 轮：抽出文件预览播放器。** 将视频/占位画面、浮动时码、上一段/播放/下一段控制、自动续播开关及 scoped CSS 迁到 `FilesPreviewPlayer.vue`（309 行）。子组件持有 `<video>` 引用和播放状态；父视图继续解析片段 URL、选片和显示 toast，并在每次选片时递增 `selectionToken`，使重新选中同一片段仍重置播放状态。移除了只写不读的 `videoLoading`。`FilesView` 从 1,420 行降到 **1,145 行**。新增 3 个组件用例覆盖占位播放、视频播放/暂停、导航和自动续播；另补 1 个父视图集成用例验证视频结束后选中下一段。临时断开 `next` 事件绑定后集成用例按预期失败，恢复后通过。全量结果：后端全量通过（当时双重 `-q` 隐藏了计数），前端 **274 passed / 54 files**，typecheck、compileall 和 `git diff --check` 通过。

**第 36 轮：抽出配置导入的嵌套区段读取。** 将设备、相机与录制区段内部的列表形状读取和 JSON 路径迁到 `config_import_section_groups.py`（81 行），`config_import_document.py` 从 235 行降到 **148 行**。主解析器仍按设备→相机→录制的原顺序调用；新增 3 个参数化用例，验证多个区段同时损坏时首个错误码和路径保持不变。临时交换设备和相机读取顺序后其中一个用例如预期失败，恢复后全量通过。结果：后端 **626 passed、4 skipped**，前端 **274 passed / 54 files**，typecheck、compileall 和 `git diff --check` 通过。

当前工作树复核采用 `pytest -o addopts='' -q`，明确显示 **630 collected、626 passed、4 skipped**；早期轮次保留当时记录的数字。项目配置自带 `-q`，直接再传 `-q` 会隐藏最终计数。

**前端 Wave 1 的逻辑与组件抽取已完成**：`utils/format.ts` + 6 个 composable + 5 个组件，均已落地到调用方；审计另列的死 CSS 清理仍待核对动态 class 后处理。**Wave 2 的 `<DrawerDialog>` 已落地 5 处。Wave 3 正在进行**：`SystemView` 现为 **1,480 行**，`PlaybackView` 2,838 行，`FilesView` 1,145 行。


**已评估但刻意不合并（附证据）：**
- `<StatusPill>` 的 6 份 `statusClass` 映射曾被我判为「同名不同义、不宜合并」。本轮重新评估后**改为合并，但只合并返回类型而不合并语义**：各站点保留自己接受的取值集合与兜底色调（SystemView 认 `OK/SENT/COMPLETED/VERIFIED`；AlertsView 未处理告警兜底 `warning`、投递失败才是 `danger`；ReleaseValidation 认 `PASS/FAIL/INVALID`；RecoveryKit 认 `current/stale`；DashboardView 词汇最窄），只是从「返回 `status-pill--x` 字符串」改为「返回类型化的 `StatusVariant`」。这样既保留了各视图的真实差异，又让**variant 名与 CSS 规则的对应关系由编译器保证** —— 原判断只看到了「取值集合不同」，漏掉了「返回 class 字符串本身没有类型保护」这一层。
- `<EmptyState>`（审计列为 14 处 / 5 种变体）：**已抽成组件并迁移 6 处**（`surface-class` prop + slot）。原判断是「12 个不同 class、内部结构各异，抽组件必须统一 DOM」——这一点是对的，但结论错了：**不必统一 DOM**。根节点带调用方 class、子元素留在调用方，就能同时保住「各视图自己的后代规则」与「组件化的结构复用」。剩下 8 处未迁移的各有原因，不是遗漏：只渲染单个 `<p>` 的（ReleaseValidationPanel ×2）、嵌在 `<td>` 里的 `empty-state__inner`（RecordingScheduleView）、带操作按钮的 `events-empty`（EventsView）、`inspector-card--empty` / `dashboard-empty` / `account-sessions-empty` / `recovery-kit-panel__empty` / `step-empty` / `cal-day-empty` 等 —— 它们要么结构只剩一行、组件化不会更清晰，要么含有与业务耦合的操作区。

### 前端验证结果

| 检查 | 结果 |
|---|---|
| `npx vitest run` | **54 files passed, 274 tests passed** |
| `npx vue-tsc --noEmit` | **clean（无输出，退出码 0）** |

## 四、刻意未做的项（含原因）

| 项 | 原因 |
|---|---|
| `_text` / `_string_list` 的不同契约强行统一 | `core/coerce.py::as_text` 已纯抽取宽松 `str().strip()` 契约，并由 ONVIF adapter 与 normalizer 的兜底分支复用。ONVIF 解包、Frigate/Event 的校验型文本与两套列表的错误契约仍各自保留；合并它们会改变输入处理行为。 |
| `zlm/health.py` 与 `zlm/continuity.py` 的 `_now` | 仅 2 行 × 2 处。合并需要让 `integrations/` 依赖 `core.db.types`（该包目前完全不 import `app.*`），为省 4 行引入跨层耦合不划算；且 `_now` 是可被 monkeypatch 的测试缝隙。 |
| 5 个 job 引擎抽 `JobRunner`（1,595 LOC） | 错误字段名（`last_error` / `last_error_code` / `error_code`）与终态守卫已经漂移，抽公共骨架必须先确定统一语义，属**行为变更**。建议先补 golden-file 测试再动。 |
| `integrations/base.py` 统一 9 个错误类 | 9 个 `*IntegrationError` 的默认 status code 不一致（502 / onvif 422 / 无）。统一会改变对外错误码，需要产品确认。 |
| import/export 共用 `SectionHandler` 协议 | 导入的读取、引用校验、应用已按职责拆开；导出仍使用独立投影规则。二者共享一个注册表会改变依赖顺序和调用契约，须先证明有真实重复收益，不应仅为注册表形式引入抽象。 |
| `cameras/api.py`（3,868 行 / 40 端点）、`system/api.py`、`worker/tasks.py`、`cli.py` 包化 | 纯搬家但触及面广（40+ 端点、Huey 任务注册、24 个子命令）。已在审计报告 §3.6 给出精确缝隙行号，建议逐个独立 PR。 |
| 测试的 `make_database` / `setup_admin` 剩余迁移（23 个非规范实现） | 这些实现的语句序列各不相同（含测试专用路由、额外 `app.state` 赋值、`With` 块等），机械改写会丢语句——第一次尝试正是因此破坏了 `test_app.py`。共享工厂已就位，应由各文件 owner 按需迁移。 |
| `_audit_snapshot` ×3、`_policy_view` ×3 | 复核后确认它们是**同名但不同投影**（分别针对 policy / target / job），并非重复实现，**不应合并**。 |
| `<EmptyState>` 的其余 8 处、toast 内容的视觉统一 | 已完成的部分见上（`<EmptyState>` 6 处、`<ToastHost>` 4 处，均未改 CSS）。剩余的是**视觉层面的统一**——例如把 4 个 toast 的定位配色收敛成一套、把 empty-state 的 title/hint 收敛成固定 prop。这需要改 CSS 且需要视觉验证，属 Wave 4。 |

## 五、建议的下一步（按收益/风险排序）

1. 为 `config_import` 各区段补齐成功映射的回归用例；维持导入区段的显式依赖顺序。
2. `cameras/api.py` 按子域拆 router（同模块已有 `live_preview_wall_api.py`、`live_layouts.py` 先例）。
3. 5 个 job 引擎抽 `JobRunner` —— 先统一错误字段与终态语义。
4. 前端 Wave 1 收尾：按动态 class 使用情况核对审计所列的死 CSS，再逐组删除并做视觉验证；基础逻辑和组件抽取已完成。
5. 前端 Wave 2 续做：`<DrawerDialog>` 已验证于 5 处；剩余可迁移的是 `system-drawer` 之外仍有遮罩层的抽屉，以及用它配合 Wave 3 的视图拆分。
6. 前端 Wave 3 续做：`SystemView`、`CameraOnboardingPanel` 已拆分，`PlaybackView` 的相机侧栏、诊断面板、操作面板、分享编辑区、顶栏与播放控制栏已抽出；`FilesView` 月历、表格、分页、片段检视器、热力图与预览播放器已抽出。剩余回放视频舞台与时间轴等可继续按状态边界迁移。
7. 前端 Wave 4：按视觉验证结果归位 scoped CSS，并继续迁移模板中的硬编码中文（审计所称 `t(中文)` 已证实是误报）。

## 六、本轮最终验证汇总

| 检查 | 结果 |
|---|---|
| 后端 `pytest -o addopts='' -q`（backend/） | **626 passed, 4 skipped** |
| 后端 `compileall app tests` | OK |
| 前端 `vitest run` | **274 passed / 54 files** |
| 前端 `vue-tsc --noEmit` | clean |
| 文档引用完整性 | `docs/adr/` 0001–0012、`docs/specs/` 0001–0022 各一次；无指向已删除/已重命名文件的悬空链接 |

## 七、一句话总结

审计确认的 6 处缺陷、后端共享模块与前端 Wave 1 产出已落地并通过全量测试；`config_import` 的应用和验证主流程已拆为可读的编排器，嵌套区段读取也已独立，录制/保留策略及依赖映射和落库、设备与相机匹配、相机元数据、码流资料与绑定、相机组落库、告警依赖与落库、凭据需求、相机组引用校验和信封校验也已分开。前端 Wave 3 已抽出回放相机侧栏、诊断面板、操作面板、分享编辑区、历史列表、操作表单、顶栏、播放控制栏与文件管理月历、表格、分页、片段检视器、热力图及预览播放器。其它巨型文件和 Wave 3/4 的剩余部分仍需逐步推进。

## 八、shadcn 设计语言移植（ADR 0013，2026-10-01）

对应决定：[ADR 0013](adr/0013-frontend-design-language-shadcn-port.md)。目标是用 [shadcn-admin](https://github.com/satnaing/shadcn-admin) 的设计语言替换现有 UniFi 风视觉，**不换框架**（shadcn-admin 是 React，组件层不可复用）。

### 做法

1. **token 层移植（`styles.css` 头部两个主题块整体重写）**：shadcn 默认 "neutral" 主题的 oklch token（`--background`/`--card`/`--primary`/`--muted`/`--border`/`--ring`/`--radius: 0.625rem` 等，亮暗两套）逐字移植为源，两套既有 token 族（`--surface-*`/`--text-*`/`--accent` 与 `--uf-*`）**名字全部保留、值改为派生**（如 `--accent: var(--primary)`），全部 ~750 条既有规则零改动继承新配色。shadcn 的 `--accent`（hover 灰）**刻意不定义**——与本地"主色"语义冲突，避免 23 处动作色调用点被静默重绑。效果：主按钮/动作色从蓝色变为 shadcn 单色黑（暗色近白），状态色 success/warning/danger 保持色相、重定标到 Tailwind green-600/amber-600/red-600（暗色用 500/400 系）。
2. **AppShell 重排为 shadcn-admin 侧栏模式**：264px 带标签侧栏（品牌行 + "平台/系统"分组导航 + 底部主题/语言/用户区），可折叠为 60px 图标栏并持久化到 localStorage；导航文案从硬编码中文改为 `t()`（新增 `nav.groupPlatform`/`nav.groupSystem`/`nav.sidebarCollapse`/`nav.webrtcPlaceholder`/`nav.accountManage`，en/zh 对齐）。折叠态名称提示用原生 `title`——自定义浮层会被侧栏 overflow/滚动容器裁剪。
3. **顺带修复 3 个 token 层既有缺陷**：`--shadow-sm`、`--uf-success`、`--uf-danger` 被样式规则引用却从未定义（样式静默失效），补上别名；`.system-nav__active` 硬编码 `color: #ffffff` 在暗色下变"白底白字"（主色变近白后暴露），改为 `var(--text-on-accent)`。

### 刻意不做

- 不引入 Tailwind / shadcn-vue（共享原语 `DrawerDialog`/`StatusPill` 等已是等价物，按组件逐个决定是否换）。
- 不加 Inter 字体（部署不得依赖外部字体分发），保持 system-ui 栈。
- 全局 `.sidebar`/`.primary-nav` 死代码块不动（属 Wave 4 CSS 清理）。

### 验证

| 检查 | 结果 |
|---|---|
| 前端 `npx vitest run` | **274 passed / 54 files**（含 i18n 双语对齐门禁） |
| 前端 `npx vue-tsc --noEmit` | clean |
| 浏览器实测（临时 SQLite 后端 + vite dev） | 亮/暗/折叠三态截图核对：LiveView、SystemView（含 `.system-nav__active` 修复）、CamerasView 均正常 |

## 九、审计收尾：死代码清理 + Wave 1 死 CSS（2026-10-01，第二轮）

对应审计：`code-audit-report.md` §2.3（死代码）与 Wave 1 清单最后一项"删死 CSS"（此前记为"待核对动态 class 后处理"）。前置核实：§2.1 三项删除、§2.4 六处缺陷、§3.5 后端共享模块与前端组件/composable 抽取均已落地（本轮以全量测试复核：后端 **626 passed / 4 skipped**，前端逐项 grep 确认存在且被使用）。

### 本轮实际改动

1. **删除审计 2.3 的 3 个死代码项**（审计"顺手清理"授权项）：
   - `frontend/src/api/live.ts` — `getCameraIceServers()`（全仓 0 引用；其返回类型 `CameraIceServers` 一并删除）。**注意**：`CameraIceServer`（单数）被 `CameraLiveStream.ice_servers` 使用，保留——初删时误删，`vue-tsc` 立即报错后恢复；
   - `frontend/src/playback/mediaTimebase.ts` — `mediaTimeSecondsForAbsoluteMs()`（`absoluteMediaTimeMs` 的反函数，仅自身 spec 引用）；同步删除仅覆盖它的 1 个用例与另一用例中的半段断言（**前端 274 → 273**，减少的唯一一个用例即死函数用例）；
   - `backend/app/integrations/contracts.py` — 零实现协议 `IntegrationAdapter` 及 `integrations/__init__.py` 的 re-export（其余 7 个协议均有实现方并被 `test_adapter_contracts.py` 钉住，不动）。
2. **Wave 1 收尾：死 CSS 清理（`styles.css` 5,408 → 3,884 行，−1,524）**。方法：重新计算（87d586c 后代码已大幅变化，审计的 118 类清单已过期）——
   - 从当前 `styles.css` 提取全部 371 个 class 定义，对 `src/**/*.{vue,ts}` + `index.html` 做全词字面匹配；
   - **动态构造护栏**：提取所有 `stem--` 后接 `${`/引号/`+` 的拼接片段（如 StatusPill 的 `status-pill--${variant}`），stem 命中的变体全部保留；
   - **保守删除条件**：选择器组内**全部** class 均死才删整条规则（部分死的组保留原样，另手工清理）；`@media` 内递归处理，清空则整块移除（3 个）；
   - `router-link-exact-active` 显式豁免（Vue Router 运行时注入，源码永远搜不到）。
   - 删除内容与审计判断吻合：旧 DOM 时间轴（`playback-timeline*`/`timeline-*`，已被 `PlaybackTimelineCanvas` 取代）、旧事件浏览区（`events-*`/`event-card__*`/`event-detail*`）、旧存储工作区（`storage-workspace` 族/`retention-table*`）、旧仪表盘（`metric-*`/`health-*`/`compact-list`）、旧 topbar/侧栏遗留（`topbar__*`/`primary-nav*`/`sidebar-backdrop`/`sidebar--open`）、`data-table` 族、`badge--ok/--muted`、`.text-link` 等。
3. **验证**：后端 `pytest -o addopts='' -q` **626 passed, 4 skipped**；前端 `vitest` **273 passed / 54 files**、`vue-tsc` clean；浏览器抽查 Events/Storage/Events 空态页渲染正常（HMR 热更后）。

### 本轮发现、已跟进修复的既有问题

- ~~**移动端侧栏不可恢复**~~ → **当日第二轮已修复**（用户确认采用"窄视口自动折叠"方案）：全局 `@media (max-width: 900px)` 原本对 `.sidebar` 施加 `translateX(-100%)` 且恢复类 `.sidebar--open` 全仓无代码设置，<900px 视口下侧栏滑出屏幕却仍占 264px 布局宽度（scoped 的 264px 宽度覆盖了媒体查询的 56px），内容区左侧出现大片空白。修复：(1) 删除该 off-canvas 死机制中的 sidebar/shell-main 三段规则（同块内 onboarding/form-grid 活规则保留）；(2) `AppShell` 增加 `matchMedia("(max-width: 900px)")` 监听，窄视口强制 60px 图标栏（不持久化，桌面仍用用户存储偏好），窄视口下隐藏折叠开关。验证：811px（rail 60px / 内容 x=60）、1440px（264px 展开）实测正常；`vitest` 273 passed、`vue-tsc` clean。
- `PlaybackView` 剩余内联模板仅 284 行，双 `<video>` 舞台是主时钟/漂移控制直接操纵 `videoA`/`videoB` ref 的编排核心（审计方案明确"视图只留 master-clock/传输编排"），**不再拆分**。Wave 3 前端巨型视图拆分到此收尾。

### 同日第三轮：深色对比度 + 窄视口工具栏（用户截图反馈）

**1. 深色模式"白底白字"（28 处规则修复）。** 主色改为单色后，所有"accent 实底 + 硬编码 `color: #ffffff`"的组合在暗色下（主色=近白）都变成白底白字。用脚本对全部 `.vue` scoped 样式按"所在规则块是否设置 accent/primary 背景"自动分类 54 处硬编码白字：**28 处修复**为 `var(--text-on-accent)`（StorageView 激活 tab/Add local、CamerasView 主按钮/筛选 chip/PTZ 键、PlaybackTopBar 全部激活态、EventsView chip/空态按钮、RecordingScheduleView 星期/保存钮、CameraDetail 三 tab 主按钮、Files 月历/检视器/播放器主按钮等）；**15 处刻意保留**（视频画面叠层、红/绿/琥珀实底——两种主题下白字都正确）；其余为边框/阴影不涉及对比度。每处替换以"选择器+上下文"精确匹配并断言唯一命中。

**2. 窄视口工具栏竖条（回放顶栏 + 机位页头部）。** 根因：`.playback-unifi-topbar` 固定 48px 高、左右控制组与按钮均无换行/禁止收缩约束，窄视口下按钮被压到 min-content，CJK 文本逐字换行成竖条。修复：容器与左右组改 `flex-wrap: wrap`（高度改内容驱动 `min-height: 48px` + `row-gap`），全部控件 `flex-shrink: 0` + `white-space: nowrap`——按钮保持自然宽度、在组内换行成多行，而不是被压扁。**刻意不用 `overflow-x: auto` 横向滚动方案**：顶栏内的相机/日期下拉是绝对定位弹层，滚动容器会裁剪它们。机位页 `.devices-header`/`.devices-actions` 同法加 `flex-wrap`，`.btn-action` 加 nowrap + 不收缩。

**3. 验证**：888px 窄视口暗色下回放顶栏两行整齐（标题/日期/按钮全单行文本）、机位页按钮单行、存储页激活 tab 与 Add local 白底深字清晰可读；亮色模式抽查回放顶栏正常。`vitest` **273 passed / 54 files**、`vue-tsc` clean。

### 同日第四轮：事件中心改名 + 真实事件筛选 + emoji 图标全站替换（用户反馈）

**1. 页面改名"事件中心"。** EventsView 页头、i18n `nav.events`/`route.events`（zh）与 `route.events`（en → "Event Center"）同步；dashboard 命名空间里的 `events` 短标签保持不变。

**2. 事件筛选对齐后端真实类别。** 原 8 个分类 chip 中 person/vehicle/package/animal 是 Frigate 式 AI 检测类别——后端**没有任何生产者**（`events/system.py` 只产出 `storage_health`/`source_connectivity`/`runtime_health`；ONVIF normalizer 产出 `motion`/`tamper`/`analytics` 等），属假筛选；`严重告警` chip 与已有的"级别"下拉重复。现在只保留 **全部 / 移动检测(motion) / 存储告警(storage_health) / 摄像头异常(source_connectivity/tamper/offline) / 加锁保护(metadata.protected，真实存在)**，共用 `categoryMatches()` 谓词（子串匹配容忍厂商标签漂移），计数与过滤同一实现；搜索占位词去掉同样无生产者的"车牌"。接入 Frigate 后在 `categoryMatches` 扩充即可。

**3. emoji 图标全站替换为 UiIcon/状态点。** 全站盘点 79 处符号（U+1F000-2BFF 全区段扫描，13 个文件），处置原则：
- **换成 UiIcon**（约 45 处）：EventsView 分类 chip/事件缩略图/表格徽标/空态（`activity`/`storage`/`warning`/`shield`/`search`）、CamerasView 筛选 chip 与状态徽标（`system`/`users`/`backup`/`warning` + `.status-dot--ok/--disabled`）、录制计划模式徽标（`record`/`calendar`/`activity`/`pause`）、机位详情录制 tab（时间轴图 `previous`/`focus`/`next`/`chevron-right`，手动录制 `record`/`stop`——**UiIcon 新增 `stop` 图标**）、LiveView 预案星标/弹层关闭（`star`/`close`）、文件组件（`shield`/`check`/`close`）、LanguageControl 勾选、StorageView 凭据状态/强制归档、CameraDetailPanel 播放/暂停。
- **原生 `<option>` 内直接去 emoji**（组件无法渲染）：EventsView 级别/状态/排序、FilesView 分层筛选。
- **脚本拼接的分层标签去掉 emoji**：FilesView `tierLabel`（表格按纯文本渲染）。
- **录制模式图例圆点**：CameraDetailRecordingTab 的颜色信号原先只来自 emoji 本体（`text-emerald-400` 等 tailwind 式类在本仓库无定义），新增 scoped `.mode-dot--continuous/--schedule/--events/--off`。
- **刻意保留**：PTZ 方向键的 ▲◀▶▼↗↘↙ 与 ⌂（单色排版符号，风格一致）、文本 ✕（内联 clear 标签）、SystemView "●" 状态点、dashboard 里的 ●。

**4. 验证**：`vitest` **273 passed / 54 files**、`vue-tsc` clean；浏览器实测事件中心（新标题 + 5 个真实筛选 chip 全部线条图标）、机位页 chip 图标正常；全站 emoji 残留扫描为 0（仅剩刻意的几何符号）。

### 同日第五轮：页面标题双语精简 + 语言切换诊断（用户反馈）

**1. 页头标题统一为「中文 (English)」双语短格式（8 处）**：`事件中心 (Events)`、`时光回放 (Playback)`、`录像文件 (Files)`、`录制计划 (Schedules)`、`机位管理 (Cameras)`、`存储管理 (Storage)`、`系统运维 (System)`；LiveView 无页头标题（由侧栏命名承担）、登录/初始化页为 i18n 驱动，均不动。标题为固定双语字符串——两种语言下形态一致，符合"带英文"的要求；4 个断言旧标题的 spec 已同步更新。

**2. 语言切换"失灵"的诊断结论：机制正常，覆盖不足。** 实测 `setLocale`（`legacy:false` + 全局 scope + localStorage 持久化 + `zero-nvr:locale-changed` 事件）完全生效——SystemView 等重度 i18n 页面切换即时生效。用户感知"无法切换"的根因是审计早已记录的硬编码中文问题：EventsView/FilesView/CamerasView/StorageView/PlaybackView/LiveView 的标题、按钮、筛选标签约 6,924 个硬编码中文字符不经过 i18n，切到英文后这些页面几乎无变化。本轮先把最显眼的页头改为双语固定格式；**按钮/筛选/表级文案的全量 i18n 迁移仍属 Wave 4**，需独立成批推进。诊断期间顺带修复一个真实缺陷：LanguageControl 使用 `<UiIcon>` 却缺失 import（vue-tsc 检不出未解析组件，运行时勾选标记不渲染，正是 refactor-status 第 3 节记录过的同类问题）。

**3. 验证**：`vitest` **273 passed / 54 files**、`vue-tsc` clean；浏览器实测：中文态三页新标题正常、切英文后标题保持双语且 i18n 部分正常切换；诊断后已清除测试写入的语言偏好。

### 同日第六轮：补退出登录入口（用户反馈）

AppShell 重排时 `logout()` 成了死代码——AccountPanel 只有改密码/会话管理，全站没有退出登录入口。按 shadcn-admin 的 NavUser 模式修复：侧栏底部用户行改为弹出菜单（用户名/用户名头部 + 账户设置 + 退出登录），`useDismissable` 处理点外/Esc 关闭，退出项用 danger 色调；侧栏移除 `overflow: hidden` 使折叠栏下菜单可越出 60px 栏体；新增 `nav.logout`（en "Sign out" / zh "退出登录"）。浏览器实测：菜单渲染正常、Sign out → 会话清除 → 跳转登录页；`vitest` 273 passed、`vue-tsc` clean。

### 同日第七轮：主界面 chrome 的 i18n 迁移，语言切换全面可用（用户反馈）

**诊断结论先行**：生产构建产物本身无 bug——`vite build` 后在 preview 上实测登录页 EN↔中文 一键切换正常。"部署后切换不可用"的根因是覆盖不足：SchedulesView(1,317 字)/CamerasView(854)/EventsView(528)/FilesView(1,575) 的模板硬编码中文不经过 i18n，切换后这些页面纹丝不动。

**本轮迁移（约 95 组 key，en/zh 对齐）**：四个主视图的**主界面 chrome**——
- 录制计划页：副标题、调度器状态、刷新/批量应用按钮及 title、5 张 KPI 卡、搜索占位、选中/总数计数、6 个表头、加载/空态、行内模式徽标、切片单位、配置入口；
- 机位页：副标题、4 个动作按钮及 title、7 个筛选 chip、搜索占位、排序标签与 4 个选项、显示计数、批量探测 title、空态 ×2、4 个表头、5 个行内状态徽标；
- 事件中心：头部 KPI（今日事件/待处理告警）、批量确认、5 个分类 chip、搜索占位、筛选标签与全部选项（时段/级别/状态）、重置、排序选项、视图切换 title、直方图标签与峰值、空态 ×3；
- 录像文件页：机位筛选、日期导航按钮、今天/最新录像、月历展开/收起、3 组筛选 select 全部选项、刷新 title、5 张 KPI 卡标签。

实现约束与冲突处理：events 命名空间已有 `period`（字符串）与 `severity`/`status` 旧 key，新增子块改名为 `periodFilter`/`severityFilter`/`statusFilter` 并同步模板引用，不动旧 key 的任何引用方。CamerasView/RecordingScheduleView 两个 spec 的透传 t() mock 补充中文映射表。i18n.spec 门禁自动验证新 key 的双语齐备与对齐。

**刻意保留**：各页弹窗/表单/详情 tab 的深层文案（数百条）仍属 Wave 4 后续批次；页面标题维持固定双语格式（用户明确要求带英文）。

**验证**：`vitest` **273 passed / 54 files**、`vue-tsc` clean；浏览器实测录制计划页 EN↔中文 整页 chrome 翻转（KPI/按钮/表头/空态全切换）；生产构建 preview 登录页切换正常。

### 同日第八轮：回放顶栏去重 + 移除"跳过空档"开关（用户反馈）

- **重复按钮**：顶栏的 加锁保护/剪辑导出 与底部控制栏的 保护/导出 完全重复（同样经 `openActionPanel` 打开操作面板）。删除顶栏两个按钮及 `open-action` 契约；底部控制栏为唯一入口（含权限门控 can-protect/can-export）。
- **跳过空档开关**：作用是"落进录像空档时自动向前寻位继续播放"，默认关闭，且空档界面本就提供 上一段/下一段 手动跳转——开关冗余，整条链路移除：顶栏按钮、`skipGaps` 状态、单机位 resolve 的自动跳转分支、诊断面板的 skip-gaps 展示行、`playback.skipGaps*` i18n key。**刻意保留** `findSkipGapTarget` + `skipSynchronizedGap`：多机位同步播放的跳空档是无条件行为（有自己的 multiCameraMode+playing 守卫，不受被删开关控制），属真实功能。
- 验证：`vitest` **273 passed / 54 files**、`vue-tsc` clean；浏览器实测 1366px 下顶栏单行排布（时光回放 | 机位 | 面板 | 日期 | 容错/严格 | 管理当前文件 | 缩放 | 全屏）。

### 剩余 backlog（按审计顺序，需独立成项）

`cameras/api.py`（3,868 行/40 端点）拆 router、`core/jobs/runner.py`（先统一 5 个 job 引擎的错误字段/终态语义并补 golden 测试）、`system/api.py`/`worker/tasks.py`/`cli.py` 包化、Wave 4 scoped CSS 归位与模板硬编码中文迁移、`RecordingWindowsEditor` 双实现合并（含魔法字符串/星期顺序漂移的产品决策）。
