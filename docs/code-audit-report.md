# zero-nvr 代码审计报告 — 非必要内容与可抽取组件

- 审计对象：`zero-nvr` @ `87d586c`（工作树干净）
- 规模：backend/app 67,561 LOC（198 模块）· backend/tests 43,572 LOC（114 文件）· frontend/src 41,183 LOC（36 个 `.vue`）· styles.css 5,259 行 · scripts 8,406 LOC · docs 25,683 LOC
- 方法：`git ls-files` / `du` 定量，AST 重复函数检测 + `difflib` 相似度聚类，全仓 anchored grep 验证引用关系；**所有 line number 均已实读复核**，结论标注置信度
- 详细附录：[前端重构审计](frontend-refactor-audit.md) · [后端重复与抽取审计](refactor-duplication-audit.md)

---

## 一、结论速览

整体判断：**这不是一个"烂代码"仓库**。后端有完整的 `core/` 分层、`integrations/contracts.py` 协议层、50 个模型统一用 `UUIDPrimaryKeyMixin`/`TimestampMixin`、误差处理内建脱敏；仓库卫生良好 —— **没有任何生成物被提交**（`__pycache__`/`.venv`/`node_modules`/`dist` 追踪数均为 0），没有注释掉的死代码块，没有一个未被引用的脚本，也没有一个真正无人调用的后端私有函数。

真正的问题只有两类：

1. **重复实现**（同一个东西写了 3~6 遍，且已经漂移出不一致行为）；
2. **巨型文件/方法**（单文件 2000~4500 行、单方法 2159 行），导致重复无处安放。

其中 **6 处已经不只是"重复"，而是可复现的缺陷**（见 2.4），建议优先处理。

| 维度 | 数量级 |
|---|---|
| 可立即删除（零风险） | `.DS_Store` + `__pycache__` 8.0 MB + `docs/superpowers/` 821 LOC |
| 死代码 / 假实现 | 2 个前端死导出、1 个零实现协议、6 个"只弹 toast 不调 API"的批量按钮 |
| 已确认缺陷 | 6 处 |
| 后端重复实现重复量 | ~6,000+ LOC |
| 前端重复实现重复量 | ~5,500+ LOC（含 10,744 行组件内 scoped CSS 中的重复） |
| 建议新增的组件 | 前端 10 个组件 + 6 个 composable + 1 个 utils 层；后端 8 个共享模块 |

---

## 二、非必要的东西

### 2.1 可立即删除（零风险，已逐条验证）

| # | 路径 | 体量 | 证据 | 置信度 |
|---|---|---|---|---|
| 1 | `.DS_Store` | 6 KB | 未被追踪、`git check-ignore` 命中、全仓 0 引用 | **确定** |
| 2 | `__pycache__` ×33 + `backend/.pytest_cache` | 8.0 MB + 132 KB | 未被追踪、可再生产 | **确定** |
| 3 | `docs/superpowers/`（5 文件） | 821 LOC / 48 KB | **全仓 0 引用**（`grep -rn superpowers` 除自身外无命中），不在 `docs/README.md` 索引内；其中 3 篇的产物已实现（`live_preview_wall.py`、`live_preview.py`、`GET /recordings/{id}/media`），设计决策已写入**已接受**的 `docs/specs/0020-live-view-media-session.md`（L131–160）；每篇开头都是"**For agentic workers:** REQUIRED SUB-SKILL"，属 agent 工具链副产物 | **高** |

> 说明：`backend/.venv`（149 MB）、`frontend/node_modules`（158 MB）、`frontend/dist`（1.5 MB）**并未被提交**，只是本地开发产物，可留可删，不属于仓库问题。

### 2.2 文档类：需 owner 确认（不做断言，供决策）

| 路径 | 体量 | 问题 | 建议 | 风险 |
|---|---|---|---|---|
| `docs/zero_nvr_prototype.html` | 4,157 LOC / 260 KB，**仓库最大单文件** | 已被真实前端取代；仅 3 处引用：`frontend/src/views/CamerasView.vue:5` 注释、`docs/refactor_plan.md:206,209`、`frontend/src/layouts/AppShell.vue:19,21,87`（按行号引用） | **归档**（如 `docs/archive/`），不硬删；若删除须同步清理 3 处代码注释 | 3 处注释指向它 |
| `docs/refactor_plan.md` | 217 LOC | **全仓 0 引用**，不在索引内；其自设门禁"绝不改动任何 `frontend/src/` 生产代码"已被 **255 次 frontend 提交**推翻；其中 PTZ/预置位等章节前端并无对应实现（`find frontend/src -iname '*ptz*'` 为空），属"愿望清单+已过期"混合体 | 把仍然有效的 backlog 迁入 `docs/ROADMAP.md`，然后删除 | owner 可能视其为活跃 UI 规划（中文、日期与 HEAD 同日） |
| `docs/plans/01-zlmediakit-media-plane.md` | 186 LOC | 状态写"blocked on design-freeze POCs"，但 `docs/plans/01-design-freeze-poc.md` 已 completed、ADR 0011/0012 与 0002 已 accepted，且 `backend/app/integrations/zlm/` 已落地 1,629 LOC + compose 服务 | 删除或更新状态 | 仅 `docs/README.md` 引用 |
| ADR `0011` 编号冲突 | ~386 LOC | `0011-v1-architecture-freeze.md` 与 `0011-zlm-recording-time-normalization.md` 同号；且 `0011-v1-architecture-freeze` 与 `0012-v1-architecture-freeze-baseline` 是**两个 ADR 声明同一次冻结**（同一 CI run `35490737812` / SHA `20ae474`）。另 `docs/specs/0002` 同为两个文件（event-recording-lifecycle 与 home-assistant-integration，后者属 V1.1 非阻塞且无代码） | 重新编号 + 修 6 处链接 + 补索引（`0011-v1-architecture-freeze` 被 6 个文件引用却不在索引里） | ADR 是已接受记录，链接面广 |

### 2.3 死代码 / 未接线代码 / 假实现

| # | 位置 | 性质 | 证据 |
|---|---|---|---|
| 1 | `frontend/src/api/live.ts:140 getCameraIceServers()` | **完全死代码**：全仓 0 引用（含测试）。它调用的 `GET /cameras/{id}/live/ice` 后端存在且有测试，但前端 ICE 配置实际来自流描述符 —— `LiveCameraTile.vue:1331` 用的是 `stream.ice_servers`。属"旧方案残留" | grep 全仓仅定义处 1 命中 |
| 2 | `frontend/src/playback/mediaTimebase.ts:12 mediaTimeSecondsForAbsoluteMs()` | **生产死代码**：只有它自己的 spec 引用，产品代码 0 使用 | `grep -rn` 仅 `mediaTimebase.spec.ts` |
| 3 | `backend/app/integrations/contracts.py:304 IntegrationAdapter` | **零实现协议**：`capabilities/enable/disable/status` 声明后，**没有任何适配器实现它**，仅在 `integrations/__init__.py` 被 re-export。同文件其余 7 个协议（`DeviceAdapter`、`MediaPlane`、`StorageBackend` …）都有实现方并被 `test_adapter_contracts.py` 钉住，唯独这个没有 | `grep -rn IntegrationAdapter app` = 仅定义 + `__init__` 导出 |
| 4 | `FilesView.vue:875-893` 四个批量按钮 | **假实现（会骗用户）**：`batchProtect` 只改本地 `segments.value`（刷新即丢），`batchExport`/`batchSyncArchive`/`batchDelete` **只调 `showToast()` 弹成功提示，完全不调 API** —— 却告诉用户"后端正在打包""已加入远端归档队列" | `grep -rn batch frontend/src/api/` 与 `grep -rn batch backend/app/modules/*/api.py` **均为 0**，后端根本不存在批量端点 |
| 5 | `EventsView.vue:359-365` `batchProtectEvents` / `batchExportEvents` | 同上，纯 toast 桩（"批量加锁已启动""已提交至导出队列"） | 同上 |
| 6 | `frontend/src/router.ts:104-111` | `/schedules`、`/schedule` 两个纯 redirect 遗留路由，全仓无任何 `to=`/`push()` 指向 | 仅 8 行，建议保留以兼容书签，属最低优先级 |
| 7 | `frontend/src/styles.css` 118 个全局 class | **死 CSS**：353 个顶层全局 class 中 118 个（33%）在全部 `.vue`/`.ts` 中 0 命中，约 **738 行**（如 `data-table`、`events-feed`、`event-card__*` 全套、`health-grid`、`compact-list`、`app-shell--collapsed`）。注：`event-card*` 疑似为已删除的旧 Events 视图遗留 | 逐类 grep 验证为 0 命中 |
| 8 | ~~`i18n.ts` 中约 26 处 `t(中文句子)`~~ **该条不成立，见文末勘误** | **误报**：全仓没有任何把中文句子当 key 的 `t()` 调用。原判据的正则会把 `showToast(`中文…`)` 的结尾 `t(` 误当成 i18n 调用 —— `showToast` 以字母 `t` 结尾且紧跟 `(`。排除标识符前缀后，真正的 ``t(`…`)`` 只剩 2 处，且都是**合法的动态 key**（`system.alertRules.severity.${value}`、`live.tile.errors.media.${key}`）。**仍然成立的部分**：22 处 `showToast(`中文 ${…}`)`（`FilesView` 10、`CamerasView` 5、`EventsView` 4、`RecordingScheduleView` 3）与模板里约 299 处硬编码中文 —— en-US 用户确实会看到中文。**第 4 轮已把这 22 条 toast 全部迁入真 key**，并顺带修掉一处真实缺陷（详见勘误） |

### 2.4 顺带发现的真实缺陷（比"非必要"更值得先修）

1. **`status-pill--warning` / `status-pill--danger` 从未定义**
   `AlertsView.vue:140,145,147` 返回这两个 class，但全局 `styles.css` 只定义了 `.status-pill--ok`(:3707)、`--muted`(:3713)、`--error`(:4394)；scope 内也没有。
   → **告警页的"未处理/失败"状态胶囊当前没有任何样式**。（`status-pill` 全仓 113 处使用 / 16 个文件）

2. **6 个"成功提示"是假的**（见 2.3 #4/#5）。这比死代码更严重：UI 在向用户撒谎，且 `batchProtect` 的本地状态变更会静默丢失。

3. **worker 心跳写入存在并发竞争 + 掉电不持久**
   `backend/app/modules/system/health.py:873 write_worker_heartbeat()`：`temporary = path.with_suffix(".tmp")` 是**固定文件名**，且 `write_text` 后直接 `os.replace`，**没有 `fsync`**。并发调用会互相覆写同一个 `.tmp`。
   → 全仓 8 处原子写中 **4 处缺 fsync**（另有 `camera_acceptance.py:82`、`recovery_kit.py:434`、`:755`），durability 语义不一致。

4. **时区归一化 7 个副本、3 套不兼容契约、2 个不同参数名**
   - `_utc` ×3：`exports/api.py:47`（参数名 `field`，naive 值抛 422）、`recordings/protection.py:20`（参数名 **`field_name`**，抛 422）、`audit/api.py:25`（**None 容忍**，返回 None）
   - `_instant` ×2：`events/service.py:44`（抛 `ApiError` 422）、`events/system.py:37`（抛**裸 `ValueError`**）
   - `_normalized_utc` ×2：`recordings/api.py:79`、`events/api.py:36`
   → `events/system.py:37` 的 `ValueError` 经 `internal/zlm_hooks.py:162,296,311` 暴露在 `/internal/hooks` 上，遇到 naive 时间戳会落到通用 handler 变成 **500**，而非同类问题的 422；`field` vs `field_name` 的漂移意味着无法互相替换。

5. **`recordings/api.py:1060` 的分页参数未校验**
   `limit: int = 100`，而 6 个兄弟模块都用 `limit: int = Query(default=..., ge=1, le=200)`；同时 `next_cursor` 的默认值在 7 个分页模型间漂移（4 个 `= None`，3 个无默认），导致 OpenAPI required 标记不一致。

6. **3 个 toast 在卸载时泄漏定时器**
   `CamerasView.vue:88-95`（unmount 490-493 未清理）、`FilesView.vue:465-472`、`RecordingScheduleView.vue:105-110` 都在 `setTimeout` 里回写响应式状态却不清理；只有 `EventsView.vue:68-75` 有 `clearTimeout`。

> 另记一处**不是缺陷、但易被误判**的点：`.form-error` 在 `styles.css:864` 与 `:1063` 出现两次。我已核对——两块设置的属性（边框/底色/前景色 vs 内外边距/圆角/字号）互不冲突，级联后是互补的，**不是样式冲突**，只是声明分散在同一文件两处，随组件化自然消解。

### 2.5 明确"不要动"的部分（审计为干净 / 有 CI 绑定）

避免误伤，以下经证据核验后**建议保留**：

- **`poc/`（38 文件 / 7,945 LOC）** —— 不是死代码：`.github/workflows/poc-runtime.yml` 会跑 `poc/run-design-freeze.sh`（matrix 01/02/03/05/07/09/10），`poc-static.yml` 在每次 `poc/**` 变更时 compileall + `sh -n` + `docker compose config -q`，并被约 10 份文档与 README 引用。`docs/plans/01-design-freeze-poc.md` 明确要求"*Keep them executable as regression gates*"。若迁出需同时删 2 个 workflow + 改 ~10 份文档，换 316 KB —— 不建议。仅当 owner 宣布设计冻结永久关闭时才考虑。
- **`scripts/` 全部 48 个脚本** —— 0 个未被引用（`deploy.sh` 派发 20 个，`deployment.yml` 跑 22 个）；14 个 `test-*.sh` + 3 个 `test_*.py` 是 CI 回归面，属"薄封装"设计而非死代码。
- **`deploy.sh`（1,215 LOC）与 `release-manifest.json`** —— 前者是 ADR 0005 指定的宿主变更唯一权威，source 6 个 `scripts/*.sh` 后派发 20 个子命令，**没有**重复实现 restic/rclone/pg_dump；后者由 `scripts/release-manifest.sh:8` 作为输入，交叉校验 `backend/pyproject.toml` + `frontend/package.json` + alembic head，是机器校验的单一真源。
- **仓库卫生本身** —— 生成物追踪数 0，`.gitignore` 覆盖完整，无注释掉的代码块，无重复文件，无真正的孤儿后端模块（`media_proxy.py`/`frontend.py`/`worker/consumer.py`/`recovery_kit_cli.py` 均被 `main.py`/compose/scripts 引用，非孤儿）。
- **后端 `models/` 层与 `core/db/mixins.py`** —— 50 个模型类统一复用 mixin，是**全仓唯一没有重复发现的层**。

---

## 三、可以抽成组件的

### 3.1 前端基础 UI 组件（同一原语被写了 3~6 遍）

| 优先级 | 建议组件 | 现状（重复量） | 关键证据 |
|---|---|---|---|
| ★★★★★ | `<DrawerDialog>` 抽屉/弹窗外壳 | **3,460 LOC 分布在 12 个文件** | `.storage-editor__header` ×11、`__actions` ×12、`class="system-drawer"` ×10；**6 种 backdrop class 名**；**6 种关闭按钮**（`UiIcon name="close"` ×19 vs 字面量 `✕`：`EventsView.vue:659,871`、`CamerasView.vue:834`、`LiveView.vue:1000,1065,1166`、`PlaybackView.vue:2803`）。建议 API：`props {open,title,subtitle,variant:'drawer'\|'centered'\|'modal',width,closeOnBackdrop,closeOnEscape,busy}` + `emit close` + slots `default/header-actions/footer` |
| ★★★★★ | `<NoticeBanner>` 提示条 | **21 个 error + 6 个 success，9 种 class 名** | 同一形状 `<div v-if="error" class="X"><UiIcon name="warning"/><span>{{error}}</span></div>` 散落 18 个文件（`SystemView.vue:1473`、`DashboardView.vue:307`、`StorageView.vue:802`、`RecordingScheduleView.vue:646`、`LoginView.vue:192,254,311` …）。**铁证**：`styles.css:3126` 的 `.events-error` 与 `:3536` 的 `.storage-notice` 除两个颜色 token 外**逐字节相同**；19 个 inline `warning` 图标 + 12 个 `check` 图标只为装饰它 |
| ★★★★ | `<StatusPill>` + `statusClass()` | **113 处使用 / 16 文件 / 6 份映射函数** | `SystemView.vue:474`、`SystemSecretStorePanel.vue:23`、`SystemReleaseValidationPanel.vue:81`、`SystemRecoveryKitPanel.vue:37`、`AlertsView.vue:137` + 2 处 inline 三元。**已漂移**：`DashboardView.vue:264` 少了 `SENT`/`VERIFIED` 两个取值（对比 `SystemView.vue:474`）。修掉 2.4 #1 的载体 |
| ★★★★ | `useToast()` + `<ToastHost>` | **5 套并存** | `EventsView.vue` `.toast-popup`、`CamerasView.vue` `.toast-banner`、`FilesView.vue` `.toast-notification`+`.toast-dot`、`RecordingScheduleView.vue` `.schedule-toast`、`SystemView`/`StorageView` 的 `notice` + `.unifi-banner--success`。**89 行近似重复 CSS**、4 种时长（2500/3000/3200/4000ms）、3 处泄漏定时器 |
| ★★★★ | `<CameraListPanel>` + `<CameraListRow>` | **约 415 LOC** | 行标记手写 5 遍：`LiveView.vue:863-921`、`PlaybackView.vue:2611-2684`、`DashboardView.vue:502-517`、`CameraGroupsPanel.vue:294-318`、`SystemAccessControlPanel.vue:1346-1368`；整个面板复制 2 遍：`LiveView.vue:775-924`、`PlaybackView.vue:2579-2693`；`filteredCameras` computed 也写了 2 份（`LiveView.vue:88`、`PlaybackView.vue:299`） |
| ★★★ | `<DataTable>` + `<PaginationBar>` | **14 个 `<table>` 分布 10 文件** | 同一 container/thead/`<td colspan>` 形状；`colspan="6"`/`colspan="5"` 已与真实列数不符；分页条只在 `FilesView.vue:1547-1573` 手写了一份 |
| ★★★ | `<ConfirmDialog>` + `useConfirm()` | **15 处原生 `window.confirm` / 11 文件** | `CameraGroupsPanel.vue:146`、`SystemApiTokensPanel.vue:113`、`StorageView.vue:396,594,696`、`PlaybackView.vue:2136,2255` … 阻塞主线程、无法样式化、无法 i18n；`LiveView.vue:700` 与 `PlaybackView.vue:2136` 是多行拼接，需要 dialog body slot |
| ★★★ | `<EmptyState>` | **14 处 / 5 种变体** | 全局 `.empty-state`（`styles.css:835`）被 `CamerasView.vue:1587`、`FilesView.vue:2641`、`RecordingScheduleView.vue:1749` 三处 scoped 覆盖而失效；另有 `.preview-empty-state`、`.storage-empty`、`.events-empty`、`.unifi-empty-box`、`.live-empty-tile` 等 |
| ★★ | `<CameraSelect>` | **42 个 `<select>` / 20 文件**，相机选项循环 9 处 | `EventsView.vue:574`、`AlertsView.vue:329`、`FilesView.vue:971`、`StorageView.vue:1646`、`SystemView.vue:2441`、`SystemAccessControlPanel.vue:1346`、`CameraGroupsPanel.vue:294`、`CameraDetailStreamsTab.vue:276`、`SystemAlertRulesPanel.vue:528` |
| ★★ | `<RecordingWindowsEditor>` | **整套周计划编辑器被写了两遍** | `RecordingScheduleView.vue`（常量 50-65、helpers 112-156、ops 441-503、模板 977-1134）vs `CameraDetailRecordingTab.vue`（`weekdays` 63-70、ops 260-410、模板 700-793）。**约 290 LOC 逻辑 + 215 LOC 模板**；且预置位已用两套魔法字符串（`'all_day'\|'workdays'\|'night'\|'weekend_plus'` vs `'24x7'\|'workdays'\|'night'\|'weekend'`）、星期顺序相反（mon-first vs sun-first）、`validateWindows` 只有 A 有 |

### 3.2 前端业务组件（按现有 `v-if="tab === …"` 边界拆分）

- **`SystemView.vue`（3,484 行：script 1-1446 / template 1447-3313 / style 3313-3484）** —— 已把 7 个 tab 委派给子组件（`SystemAccessControlPanel` 等），但 **6 个 tab 仍内联**。按既有 `v-if` 缝隙切：`SystemOverviewTab` 1483-1584(102) · `SystemGeneralTab` 1589-1817(229) · `SystemTimeTab` 1818-2161(344) · `SystemNotificationsTab` 2174-2358(185) · `SystemAiFrigateTab` 2367-2521(155) · **`SystemBackupTab` 2522-3178(657!)** · `SystemAuditTab` 3179-3312(134) · `SystemNavSidebar` 1449-1470。**这只是在extends已确立的模式**，改完约 300 行。
- **`PlaybackView.vue`（4,512 行：script 1-2576 / template 2577-3798 / style 3799-4512）** —— 3 个内联巨型面板：`PlaybackCameraPanel`（模板 2579-2693）· `PlaybackTopBar`（2696-2926 + style 4089-4500）· `PlaybackVideoStage`（2928-3186）· `PlaybackDiagnosticsPanel`（3188-3415）· **`PlaybackActionPanel`（3445-3794 + style 3800-4087 ≈830 LOC）**，其中 protect/export/share 三块还可再分（3442-3793 = 152 行 + `saveShare`/`copyShareLink`/`revokeShare` 2158-2272）· `PlaybackTimelinePanel`（3400-3443）。视图只留 master-clock/传输编排（1295-1817），约剩 800 行。
- **`FilesView.vue`（2,684 行，scoped style 1,097 行是全仓最大）** —— `FilesFilterHeader` 957-1074 · `FilesMonthCalendar` 1075-1122 · `FilesSegmentInspector` 1125-1356 · `FilesHeatmapCard` 1190-1257 · `FilesSegmentTable` 1358-1574。**注意**：拆分时不要把 2.3 #4 的假批量按钮固化进共享 `BatchActionBar`。
- **`StorageView.vue`（2,560 行）** —— `StorageMetricsCards` 768-800 · **`StorageTargetCard` 849-1013 与 1014-1128 近乎相同**（同 `.unifi-card-header`、同健康徽标、同容量条、同 4 按钮页脚，只差水印块与 WebDAV 说明）· `StorageRetentionTable` 1152-1288 · `StorageSwitchTargetDrawer` 1291-1356 · `StorageTargetEditorDrawer` 1357-1595 · `StorageRetentionEditorDrawer` 1596-1736。
- **`CameraOnboardingPanel.vue`（1,881 行，无 scoped style，最干净）** —— `OnboardingModeTabs` 1144-1182 · `OnvifOnboardingFlow` 1184-1568(385) · `CsvBatchImportStep` 1569-1747(179) · `RtspManualForm` 1748-1881(134)。**文件内已有真重复**：批量默认值表单逐字渲染两遍（1329-1375 与 1651-1697，各约 47 行）→ 提取 `<BatchDefaultsForm v-model>`；`csvPort`/`rtspHost`/`buildRtspUrl`(252-300) 应入 `utils/rtsp.ts`（已有 `cameraBatchCsv.ts` 先例）。

### 3.3 前端 Composables（现在 `utils/` 只有 `uuid.ts`，**完全没有 util/composable 层**）

| 建议 | 现状重复 |
|---|---|
| `useAsyncResource(loader)` | `loading=true / error=null / try / catch / finally` 块出现 **22 次**；其中 4 个文件连函数名都叫 `load()`（`CameraDetailPanel.vue:192`、`SystemApiTokensPanel.vue:64`、`SystemOidcPanel.vue:51`、`SystemSecretStorePanel.vue:52`）；并可吸收重复的 `auth.hasPermission` 守卫 |
| `useGlobalRefresh(handler)` | `zero-nvr:refresh` 监听在 **8 个视图**手工接线（`EventsView`、`AlertsView`、`CamerasView`、`DashboardView`、`StorageView`、`LiveView`、`SystemView`、`PlaybackView`），约 40 LOC + 8 个自定义 wrapper |
| `useDismissable(open, root)` | `closeOnOutside` + `closeOnEscape` 在 `ThemeControl.vue:52-70` 与 `LanguageControl.vue:54-84` **逐字重复约 30 行**；而所有抽屉与 popover 恰恰**缺**这个行为 |
| `useFullscreen(ref)` | `LiveView.vue:723-736`、`PlaybackView.vue:2541-2552`、`LiveCameraTile.vue:1978-1980` |
| `usePolling` | `CameraDetailRecordingTab.vue:311`、`LiveCameraTile.vue:740,788`、`PlaybackView.vue:2079-2102` |
| `useLocalStorage` | `theme.ts:18,52`、`i18n.ts:3204,3239` |
| `utils/format.ts` | **`formatBytes` 在 `SystemView.vue:518` 与 `SystemReleaseValidationPanel.vue:100` 逐字节相同**；`formatTime`（Intl）写了 **8 份**且 options 各不同（`SystemView.vue:506`、`SystemApiTokensPanel.vue:53`、`SystemReleaseValidationPanel.vue:88`、`SystemRecoveryKitPanel.vue:57`、`AccountPanel.vue:37`、`DashboardView.vue:183`、`AlertsView.vue:101`、`CameraDetailPanel.vue:131`）；`pretty()` 重复 2 份；`formatDuration` 2 份 |
| `utils/recordingWindows.ts` | 见 3.1 的 `<RecordingWindowsEditor>`（纯函数 + `PRESETS`） |

### 3.4 前端 CSS 与 i18n

- **组件内 scoped CSS 共 10,744 行，占全仓 CSS 的 67%**（`styles.css` 仅 5,259 行）。其中 **25 个 class 在 ≥2 个 scoped 块中重复**，**25 个 class 同时存在于全局与 scoped**（scoped 静默覆盖全局，全局那份成了死代码）。最严重的是三个 camera-detail tab 各自重声明整套按钮系统：`.button`/`--primary`/`--ghost`/`--compact` + `.camera-detail-actions`，**约 229 行重复**；`.camera-detail-section` 家族在 `RecordingTab 1004-1032` 与 `StreamsTab 312-340` 逐字重复 58 行 → 提取 `<CameraDetailSection>` + `#heading`/`#actions` slots。
- **`i18n.ts`（3,252 行）把 18 个命名空间 × 2 语言塞在一个文件里**，另有 6,924 个字符的硬编码中文在绕过它。建议按命名空间拆 `locales/<ns>.ts`，并在做组件拆分时顺手把 `t(\`中文\`)` 换成真 key（成本最低的时机）。
- **`AppShell.vue:93-200` 有 9 段手写 svg + `RouterLink` 导航块**，可像 `SystemView.vue:205-287` 那样用数组驱动；另 7 处 inline `<svg>` 重复了 `UiIcon` 已有图标（`PlaybackView.vue:2717,2765,2779,2824`、`LiveView.vue:952,1085`、`RecordingScheduleView.vue:600`、`AppShell.vue:93,105,117,127,136,145,155,168,195`）。

### 3.5 后端共享基础模块

| 优先级 | 建议模块 | 现状（重复量） | 证据 |
|---|---|---|---|
| ★★★★★ | `core/pagination.py`（`Page[T]`/`PageModel[T]`/`encode_cursor`/`decode_cursor(resource=)`/`paginate()`） | **游标分页写了 6 遍**：`recordings/query.py:24,35`、`exports:23,36`、`alerts:23,36`、`audit:29,44`、`events:23,34`、`backups:23,36`（codec 249 LOC，6 个 `query.py` 合计 1,033 LOC）。AST 归一化 diff 证明 **零逻辑漂移** —— 仅时间戳 key 与错误码不同，4 份相似度 0.96~1.00。重复还延伸到 6 个 page dataclass + 7 个 Pydantic page model（`next_cursor` 默认值漂移） | 已用 `diff` 逐对验证 |
| ★★★★★ | `tests/conftest.py` + `tests/factories.py` + `tests/fakes.py` | **`conftest.py` 只有 11 行**，脚手架每文件重写：`make_app` ×40、`make_database` ×32、`setup_admin` ×23、`seed_camera` ×8、`login` ×5，合计 **约 1,866 LOC**；另有 131 处 inline `Settings(...)`、88 处 `Base.metadata.create_all`、95 个 `class Fake*`（`FakeOnvifAdapter` ×16、`FakeZlmAdapter` ×9、`FakeRecordingTasks` ×7）、`ADMIN_PASSWORD` 在 **69 个文件**里重复定义。已漂移：`session_cookie_secure=False` 与 `FakeRecordingTasks` 挂载只有部分副本有 | 定量统计 |
| ★★★★ | `core/db/repository.py::fetch_or_404()` | **get-or-404 写了 31 遍**（`X = session.get(...)` / `if X is None:` / `raise ApiError(404…)`），25 个文件；其中 7 对是并排的 12 行双胞胎（`alerts/service.py:75`、`cameras/groups.py:32`、`storage/retention_admin.py:26`、`storage/service.py:247`、`backups/service.py:192`、`notifications/service.py:587`、`exports/service.py:74`） | 约 370 LOC |
| ★★★★ | `core/api/views.py`（`ApiSchema(from_attributes=True)` + `view()` + `AuditedSchema.audit_snapshot()`） | **56 个手写 view/snapshot 映射函数**（约 1,040 LOC），而全仓 `from_attributes` **只有 1 处**（`auth/schemas.py:49`），尽管有 155 个 `BaseModel`。同名重复：`_policy_view` ×3（`recordings/api.py:89`、`alerts/api.py:34`、`backups/api.py:35`）、`_audit_snapshot` ×3（`recordings/api.py:112`、`storage/api.py:90`、`exports/api.py:99`）、`_policy_snapshot` ×2 | 已核实 3 个 `_audit_snapshot` |
| ★★★ | `core/time.py`（`require_utc`/`optional_utc`/`coerce_utc`/`parse_aware`） | 7 个副本、3 套契约、2 个参数名（详见 2.4 #4）；另有 16 处 `utcoffset() is None` 与 **53 处裸 `datetime.now(UTC)`**（而 `utc_now()` 已存在于 `core/db/types.py:49`） | 逐个实读 |
| ★★★ | `core/fs.py`（`atomic_write_bytes/text/json`、`fsync_path`、`contained_path`） | 原子写 **8 处**（4 处缺 fsync，`health.py:883` 还有固定 `.tmp` 竞争）；路径包含性检查 **7 个命名副本 + 4 处 inline**，且 2 个返回 None / 6 个抛不同异常类型，只有 `reconciliation.py:242` 捕获 `OSError`（符号链接环） | 约 270 LOC |
| ★★★ | `core/jobs/runner.py` | **5 个 job 引擎共享同一骨架**（`__init__ + prepare + _mark_failed + _mark_<positive> + execute`）：`ArchiveLifecycleService`(377)、`ExportExecutionService`(229)、`BackupExecutionService`(444)、`NotificationDeliveryService`(326)、`LocalRetentionDeletionService`(219) = 1,595 LOC；`_mark_failed` ×5(82 LOC)：`retention.py:924`、`archive.py:254`、`delivery.py:206`、`exports/execution.py:146`、`backups/execution.py:293`。**漂移**：错误字段名 `last_error`/`last_error_code`/`error_code` 不一致；终态守卫 `{CANCELLED,EXPIRED}` 只有 exports 有 | |
| ★★★ | `core/api/router.py`（`audited()` 装饰器、`scoped_or_404`）+ `modules/audit/emitter.py` | **73 处** `try/except/rollback`（12 文件，`cameras/api.py` 14、`auth/admin_api.py` 12）· **65 处** `append_audit_event(...); session.commit()`（12 文件）· 26 处重复的 scope-gate 前导。**契约不对称**：`core/db/dependencies.py:7` 的 `get_db_session` 只 `close()` 不 `rollback()`，而路由器自己补了 73 次 rollback | |
| ★★ | `integrations/base.py`（`IntegrationError`、`HttpAdapter.request()`、`run_subprocess`） | **9 个 `*IntegrationError(RuntimeError)`**（122 LOC）；httpx `TimeoutException`/`HTTPError` 映射在 `zlm/adapter.py:143/149,244/250,337/343,396/402` + `frigate:105/111/124` 共 8 处；`_run` 子进程包装 2 份（`rclone:111`、`restic:66`）。**漂移**：默认 status 502 vs onvif 422 vs 无；无一带 `retryable`，尽管 15 个 huey 任务各自声明 retries | |
| ★★ | `core/settings/namespace.py` | 3 个服务各自重实现同一 key-value 命名空间存储：`SystemSettingsService`(:31)、`TimeSystemSettingsService`(:207)、`RuntimeTuningSettingsService`(:430)，`update` 体近乎相同；**漂移**：Time 的 get/update 丢了 `settings` 关键字参数并加 `legacy=` 回退，三个 `normalize` 签名不可互换。另：惰性 settings 读取在 `live_transcode.py:104` == `playback_cache.py:64` ≈ `dispatcher.py:25` **逐字复制 3 遍** | |
| ★★ | `core/coerce.py` + `core/http.py::client_fingerprint` | `_read` **三份逐字节相同**（`onvif/adapter.py:98` == `onvif/normalizer.py:23` == `onvif/events.py:14`）；`_text` ×5 但有 **3 套契约**（宽松 `str()` / 解包 `_value_1` / 校验型含 max_length + ApiError）；`_string_list` ×2（一个抛错去重，一个静默截断到 64）；`_client_info` 在 `auth/api.py:71` 与 `oidc_api.py:38` 相同，且同一逻辑在 `audit/service.py:22-40` 被 open-code 第三遍；`_now` 在 `zlm/health.py:46` == `zlm/continuity.py:47` | |
| ★★ | `core/registry.py::TtlRegistry` + `core/process.py` | `MediaSessionRegistry`（`media_sessions.py:33-39,66,156,206,290,316`）与 `LiveTranscodeManager`（`live_transcode.py:67-93,401,417,427,442,480,486`）各自实现 RLock + timer 工厂 + 取消 + 过期；进程停止被分叉成同步 `_stop_process`(`live_transcode.py:350`) 与异步 `_begin_process_stop`/`_stop_process`(`live_preview.py:160-174`，asyncio.shield 变体) | |
| ★★ | `scripts/lib.sh` 扩展（`read_env_file` 等） | **`read_env_file` 在 3 个脚本中逐字节相同**（`resource_check.py:53`、`resource_bounds_check.py:37`、`small_host_soak.py:63`），`positive_int` ×2、`host_path` ×2 —— 已用 `diff` 验证为 IDENTICAL | 已 diff 验证 |

### 3.6 后端巨型文件拆分

| 文件 | 规模 | 自然缝隙 |
|---|---|---|
| `modules/system/config_import.py` | **3,452 LOC，其中 `apply()` 2,159 行 + `validate()` 939 行 = 89.7%** | `_KNOWN_SECTIONS`(L63) 的 **12 个 section** 在两个方法里被线性走一遍，第三遍又在 `config_export.py`（727 LOC，同名 `_general:50` … `_backups:608`）。12 个 section 的精确行号已定位（validate→general:349,time:353,roles:363,devices:367,cameras:396,recording:440,storage_targets:462,alerts:471,notifications:480,oidc:489,frigate:498,backups:510；apply→1327,1374,1398,1521,1755,2396,2529,2874,2992,3116,3229,3404）→ `config_import/{_registry,_context,sections/*.py}` + 一个被 import/export **共用**的 `SectionHandler` 协议。**另有 42 处裸 `assert` 作用在不可信导入载荷上**，畸形输入会变成 `AssertionError` → 500 而非 400（已核实 42 处） |
| `modules/cameras/api.py` | 3,868 LOC / 40 端点 / 109 KB | 同模块**已有先例**：`live_preview_wall_api.py`、`live_layouts.py` 就是独立 router，`auth/` 也有 `admin_api.py`/`oidc_api.py`。按子域切：view 映射 115-444 · groups 451-596 · CRUD 600-720 · ONVIF 导入+发现 728-1308 · health/clock 1315-1493 · enable/disable/retire 1497-1763 · probe/verify 1764-2184 · live 选路+WHEP 2194-2791 · live 端点 2798-3373 · live compatibility 3381-3662 · snapshot/PTZ 3666-3868 |
| `modules/system/api.py` | 1,856 LOC / 19 端点 | views 94-161 · health+secret-store 168-333 · frigate 317-618 · config import/export 635-882 · settings 885-1237 · updates+SSE 1244-1300 · **NTP 1308-1780（`apply_camera_ntp_settings` 268 行）** · release 1787-1856 |
| `worker/tasks.py` | 1,549 LOC / 约 20 个 huey 任务 | prebuffer 84-376 · runtime reconcile 380-612 · capacity+policy 618-956 · catalog 963-1123 · retention 1126-1247 · frigate backfill 1251-1368 · 薄派发 1373-1453 · 调度+心跳 1457-1549。15 个任务各自手调 `retries`/`retry_delay`，无共享策略 → `worker/tasks/` 包 |
| `app/cli.py` | 2,686 LOC | **21 处完全相同的 `print(json.dumps(payload, sort_keys=True))`**（89,267,348,372,499,576,657,870,949,959,1008,1076,1193,1251,1273,1395,1501,1575,2131,2173,2360）· `_settings_database()` 被调 20 次 · 287 行 `build_parser`(2383-2669) 含 24 个 `add_parser`；另有第二对 `build_parser`/`main` 在 `recovery_kit_cli.py:12,33` → `app/cli/` 包（`_output.emit`、`_context`、`_registry.COMMANDS`，按 migrate/update/health/restore 分文件）。伴随小重复：`Database(settings)` + `initialize_runtime()` 在 5 处（`cli.py:72,2158,2208,2241`、`worker/tasks.py:129`），两种写法 |
| `modules/storage/service.py` | 1,272 LOC（单个 1,184 行类） | 注意 `_ensure_default_recording_unique:116` 与 `_ensure_default_archive_unique:155` 是 **37 行结构双胞胎**，只差一个 role 字面量；`update:654` 206 行、`switch_recording_target:861` 186 行 |
| 其他可切 | — | `onvif_onboarding.py` 1,257（`_reconfigure_existing:589-985` = 397 行）· `retention.py` 1,114（planner 69-879 vs deleter 896-1114）· `reconciliation.py` 1,107 · `notifications/service.py` 1,097 · `system/health.py` 894（7 个独立探针需 Collector 注册表，`HealthComponent` dataclass 已存在于 :147） |

**跨模块同名冲突型重复（4+ 实现）**：`_ensure_name_available`(`storage/service.py:95`) · `_ensure_name`(`backups/service.py:206`) · `_name_available`(`notifications/service.py:601`) + 若干 inline 409。

---

## 四、建议执行顺序

分为四波，核心原则是：**先把"已经逐字相同"的代码抽出来（近零风险），再让新组件吸收行数，最后才拆巨型文件** —— 否则拆分只是把代码从大文件搬到小文件，重复依旧。

**Wave 1 — 纯抽取，零行为变更（近零风险）**
后端：分页 (3.5-1) → 测试 fixtures (3.5-2) → `fetch_or_404` (3.5-3) → time helpers (3.5-5，顺带修 2.4 #4) → coerce (3.5-11) → atomic write / path containment (3.5-6，顺带修 2.4 #3)。
前端：`useToast`+`ToastHost`（修 2.4 #6）→ `StatusPill`（修 2.4 #1）→ `NoticeBanner` → `useConfirm` → `EmptyState` → `utils/format.ts` → `useDismissable`/`useGlobalRefresh`/`useAsyncResource`/`useFullscreen` → 删死 CSS。

**Wave 2 — 依赖 Wave 1 的原语**
前端 `<DrawerDialog>` 先落地，然后**逐个**改造 12 个抽屉文件（这一步解锁视图拆分）。
后端：`core/api/views.py` → router 样板 → `integrations/base.py` → `core/jobs/runner.py` → settings 命名空间 → `TtlRegistry` → `app/cli/` 包。

**Wave 3 — 巨型视图/文件拆分**
前端先去重 `<RecordingWindowsEditor>`，再 `SystemView`（沿用已有 Panel 模式）→ `PlaybackView` → `FilesView` → `StorageView` → `CameraOnboardingPanel` → `CameraListPanel`。
后端最后做 `config_import` section 注册表（**前置条件：先补 golden-file 测试**），再按 3.6 的表拆 router 与 worker。

**Wave 4 — 样式与 i18n 归位**
scoped CSS 提升到全局、`DataTable`/`CameraSelect`/`UiIcon` 图标补全、`AppShell` 导航数组化、`t(\`中文\`)` → 真 key。**CSS 提升必须放在拆分之后**，这样提升后的规则才落在正确的归属文件里。

**顺手清理**（任何一波都可并行）：2.1 的三项删除 + 2.3 的 2 个死导出 + `IntegrationAdapter` 死协议。
**需 owner 决策**：2.2 的文档归档与 ADR/spec 重新编号；2.3 #4/#5 的批量功能是"补后端批量端点"还是"摘掉按钮"。

---

## 五、审计明确排除的误报（避免白费力气）

- 后端 `get/list/create/update/delete` 在 21/13/14/11/8 个服务里同名 —— 这是**有意的 per-service CRUD 词汇**，只有 404 响应体可以共享。
- `integrations/contracts.py` 中约 35 对 Protocol 与实现的同名方法（`DeviceAdapter:8`、`MediaPlane:44`）—— **刻意保持接口镜像**，且被 `test_adapter_contracts.py` 钉住；只有 `__enter__/__exit__/close` 值得上提。
- `_prune`、`_roles`、`_fingerprint`、`_message`、`_database` 为**无关同名**。
- `media_proxy.py`、`frontend.py`、`worker/consumer.py`、`recovery_kit_cli.py` **不是孤儿模块**（分别被 `main.py:19,49`、compose 的 `huey_consumer.py`、`scripts/recovery-kit-decrypt.sh:54` 引用）。
- `.form-error` 的两次声明**不是样式冲突**（属性互补，已核对）。
- `poc/`、`scripts/`、`deploy.sh`、`release-manifest.json` 均**建议保留**（见 2.5）。

---

## 勘误（第 4 轮执行时发现）

### 1. 第 8 条「把中文句子当 i18n key」是误报

原判据的正则形如 `t(\`[^\`]*[一-龥]`，它**会匹配 `showToast(\`中文…\`)` 的尾部**：`showToast` 以字母 `t` 结尾、紧跟一个 `(`，因此子串 `t(` 命中。

要求 `t` 前面不是标识符字符后，真正的 ``t(`…`)`` 只剩 **2 处**，且都是**正确的动态 key**用法、不含中文；所谓「22 处」全部是 `showToast(`中文 ${…}`)`。

因此问题不是「中文被当成 key」，而是「**这些用户可见文案根本没走 i18n**」。修复方式相近，但性质与影响面不同。

**第 4 轮已修复**：22 条 `showToast` 迁入真 key（`cameras.toast.*` 5、`events.toast.*` 4、新增 `files.toast.*` 10、新增 `schedules.toast.*` 3），en / zh 各一套。

### 2. 顺带发现的真实缺陷：`t("storage.mode") || "清理模式"`

`StorageView.vue` 的保留策略表头：

```vue
<th>{{ t("storage.mode") || "清理模式" }}</th>
```

`storage.mode` 这个 key **不存在**，而 vue-i18n 缺 key 时返回的是 **key 本身**（非空字符串），所以 `|| "清理模式"` 这个兜底**永远不触发** —— 运维在表头上看到的是字面量 `storage.mode`。

同一张表还有两处硬编码中文表头（`WebDAV 强制前置`、`操作`）。三处均已修复，并补上 `storage.mode` / `storage.webdavRequired` / `storage.actions`（两个语言各一份）。

### 3. 新增回归门禁 `frontend/src/i18n.spec.ts`（5 个用例）

此类缺陷（缺 key、单边语言、死兜底）此前没有测试覆盖。新 spec 断言：

1. `.vue` / `.ts` 中**静态引用的每个 key** 在 en 与 zh **都存在**；
2. en 与 zh **完全对齐**（任一方向差集为空）；
3. 保留策略表那三个 key 的值正确（锁死本次修复）；
4. **不存在** `t("…") || "…"` 这种兜底永不触发的写法；
5. 本轮新增的 4 个 toast key 双语齐备。

编写时遇到并解决了一个环境约束：应用 `tsconfig` 只引入 `vite/client`（无 `@types/node`），故 spec **不能用 `node:fs`**，改用 Vite 的 `import.meta.glob(..., { query: "?raw", eager: true })` 读取源码 —— 既有类型可用，也无需新增依赖。
