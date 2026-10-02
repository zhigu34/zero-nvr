# 前端功能对等审计：删除 `frontend/` 会失去什么

**状态**：PR-6 切换的前置材料
**日期**：2026-10-02 · 基线 `codex/frontend-react-shell` @ `ba3a733`
**结论**：**PR-6 的阻塞项不是 D-2，是一份尚未清点的功能差距。**

---

## 0. 为什么有这份文档

之前把 PR-6 标为「需先裁决 D-2」，那是**沿用了排批次时的假设，从未核对过**。
实际去清点后发现，React 侧有**一批 Vue 已有、React 完全没有的功能**，
其中大部分对应着**后端已经实现、并且有测试覆盖**的端点。

D-2 裁决不了这件事：它决定的是告警与录制过滤**怎么合并**，与「备份界面
要不要重建」无关。

---

## 1. 规模对比

| | Vue (`frontend/`) | React (`frontend-react/`) |
|---|---|---|
| 视图 + 组件 | 54 个组件 + 13 个视图，**39,129 行** `.vue` | 12 个模块页 + 3 个系统页，**17,836 行** `.ts/.tsx` |
| 测试 | 54 个 spec，8,371 行 | 48 个 spec，9,896 行 |
| 路由 | 12 | 15 |

React 测试行数更多、文件更少，是因为媒体层的纯逻辑被拆成了可测模块
（PR-4 拆出 11 个）。**但行数不是差距的度量**——有 30 个 Vue spec 测的是
React 完全没有的功能，删掉 `frontend/` 会连同这些测试一起消失，**没有任何东西接替**。

---

## 2. 路由层

| Vue | React | 状态 |
|---|---|---|
| `/login` `/setup` `/live` `/playback` `/files` `/events` `/cameras` `/recording-schedules` `/storage` `/system` | 同名 | ✅ |
| `/alerts` → 重定向 `/events`（`AlertsView.vue` 是死代码） | `/alerts` 独立页 | ✅ 反而修好了 |
| `/dashboard` → 重定向 `/live` | — | ✅ 无需接 |
| `WorkspaceView.vue` | — | ⚪ Vue 侧也未被 `router.ts` 引用，同样是死代码 |
| — | `/timeline` `/users` `/audit` | ✅ 新增 |

**路由层没有缺口。** 差距全在页面内部。

---

## 3. 系统设置页：10 个 tab 覆盖 6 个

Vue 的 `SystemTab` 定义在 `SystemView.vue:93-103`。

| tab | Vue 组件（行数） | 后端端点 | React | 状态 |
|---|---|---|---|---|
| overview | SystemOverviewTab (223) | `/system/health` `/info` | SystemView 状态条 | ✅ |
| general | SystemGeneralTab (277) | `PATCH /system/settings` | SystemView | ✅ |
| time | SystemTimeTab (417) | 同上 + `/camera-clock-health` | SystemView | ✅ |
| users | SystemAccessControlPanel (1305) | `/users` `/roles` `/permissions` | UsersView | 🟡 见 §3.1 |
| alerts | SystemAlertRulesPanel (969) | `/alert-policies` | AlertsView | ✅ |
| audit | SystemAuditTab (269) | `/audit` | AuditView | ✅ |
| **tokens** | SystemApiTokensPanel (376) | `/api-tokens` | — | ❌ |
| **notifications** | SystemNotificationsTab (237) | `/notification-targets` `/notification-deliveries` | — | ❌ |
| **ai** | SystemAiTab (218) | `/integrations/frigate` `+/test` `+/backfill` | — | ❌ |
| **backup** | SystemBackupTab (813) + SystemRecoveryKitPanel (400) | `/backups/*` `/recovery-kit/*` | — | ❌ |

### 3.1 `SystemAccessControlPanel` 1305 行 vs `UsersView`

`UsersView` 覆盖了用户 CRUD、角色分配、机位范围。**没有**的是「角色 → 权限点」
矩阵：`GET /permissions` 与 `GET /roles`（含 `RoleView.permissions`）这两个端点
React 只用到了后者的一半——`MATCH_KEY_META` 之外没有渲染任何权限矩阵。

这正是 **PR-0（RBAC 收敛）**的实际工作量所在。之前把 PR-0 记为「与 D-2 同批」
也是错的：它不依赖 D-2，它依赖这个矩阵界面存在。

---

## 4. 摄像机页

| Vue 组件（行数） | 说明 | React | 状态 |
|---|---|---|---|
| CameraOnboardingPanel (1248) + 5 个步骤 (960) | ONVIF 探测 / 手动接入 / CSV 批量，**6 个 spec** | — | ❌ **最大单项** |
| CameraDetailPanel (1147) + General/Streams 两个 tab (888) | 详情抽屉：基本 / 码流与绑定 / 健康与时钟 | CameraEditor（仅编辑表单） | 🟡 缺只读详情与**码流用途绑定**（RECORD/LIVE_HIGH/AI_DETECT/… 的绑定是核心能力） |
| CameraGroupsPanel (595) | 机位分组 CRUD | 仅在用户范围面板里只读列出 | ❌ |
| CameraDeviceGlyph (92) | 设备图标 | lucide 图标 | ✅ |

后端 `POST /camera-groups` `PATCH` `DELETE` 齐全，**只是没有界面**。

---

## 5. 文件页

Vue 的文件浏览器是一套**独立设计**（月历 + 热力图 + 预览播放器），
React 的 FilesView 是按契约重写的另一种形态。两者不是同一件东西：

| Vue 组件（行数） | React | 状态 |
|---|---|---|
| FilesMonthCalendar (376) | — | ❌ |
| FilesHeatmap (298) | — | ❌ |
| FilesPreviewPlayer (309) | — | ❌ |
| FilesSegmentInspector (235) | 片段详情侧栏 | 🟡 形态不同 |
| FilesSegmentTable (333) | SegmentTable | ✅ |

**这 3 个组件共 983 行、5 个 spec，功能是「按月/按天浏览录像密度」。**
React 的时间轴页部分覆盖了「看录像覆盖」这个需求，但**没有日历与热力图形态**。

这是一个**产品决策**，不是单纯的补齐：文件页到底是「浏览并导出」还是
「日历式回看」，PR-5e 已经按前者实现了。需要确认后者是否要。

---

## 6. 回放页

| Vue 组件（行数） | React | 状态 |
|---|---|---|
| PlaybackTopBar (701) + TolerantPlaybackTile (608) + PlaybackTimelineCanvas (1063) + Controls (169) + CameraPanel (155) | PR-4 拆为 11 个可测模块 + PlaybackView | ✅ 已被取代（且修掉 3 个旧缺陷） |
| **PlaybackActionPanel (171) + Form (172) + History (177)** | — | ❌ **3 个 spec**（回放中的手动触发录像、保护录像、操作历史） |
| **PlaybackShareEditor (308)** | FilesView 有分享面板 | 🟡 入口不同 |
| **PlaybackDiagnosticsPanel (279)** | — | ❌ **1 个 spec** |

「回放中的操作」——手动触发录像、保护录像、操作历史——是回放页的另一半，
React 目前只有「看」没有「做」。

---

## 7. 直播 / 账号 / UI 原语

| 项 | React | 状态 |
|---|---|---|
| LiveCameraTile (2591) | PR-4 拆为传输层 + `useLiveTile` + 9 个 spec | ✅ 已被取代 |
| **AccountPanel (531)** | — | ❌ 个人账号设置：改密码、邮箱、语言 |
| ConfirmDialog (57) + useConfirm | — | ❌ **本轮已补**，见 §9 |
| DrawerDialog (81) | — | ❌（部分页面用侧栏代替，未统一） |
| **LanguageControl (189) + i18n** | 无 i18n | ❌ 全应用硬编码中文 |
| ThemeControl (190) | `use-theme.ts` | ✅ |
| NoticeBanner / StatusPill / EmptyState / ToastHost | Callout / StatusDot / EmptyState / Toast | ✅ |

**i18n 是一条独立的决策**：Vue 侧有 `vue-i18n` 与 `LanguageControl`，
React 侧目前全部硬编码中文。删掉 `frontend/` 等于**永久放弃多语言**，
除非决定在 React 侧重建 i18n 体系。这需要明确裁决，不能默认丢掉。

---

## 8. 汇总

| 分类 | 组件数 | Vue 行数 | 受影响的 Vue spec |
|---|---|---|---|
| ✅ 已被 React 取代 | 19 | 8,373 | 0（都有 React 对应测试） |
| ❌ **完全缺失** | **23** | **7,784** | **16** |
| 🟡 部分覆盖 / 形态不同 | 5 | 2,578 | 3 |
| ⚪ 两侧都是死代码 | 2 | — | 0 |

行数为 `wc -l` 实测，非估算。

**完全缺失的 23 个组件对应的后端端点全部已经实现并有测试覆盖。**
换句话说这不是「后端没做」，是「前端没做」。

**54 个 Vue spec 中，19 个测的是 React 完全没有的功能**——删除 `frontend/`
会让这 19 个文件连同它们覆盖的行为一起消失。

按建议顺序（依赖少、价值高在前）：

| # | 项目 | Vue 行数 | 依赖 |
|---|---|---|---|
| 1 | 通知渠道（targets + deliveries + 测试发送） | 237 | 无 |
| 2 | API 令牌（自己的账号） | 376 | 无 |
| 3 | 密钥环查看与轮换 | 435 | 无 |
| 4 | Frigate 集成（配置/连通性/回填） | 218 | 无 |
| 5 | 备份策略 + 恢复包 | 1,213 | 1 个 spec |
| 6 | 机位分组 CRUD | 595 | 无 |
| 7 | 个人账号设置（改密码/邮箱） | 531 | 无 |
| 8 | 回放操作（手动触发/保护/历史）+ 诊断面板 | 799 | 4 个 spec |
| 9 | 摄像机接入向导（ONVIF/手动/CSV） | 2,208 | 6 个 spec，最复杂 |
| 10 | 角色 → 权限矩阵（= PR-0） | — | 需先裁决 RBAC 收敛范围 |
| 11 | 摄像机详情抽屉（码流绑定/健康/时钟） | 2,035 | 1 个 spec |
| 12 | 文件日历 / 热力图 / 预览播放器 | 983 | 3 个 spec，需产品决策 |
| 13 | i18n 体系 | 189+ | 需明确是否放弃多语言 |

---

## 9. 本轮已修：确认弹窗

清点过程中发现一个**本分支自己引入的回退**：Vue 侧有 `useConfirm` +
`ConfirmDialog`（15 处调用点），React 侧没有，删除告警规则 / 撤销分享链接 /
取消导出三处**单击即执行**。

`useConfirm.ts` 里的注释说明了原语存在的原因，值得照抄进判断标准：

> `window.confirm` 阻塞主线程、无法样式化或翻译，且在某些浏览器里被直接
> 抑制——此时检查**静默通过**，操作照常执行。

已补 `components/ui/Confirm.tsx`（`role="alertdialog"`，Esc 与背景点击均视为
取消，**无 provider 时抛错而不是默认同意**），并接入上述三处。
判定标准是**不可逆**：停用用户可逆，不加确认；删除规则、撤销链接、取消导出
不可逆，必须确认。

---

## 10. PR-6 切换还需要改什么

即使 13 项全部补齐，切换本身还要动这些：

| 位置 | 改动 |
|---|---|
| `backend/Dockerfile:14,94` | 构建 Vue → 改构建 React，产物路径 `/app/frontend` 不变 |
| `scripts/release-manifest.sh:44` | 读 `frontend/package.json` → 改指 `frontend-react/` |
| `.github/workflows/frontend.yml` | 触发路径与缓存键 |
| `.github/workflows/deployment.yml:11,22` | 触发路径 |
| `frontend/` | 删除 |
| `docs/` | TECH_STACK / DEPLOYMENT / ARCHITECTURE 中的前端描述 |

**因此 PR-6 应当拆成「补齐 → 切换」两段**，而不是原计划里的一步。
切换本身是机械的，风险在补齐清单的取舍上。

---

## 11. 待裁决

1. **i18n**：React 侧是否重建多语言？这决定 13 项之外是否还有第 14 项。
2. **文件页形态**：日历 + 热力图是否保留，还是接受 PR-5e 的「浏览并导出」？
3. **RBAC 收敛范围**：`SystemAccessControlPanel` 的 1305 行是权限矩阵，
   收敛成三角色后它会大幅简化——但简化成什么样需要先定。
4. **D-2**：仍然待裁决，但它只影响告警页的形态，不影响上面任何一项。
