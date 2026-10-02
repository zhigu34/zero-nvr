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
| users | SystemAccessControlPanel (1305) | `/users` `/roles` `/permissions` `/roles/{id}/camera-scope` | UsersView + RoleEditor + RoleScopeSection | ✅ 已补齐 |
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
| CameraDetailPanel (1147) + General/Streams 两个 tab (888) | `CameraDetailDrawer` + `CameraStreamsPanel` / `CameraHealthPanel` / `CameraClockPanel` | — | ✅ 已补齐 |
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
| DrawerDialog (81) | `components/ui/Drawer.tsx` | ✅ 已补齐 |
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
| ✅ 本轮补齐 | 18 | 12,833 | 26 |
| ❌ **仍然完全缺失** | **6** | **272** | **3** |
| 🟡 部分覆盖 / 形态不同 | 5 | 2,578 | 3 |
| ⚪ 两侧都是死代码 | 2 | — | 0 |

行数为 `wc -l` 实测，非估算。

**完全缺失的 23 个组件对应的后端端点全部已经实现并有测试覆盖。**
换句话说这不是「后端没做」，是「前端没做」。

**54 个 Vue spec 中，19 个测的是 React 完全没有的功能**——删除 `frontend/`
会让这 19 个文件连同它们覆盖的行为一起消失。

按建议顺序（依赖少、价值高在前）：

| # | 项目 | Vue 行数 | 依赖 | 状态 |
|---|---|---|---|---|
| 1 | 通知渠道（targets + deliveries + 测试发送） | 237 | 无 | ✅ 已补齐 |
| 2 | API 令牌（自己的账号） | 376 | 无 | ✅ 已补齐 |
| 3 | 密钥环查看与轮换 | 435 | 无 | ✅ 已补齐 |
| 4 | Frigate 集成（配置/连通性/回填） | 218 | 无 | ✅ 已补齐 |
| 5 | 备份策略 + 恢复包 | 1,213 | 1 个 spec | ✅ 已补齐 |
| 6 | 机位分组 CRUD | 595 | 无 | ✅ 已补齐 |
| 7 | 个人账号设置（改密码/邮箱） | 531 | 无 | ✅ 已补齐 |
| 8 | 回放操作（手动触发/保护/历史）+ 诊断面板 | 799 | 4 个 spec | ✅ 已补齐 |
| 9 | 摄像机接入向导（ONVIF/手动/CSV） | 2,208 | 6 个 spec，最复杂 | ✅ 已补齐 |
| 10 | 角色 → 权限矩阵（= PR-0） | — | 需先裁决 RBAC 收敛范围 | ⬜ |
| 11 | 摄像机详情抽屉（码流绑定/健康/时钟） | 2,035 | 1 个 spec | ⬜ |
| 12 | 文件日历 / 热力图 / 预览播放器 | 983 | 3 个 spec，需产品决策 | ⬜ |
| 13 | i18n 体系 | 189+ | 需明确是否放弃多语言 | ⬜ |

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

## 10. 补齐 1/13：通知渠道

对应 Vue 的 `SystemNotificationsTab.vue`（237 行，1 个 spec）。已接入
`SystemView` 的「通知渠道」tab，**零后端改动**。

### 契约上最要紧的一条

`url` 与 SMTP 密码是 `SecretStr`——**只写，读不回来**。读模型只有
`url_configured` / `credentials_configured`（`notifications/schemas.py:63-70`）。

所以 `NotificationTargetUpdate` 不是 `url: str | null`：`null` 在「保持不变」
与「删掉它」之间无法分辨，schema 因此带了一个显式动词：

```text
url_action:         keep | replace | clear
credentials_action: keep | replace | clear
```

`applyUrlEdit` / `applyCredentialsEdit` 是全应用唯一构造这两种 body 的地方。
编辑器每个秘密给三选一，**默认「保持不变」**——已存的值读不出来，表单无从
预填，一个什么都没输入的操作员**不应该**顺手替换或清空它。

### 另一件容易混的事

有两处设置看起来都像「安全邮件」，规则却不同，所以拆成两个控件：

| | `config.password_reset: true` | security email default |
|---|---|---|
| 存在哪 | 目标自己的 `config_json` | 一个 `SystemSetting` 指针 |
| 唯一性 | 全局唯一，第二个是 409（`service.py:96-112`） | 单指针，随便覆盖 |
| 要求 | URL 必须是 `mailto:`/`mailtos:`，无路径无 fragment（`service.py:119-134`） | 目标必须是 **`kind == "smtp"`**（`service.py:539-551`） |

第一个决定重置邮件在 Apprise 里怎么寻址，第二个指向真正发信的 SMTP 目标。

### 移植时改掉的四处

Vue 侧能用的写法在这里会**静默**做错事，所以没有照搬：

1. **测试抓到的真 bug**：编辑路径提交时用的是点击「替换」瞬间捕获的
   `urlEdit.value`，此后在输入框里敲的内容全部丢失——URL 永远发空串。
   改成动词与值分开存，提交时读实时输入。
2. **「替换」但不填值**：发空串 = 清掉已存的秘密，且因为读不回来**无法撤销**。
   现在空值直接挡住提交。
3. **密码重置目标可以清空 URL**：清掉之后它永远收不到重置邮件，而且界面上
   只剩一行「未配置 URL」。现在当场说明后果并阻止。
4. **新建时默认「保持不变」**：可以建出一个 URL 为空、永远不投递、看上去
   却已配置好的目标。新建时 URL 默认进入「替换」并必填；SMTP 凭据仍默认
   不发送——无认证是合法配置。

`toSecretAction` 把三态控件的字符串值收窄回动词，**未知值落到 `keep` 而不是
`clear`**：两者破坏的东西不同，在只写字段上猜错不可恢复。

### 顺带修的无障碍缺陷

`Segmented` 是字符串值控件，同一屏里两个秘密字段各有三个同名按钮
（保持不变 / 替换 / 清空），屏幕阅读器会读成六个无关按钮。整块字段改为
`role="group"` + `aria-label`（而不只是按钮行），两个目标列表也各加了名字。
测试因此可以用 `getByRole("group", {name})` 精确定位，而不是靠按钮序号。

### 验收

| 项 | 结果 |
|---|---|
| `npx tsc --noEmit` | 干净 |
| `npx vitest run` | 693 passed / 50 files（本项 +42） |
| `npm run build` | 通过 |
| `git diff main...HEAD -- backend/` | 空 |

新增测试：`api/notifications.spec.ts`（20）+
`components/system/NotificationsPanel.spec.tsx`（22）。
面板测试里最要紧的一条断言是**「打开编辑器什么都不输入直接保存，请求体里
不出现任何秘密字段」**——它是「保持不变」这个默认值的唯一证明。

---

## 11. 补齐 2–4/13：API 令牌 / 密钥环 / Frigate

三个面板一起做，零后端改动，挂在系统设置的新增 tab 上。

### 分工

契约层（`api/*.ts` + `lib/*Mutations.ts` + `queries.tsx`）自己写——这三块的
精度要求最高，且跨模块必须一致。三个面板并行委派，文件所有权互不重叠
（各一个 `.tsx` + 一个 `.spec.tsx`），契约层不交给子任务。
`SystemView` 的 tab 接线最后由我统一做。

**并行的一个副作用值得记**：两个子任务各自报出了契约层的问题，而它们都没权限
改，只能在面板层绕过。其中一个是我在任务书里**直接给错的选择器**：

```ts
useAuthStore((s) => s.user?.permissions ?? [])   // ← 错
```

`user` 为 null 时每次调用都返回**新的**数组引用，而 `useSyncExternalStore` 用
`Object.is` 比较快照，于是永远不相等 → 无限重渲染 → React 抛
*Maximum update depth exceeded*。已修成 `stores/auth.ts` 里的 `useMyPermissions()`，
并把「fallback 必须是常量」写进注释——**陷阱留在出问题的源头，而不是每个调用点**。

另一个是 `validateFrigateForm` 只校验 Frigate 侧机位名，漏了 `camera_id` 是必填
UUID（`frigate.py:99-128` 会拒），等于把一个必然的 422 留给服务端发现。已补进
契约层，并加了断言。

### 三处最容易写错的契约

**1. `permissions: null` 不是「没有权限」**（`auth/api.py:514-518`）

```python
requested = frozenset(body.permissions) if body.permissions is not None
            else context.permissions
```

`null` = 继承创建者的权限，`[]` = 一个什么都做不了的令牌。两者都是合法请求，
且 `[]` 不会在任何地方被当成假值处理。表单因此把「同我当前权限」做成一个
**独立选项**，绝不用 `[]` 当简写。

**2. 密钥环的 `unreadable` 是重叠轴，不是第三个桶**（`secret_store.py:418-435`）

`inspect_records` 对每条记录**一边**归入 current/stale，**一边独立**试一次解密。
所以恒有 `current + stale == total`，而 `current + stale + unreadable`
描述的是任何一种都不存在的存储。面板把 total 显示成一行 `current + stale`，
unreadable 单独一行并明说「这 N 条已经算在上面了」。

`ERROR` 态**不提供轮换按钮**，且禁用理由直接用 `rotationBlockedReason()` 的
返回值——它以 `unreadable > 0` 为最高优先级，即使服务端同时说
`rotation_ready: true` 也照样禁用，因为那正是会让写入中途抛错的组合。
测试里专门有一条守住这个矛盾载荷。

**3. Frigate 的 PUT 是整对象替换，且 404 是首次配置的正常状态**

`FrigateProviderView` 有个 `configured: bool = True` 字段，但 GET 在没配置时
**先抛 404**，这个字段在任何成功响应里都必然是 true（G-36）。按它分支会让
从未配置过的操作员看到**报错横幅**而不是配置表单——而报错内容本身就是
「Frigate integration is not configured.」。

另外两处：PUT 每次必须带全量字段（无「保持不变」的字段），以及
**凭据 `replace` 会让服务端在 PUT 过程中真的去连 Frigate**，凭据错就直接把
保存打失败（`frigate.py:421-429`）——这个副作用写在界面上了。
还有 `replace` 是**整体替换五个字段**（`frigate.py:411-435`），不像通知那边
只替换一个，所以编辑器五个一起显示并说明这一点。

### 顺带修的一处无障碍缺陷

`Segmented` 是字符串值控件，同屏两个秘密字段各有三个同名按钮
（保持不变 / 替换 / 清空），屏幕阅读器会读成六个无关按钮。整块字段改为
`role="group"` + `aria-label`（而不只是按钮行），两个目标列表也各加了名字。
测试因此可以用 `getByRole("group", {name})` 精确定位，而不是靠按钮序号。

### 验收

| 项 | 结果 |
|---|---|
| `npx tsc --noEmit` | 干净 |
| `npx vitest run` | **808 passed / 56 files**（本轮 +169） |
| `npm run build` | 通过 |
| `git diff main...HEAD -- backend/` | 空 |

新增测试：`api/apiTokens.spec.ts`(18) + `api/secretStore.spec.ts`(11) +
`api/frigate.spec.ts`(20) + `ApiTokensPanel.spec.tsx`(24) +
`SecretStorePanel.spec.tsx`(17) + `FrigatePanel.spec.tsx`(23) +
`SystemView.spec.tsx` 追加 2 条（tab 外壳在 guard 之外）。

**测试不是摆设**：子任务对三个面板都做了变异检查——把实现改回天真写法
（明文缓存进模块变量、`[]` 当继承、裸 datetime、去掉确认弹窗、只用
`rotation_ready` 门控），确认对应用例会红，再还原。

---

## 12. 补齐 5–7/13：备份与恢复 / 机位分组 / 个人账号

三个面板并行委派，契约层自己写，接线统一做。零后端改动。

### 调研先行

先派三个只读 explore 任务把三份后端契约摸清再动手。值得记的是它们各自报出的
东西都属于「照着接口名写会写错」的那一类：

- 备份的 `POST /backups/run` **先 commit 再入队**，所以 503 可能意味着「备份已经
  建好、队列没接上」——`details.backup_persisted: true`。报成失败会诱导重试，
  而重试会建出第二份备份。这是 G-17 / G-23 同一个模式的第三个实例。
- 备份的 `schedule: {}` 是**合法值，意思是「不按计划跑」**，不是校验错误。
- 恢复包是 POST 的**响应字节**而不是可导航的 URL，且**生成后无法作废**。
- 机位分组的 PATCH **按字段合并，但 `camera_ids` 出现即整体替换**。
- 一个分组授权会**递归展开到所有下级分组**，且用户范围**覆盖**角色范围而非求交。
- 个人账号**没有任何自助改资料端点**，`email_verified` 对每个真实用户都是 false。
- `last_seen_at` 只在建会话时写一次，**恒等于 `created_at`**。

### 三个面板里最要紧的判断

**个人账号页没有「编辑资料」。** 不是没做，是后端**没有这个端点**：
`username` / `display_name` 只能通过 `PATCH /users/{id}` 改，而那需要
`user.manage` 且是**别人的账号**。做出来就是一个每次提交都 403 的表单。
所以页面只读展示并说明为什么改不了。同理，Vue 侧的 `AccountPanel.vue` 其实也
只有「会话 + 改密 + 只读资料」——两边都没有邮箱编辑，**不是对等缺口**。

**令牌从系统设置页迁到了 `/account`。** G-32 早就写了它属于「我的账号」；这一轮
正好把个人账号页做出来，顺手迁走。连带删掉了 `ChangePasswordDialog.tsx`——
账号页已经包含改密，同一个动作在两个地方各有一份 UI 是重复而不是便利。

`/account` 路由**刻意不走 `guard(...)`**：`guard` 解析的是导航模块与最低角色，
而这一页恰恰相反，它对 Operator 和 Administrator 是同一页。给一个「改掉泄露的
密码」的入口加角色门禁，会正好把最需要它的人挡在外面。已加测试守住。

### 并行的第二次收获

三个子任务又各自报出了契约层的问题，这一轮更实：

1. **`emptyPolicyForm` 在新建时给出 `credentialsAction: "keep"`**——而创建体的
   `credentials` 是**必填**，所以表单停在「保持不变」就会发一个空密码，然后收到
   一条关于操作员从没见过的字段的报错。已改为新建时默认 `replace`。
2. **`useChangeOwnPassword` 对 400 会弹两次**：`useSave.failure` 返回了消息，
   而表单自己也在 `current_password` 字段上内联显示了同一句。`useSave` 里
   `null` 的语义正是「已在别处呈现」，返回 `null` 消掉重复。
3. **恢复包口令按字符还是按字节？** schema 按字符（`min_length=16`），service
   按 **UTF-8 字节**且字节说了算。16 个汉字是 48 字节，能过；16 个双字节字符
   过不了。常量与 `passphraseAccepted()` 已分开。
4. **`descendantsOf` 的遍历顺序没有意义**（栈式 DFS，出来是 LIFO）。渲染前排序，
   不要对顺序写断言，也不要拿它派生的下标去持久化。

一个 worker 还在自己的递归行组件里抓到了一类值得记住的 bug：**递归行不能接收
父层绑定的回调**——第一版把 `onEdit={() => setEditing(node.group)}` 传了下去，
结果每一行打开的都是分支根节点。

### 验收

| 项 | 结果 |
|---|---|
| `npx tsc --noEmit` | 干净 |
| `npx vitest run` | **949 passed / 62 files**（本轮 +80） |
| `npm run build` | 通过 |
| `git diff main...HEAD -- backend/` | 空 |

新增测试：`api/cameraGroups.spec.ts`(19) + `api/account.spec.ts`(15) +
`api/backups.spec.ts`(34) + `CameraGroupsPanel.spec.tsx`(23) +
`AccountPanel.spec.tsx`(26) + `BackupPanel.spec.tsx`(23) +
`router.spec.ts` 追加 3 条（`/account` 不带角色门禁）。

---

## 13. 补齐 8–9/13：回放操作与诊断 / 摄像机接入向导

13 项里最复杂的两块，拆成 3 个并行任务：回放操作+诊断、接入向导、批量 CSV。
零后端改动。

### 一条决定性发现

**后端没有任何诊断端点。** Vue 的 `PlaybackDiagnosticsPanel.vue` 279 行**全是
客户端的**——`HTMLMediaElement` 状态 + `masterClock` + 本地解析器。`backend/app`
下不存在 `/diagnostics`、`/health`（在 `/api/v1` 下）或 `/metrics`。

所以诊断面板按「本地状态 + 录制策略运行块」建模，**没有发明诊断请求**。这正是
「文档说『没有』之前先去代码里找一遍」那条规则的又一次应用——如果按面板的名字
去猜后端有什么，会凭空造出一个端点。

诊断 worker 进一步报出：**`driftMs` 目前无法渲染**。`MasterPlaybackClock` 被
`useMasterClock` 放在 ref 里（`hooks/useMasterClock.ts:28-32`），没有 store、没有
context、没有 DOM 标记把它发布出来，只给 `cameraId` 的面板拿不到播放头。面板
如实显示「无法读取」并说明原因，而不是显示一个假的 0。修它需要改 hook，超出补齐
范围。

### 三个新的「已持久化却报 503」

手动触发（`details.trigger_persisted`）和接入导入（`details.configuration_persisted`）
是这个模式的**第三、第四个实例**，前两个是通知与备份。四处都遵循同一条规则：
行先 commit 再入队，所以 503 可能意味着**它成功了**。报成失败会诱导重试，而重试
会造出第二份没人分辨得了的记录。四个模块现在各有自己的判别器，形态一致。

### 接入向导的四个陷阱

- **`profile_tokens: null` 是「全部 profile」，`[]` 是「一个都不要」**且会走到
  422（`onvif_onboarding.py:229-230`）。表单初始什么都不勾，自然会发 `[]`。
- **N 个 profile 不等于 N 个机位**：机位按 `video_source_token` 分组
  （`:1149-1176`），多通道设备一次导入产出「<name> 1」「<name> 2」。
- **`confirm_existing_device_id` 必须原样回传**服务端的 `matched_device_id`；
  本地推导会得到**另一个** 409（`:490, :547`）——同一个用户错误两种提示。
- **422 `onvif_connection_failed` 同时覆盖密码错、IP 错、防火墙拦截**
  （`onvif_adapter.py:471-479`），不能按状态码声称知道是哪个。

### 批量接入：100% 客户端，且不可预览

没有服务端端点、没有 CSV 解析、**没有试运行**——`onvif/import` 是唯一的「校验」
而它会写库。所以批量**不原子**、第 N 行失败时前 N-1 行已建成且无回滚。CSV 解析
自己写（要处理 BOM、CRLF、引号内逗号与 `""` 转义、按名而非按位匹配表头），
逐行**串行**执行，可中途停止。`review` 状态与 `failed` 分开：身份不是 `new_device`
的行没有被导入，标成 failed 会诱导重试。

### 并行的第三次收获

三个 worker 报出六个契约层问题，都已修。其中一个是**真设计缺陷**：

> `validateOnvifForm` 把「profile 勾选为空」也算作表单无效。但未触碰的空勾选
> **不是表单填错**，它是请求体表达「全部 profile」的方式。折进表单有效性里，
> 调用方就会拿它去卡**检查设备**这一步——而这条规则与检查毫无关系。

已拆成 `validateProfileSelection`（请求体语义）与 `validateOnvifForm`（表单语义），
再加一个 `validateOnvifForImport` 给真正要提交的那一处用。两个步骤，两个校验器。

其余五个：`refreshOnvifCapabilities` 的参数其实是 **device id** 不是 camera id
（叫 `cameraId` 会让人传错拿 404）；`OnvifImportResult.cameras` 是 `unknown[]`
逼着每个调用点强转；`describeFailure` 是私有的，两个 worker 各自复制了一份中文
映射（现在导出）；`ONVIF_TIMEOUT_BUDGET_MS` 没有总预算（补了 `importBudgetMs`）。

一个 worker 在自己的代码里抓到真 bug：快照初始化跑在 stage 元素进 DOM 之前，
面板会一直说「没有媒体元素」直到第一次媒体事件。测试抓到的。

### 验收

| 项 | 结果 |
|---|---|
| `npx tsc --noEmit` | 干净 |
| `npx vitest run` | **1098 passed / 67 files**（本轮 +95） |
| `npm run build` | 通过 |
| `git diff main...HEAD -- backend/` | 空 |

新增测试：`api/playbackActions.spec.ts`(29) + `api/onboarding.spec.ts`(29) +
`PlaybackPanels.spec.tsx`(33) + `OnboardingWizard.spec.tsx`(31) +
`batchCsv.spec.ts`(27)。

---

## 14. PR-6 切换还需要改什么

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

## 15. 补齐 11/13：摄像机详情抽屉

一行一台摄像机，一个抽屉四个页签。替换掉了原先表格右侧的停靠编辑面板——
同一台摄像机有两个入口，就是名称在一处改、绑定在另一处改的起点。

| 文件 | 行数 | 测试 | 职责 |
|---|---|---|---|
| `components/ui/Drawer.tsx` | 205 | 8 | 抽屉原语：焦点进入 / 焦点陷阱 / 焦点归还 / Esc / 背景滚动锁 |
| `components/cameras/CameraDetailDrawer.tsx` | 210 | 7 | 外壳与四页签，概览页含只读事实 + 编辑表单 |
| `components/cameras/CameraStreamsPanel.tsx` | 445 | 19 | 码流列表、单条检测与轨道回显、六用途绑定编辑 |
| `components/cameras/CameraHealthPanel.tsx` | 250 | 21 | 六层能力健康 |
| `components/cameras/CameraClockPanel.tsx` | 260 | 17 | 时钟偏差与四类「没有读数」的区分 |
| `components/cameras/CameraEditor.tsx`（改造） | 180 | 10 | 去掉外壳后成为纯表单，嵌入概览页 |

### 契约层修正（先于 UI）

1. **`CameraStreamProfile.codec` 被写成了 `video_codec`**。那是 `CameraSummary`
   上的另一个字段；按错误的名字读，每台摄像机的码流编码都会静默变成 `undefined`。
2. **`CameraStreamBinding.stream_profile_id` 标成了可空**。后端是 `uuid.UUID`
   非空且外键 `ondelete="RESTRICT"`，悬空绑定走 API 不可达。原来的 `: "未绑定"`
   分支因此是死代码，且把 `auto` 误画成「没绑定」——`auto` 的 profile 是真实
   存在的，只是由服务端挑。
3. **补齐 `CameraCapabilityHealth` / `CameraStreamDiagnostic` / `verifyStreamProfile`**
   三个此前不存在的契约。`getCameraClock` 早就有定义但零调用方。

### 移植时修掉的 Vue 缺陷（4 个）

1. **Vue 详情面板根本没有健康面板**——`GET /cameras/{id}/health` 在整个 Vue
   前端零调用方。这一块是新增能力，不是移植。
2. **Vue 把四种「没有时钟读数」的原因塌缩成一句话**（`CamerasView.vue:481-497`
   只看 `offset_ms === null`），`unsupported`（设备不支持）与「尚未测量」对
   操作员是完全不同的两件事。前者永远不会好，后者等一下会。
3. **Vue 的健康判定是 `health === "healthy" || |offset| < 200 || |offset| < 1000`
   的或运算**（`:488-496`）——两个来源互相覆盖。React 侧只用 `health`。
4. **Vue 的码流用途绑定会丢 `selection_mode`**：只读 `stream_profile_id`、
   硬编码 `"manual"`，导入期建的 `auto` 绑定在操作员第一次保存时被静默改写。

### Vue 丢弃的检测结果

`POST /streams/{profile_id}/verify` 的响应体在 Vue 侧**整个被丢掉**，
只弹一句硬编码的「已更新最新状态与分辨率」（`CameraDetailStreamsTab.vue:199`）。
而 `ready: false`（轨道在、探测读不到）正好是这类面板最容易骗过操作员的地方。
React 侧把 video / audio 两条轨道和 `verified_at` 都渲染出来，三态分开。

### 新增契约缺口

G-41（`auto` 静默丢弃显式选择 🔴）/ G-42（时钟无按通道刷新入口，且一个 GET
在写库 🟡）/ G-43（三层健康永远无法报告 healthy ⚪）。

### 明确没做的

**实时预览**。Vue 详情面板有 `LiveCameraTile`，但那是一整套独立的播放栈
（会话租约、编解码协商、兼容性回退），在摄像机页重建一份会立刻产生第二套
真相源。直播仍然只在直播页。

## 16. 补齐 10/13：角色 → 权限矩阵

### 先纠正一个此前的错误说法

我此前把「RBAC 收敛成三角色」当成一个待裁决项。**它不是** —— 后端已经把三个
内置角色焊死了：`auth/service.py:71-97` 每次启动按 `BUILTIN_ROLE_PERMISSIONS`
重新同步权限集并强制 `built_in=True`，`auth/admin_service.py:293-298` 对
`built_in` 角色一律 409 `builtin_role_immutable`，**管理员自己也改不了**。

所以真正开放的只有**自定义角色**，需要定的也只是「做不做」。裁决：做。

### 落点

| 文件 | 行数 | 测试 | 职责 |
|---|---|---|---|
| `api/users.ts` | +130 | — | `RoleCreate`/`RoleUpdate`、4 个端点、19 条权限标签与分组、`validateRole` |
| `lib/userMutations.ts` | +70 | — | `useCreateRole` / `useUpdateRole` / `useSetRoleCameraScope` |
| `lib/queries.tsx` | +26 | — | `usePermissions` / `useRoleCameraScope` |
| `components/system/RoleEditor.tsx` | 300 | 11 | 权限矩阵编辑器 + `RoleScopeSection` |
| `components/system/CameraScopeEditor.tsx` | 185 | 3 | 范围编辑器（**从 `UsersView` 抽出，用户与角色共用**） |
| `components/ui/primitives.tsx` | +17 | — | `Textarea` |

### 四个决定

1. **内置三角色不给编辑入口。** 三个按钮会返回 409。列为固定参照。
2. **不提供「全选本组」。** `recording.export` 与 `recording.delete` 不是
   一起开关的东西，整组勾选只会制造部分选中态和第二种出错方式。19 条平铺，
   按域分组显示。
3. **权限与机位范围分两步保存。** 一个角色有两个独立资源、两个端点，变更频率
   差一个数量级（权限一年一次，范围每周）。一个「保存」会让操作员分不清哪半
   落库了。
4. **空权限集合法。** 它是先建角色、后分配的标准用法，不拦；但界面要说清
   后果，而不是把表单标成「没填完」。

### 顺带的去重与诚实性

- 用户侧 `ScopeSection` 与角色范围逻辑完全相同（约 120 行），抽成
  `CameraScopeEditor`。这样 `inherit`/`all` 清空 id 列表这条规则只存在于一处，
  不会只修好一个 owner 类型。`UsersView` 净减约 4.7 KB。
- `PATCH /roles/{id}` 是**整体替换**（`admin_service.py:306-314`），所以矩阵
  永远提交完整集合。已 granted 但目录里已不存在的权限会**显式提示**，而不是
  随保存被静默丢弃。
- 角色写入同时失效 `ADMIN.users`：用户的有效权限是所有角色的并集，改角色会
  改变每个持有者的能力，而用户行本身看起来没变。
- 新增缺口 **G-44**（角色不能删除 🟡）。

## 17. 待裁决

1. **i18n**：React 侧是否重建多语言？这决定 13 项之外是否还有第 14 项。
2. **文件页形态**：日历 + 热力图是否保留，还是接受 PR-5e 的「浏览并导出」？
3. **RBAC 收敛范围**：`SystemAccessControlPanel` 的 1305 行是权限矩阵，
   收敛成三角色后它会大幅简化——但简化成什么样需要先定。
4. **D-2**：仍然待裁决，但它只影响告警页的形态，不影响上面任何一项。
