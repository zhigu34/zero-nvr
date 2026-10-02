# ADR 0014 — 前端栈迁移：Vue 3 → React 19 + shadcn-admin

Status: **Accepted**（取代 ADR-0013 的第 1、4 条）

Date: 2026-10-02

Supersedes: ADR-0013 第 1 条（保留 Vue 3 基线）与第 4 条（手写 CSS 重写 AppShell）

## Context

### 为什么推翻 ADR-0013

ADR-0013（2026-10-01）曾决定「只移植 shadcn-admin 的设计语言，不动框架」，理由是它的组件是 React、无法在 Vue 中执行。这个技术判断本身没错。

但它没有解决 zero-nvr 真正的问题：**手写 UI 层已经失控**。当前 `frontend/src` 状态：

| 资产 | 规模 | 问题 |
|---|---|---|
| 手写 CSS | ~5300 行 | 两套并存的 token 家族（`--surface-*` 与 `--uf-*`） |
| 最大单文件组件 | `LiveCameraTile.vue` 2591 行 | 承担叠加/布局/状态渲染多重职责 |
| 回放主时钟 + 播放容错 | 6584 行（playback 组件群） | 无测试覆盖的核心媒体逻辑 |
| 组件总量 | 85 个 | 全部手搓，无第三方 UI 基础 |
| 设置页 | 9 个 tab 平级堆叠 | 只按权限显隐，不按启用状态（已部分整改） |

根因不是「写得不好」，而是**没有组件库底座**。Radix UI 提供了无障碍、焦点管理、键盘导航的一整套语义，这些手搓必然不完整。

### 为什么现在值得付这个代价

1. **产品方向已收敛**（`docs/IMPLEMENTATION-MAP.md` §2B）：目标是「类海康 NVR」，平台层正在删减，剩余页面的形态已稳定，重写的返工风险比早期低得多。
2. **技术栈已经现代化过一轮**：ADR-0013 已把 oklch 令牌、radius 标度、shadcn 调色板移植进来了，视觉语言这一层没有额外成本。
3. **零一境处于测试阶段**（ADR 0013 同期确认）：不写 Vue↔React 兼容层，不维护双栈。

### shadcn-admin 是什么

版本 2.2.1，技术栈实测自 `package.json`：

```text
React 19.2 · TypeScript 6 · Vite 8
TanStack Router 1.168 / Query 5.99 / Table 8.21
Tailwind CSS v4.2（@theme inline + CSS 变量）
Radix UI primitives（21 个包）· lucide-react · recharts · zustand
Clerk（认证占位，需替换为 zero-nvr 自己的 session）
```

目录组织（`src/`）：`routes/`（文件路由）、`features/`（按业务域）、`components/`（`layout/` + `ui/`）、`stores/`、`lib/`、`styles/theme.css`。

## Decision

### 1. 全面迁移到 React 19 + shadcn-admin 框架

- 以 shadcn-admin v2.2.1 为基线仓库，**保留其**：`src/styles/theme.css`（oklch 令牌，原样采用）、`src/components/layout/`（AppShell / Sidebar / Header / Main / NavGroup）、`src/components/ui/`（shadcn 组件集）、`src/routes/` 的文件路由组织方式、TanStack Table 的数据表模式。
- **必须替换**：`@clerk/react` → zero-nvr 自有认证（现有 cookie session + `useAuthStore` 等价物）；`src/stores/` 中 Clerk 相关切片 → 自有 store。
- **不引入**：Clerk、TanStack Router 的 `beforeLoad` 鉴权（改用 zero-nvr 的权限模型）。

### 2. 保留 shadcn-admin 的导航分组模式

它把导航分为「Overview / Management / Others / Documentation」四组。zero-nvr 映射为**产品语义**分组，而非照抄：

```text
监控        Live · Playback · Timeline
管理        Cameras · Recording Schedules · Events · Alerts
存储        Storage · Files
系统        System · Users · Audit
```

逐页的功能定义、数据来源与边界见 `docs/FRONTEND-MODULE-MAP.md`。分组不是装饰——它直接回应「设置页 11 个 tab 平级堆叠」的原始问题。

### 3. 迁移分批推进，禁止 Big-Bang 替换

**硬约束：Vue 应用在 React 迁移完成前必须保持可运行。**

实施方式：新建 `frontend-react/`，与现有 `frontend/` 并存，逐步迁移路由。两套前端由不同路径服务（`/` → Vue，`/next/*` → React），迁移完成一个模块就切一个入口，最后统一切换。

理由：媒体核心（回放主时钟 2813 行、hls.js 集成、直播墙）没有测试保护，一次性替换等于把整个产品置于「无法验证」的状态。

### 4. 后端 API 契约不变

React 前端复用现有 `backend/app/api/v1` 的全部 161 个端点（AST 统计 `@router.{get,post,put,patch,delete}` 装饰器，14 个 router 文件）。`src/api/*.ts` 的 13 个文件按 TanStack Query 的 hook 模式重写，但**请求/响应 schema 不动**。后端不因本次迁移做任何修改。

### 5. 保留需要重写而非复制的媒体资产

以下不能从 shadcn-admin 获得，必须基于现有实现重写，且要补测试：

| 资产 | 现有规模 | 迁移要求 |
|---|---|---|
| 回放主时钟 / 播放容错 | `PlaybackView.vue` 2813 行 | 重写为 React 组件 + `PlaybackClock` 纯逻辑模块，**必须补 vitest 测试**（当前无覆盖） |
| 直播墙 / 瓦片 | `LiveCameraTile.vue` 2591 行 | 拆分：`<video>` 容器、`useWebRTCTransport`、`useHlsTransport`、布局算法 |
| hls.js 传输选择 | `src/live/playback.ts` 190 行 | 直接移植（H.265 只能走 HLS、子码流优先 HLS 的规则要保留） |
| i18n | `i18n.ts` 3587 行 | 迁到 `react-i18next` 或 `vue-i18n` 兼容层，**文案内容零改动** |

### 6. i18n 与 RBAC 是迁移中不可回退的部分

- **i18n 键名冻结**：现有 3587 行文案的键结构不变，只换加载方式。`i18n.spec.ts` 的守卫测试（如 gap reason 完整性检查）必须继续通过。
- **RBAC 收敛先行**：迁移前先把 19 个细粒度权限点 + `principal_camera_scopes` 摄像头级授权收敛为 3 个固定角色（Administrator / Operator / Viewer）。**理由**：权限模型是每个页面的守卫逻辑，迁移中同时改权限和改框架会让问题无法定位。

## Consequences

### 正面

- 获得 Radix UI 的无障碍与键盘导航语义，85 个手搓组件可逐步退役。
- `data-table` 模式（TanStack Table + shadcn）直接适用于机位列表、事件列表、录像目录、审计日志——这四块占了当前一半的表格代码。
- 后续新增页面有现成组件可拼，不再从零画。

### 负面（必须正视）

- **现有 273 个前端测试全部失效**。`@vue/test-utils` 无法测 React。54 个 spec 需要逐个重写为 React Testing Library。这是本次迁移最大的隐性成本。
- **媒体核心要从「已有可用」变成「重新实现」**。回放主时钟、直播墙、hls 传输层在迁移窗口内存在功能回退风险。
- **两套前端并存期**：`frontend/` 56015 行代码不会立即消失，构建体积与仓库复杂度临时翻倍。
- **放弃 Vue 生态**：如果未来需要引入 Vue 侧现成 NVR 组件库，将不可用。

### 中性

- 视觉风格变化对用户可见（shadcn-admin 的中性色 vs 现有 UniFi 风格），需要一次走查。
- `@tanstack/react-query` 取代手写 fetch + store 模式，缓存策略需重新设计（录像时间轴对数据新鲜度敏感）。

## Alternatives considered

**A. 保留 Vue，只移植设计语言**（即 ADR-0013 原方案）
- 优点：不重写媒体核心，测试全部保留。
- 否决理由：手写 UI 层失控的根因（无组件库底座）未解决；无障碍语义缺失需长期自维护。

**B. 双轨并存**（React 新页面 + Vue 保留媒体页）
- 优点：风险最低。
- 否决理由：两套构建、两套路由、两套状态管理，且 shadcn-admin 的设计语言在两套技术栈下会产生视觉漂移。长期维护成本高于一次性迁移。

**C. 引入 shadcn-vue 而非 React**
- 优点：保留 Vue，可复用现有测试与组件。
- 否决理由：shadcn-vue 社区规模远小于 React 版，Radix 原语覆盖不全；且用户明确选择了 shadcn-admin 本体。

## Implementation order

1. **PR-1 骨架**：`frontend-react/` 初始化，移植 theme.css + layout 组件，产出静态原型供走查 —— **已完成**（`6ec78ed`）
2. **PR-2 认证与外壳**：登录、session、AppShell 导航分组、权限守卫 —— **已完成**（认证门禁、TanStack Router 路由树、角色过滤、用户菜单）
3. **PR-3 只读页**：Dashboard / Cameras 列表 / Events / Storage 列表（TanStack Table 模式验证）
4. **PR-4 媒体页**：Live / Playback（hls.js 传输层 + 播放容错 + 补测试）
5. **PR-5 写操作页**：机位编辑 / 录制计划 / 告警规则 / 系统设置
6. **PR-6 切换**：删除 `frontend/`，`frontend-react/` 升为唯一前端

### PR-2 的两个既定事实

**权限按模块整体授予，粒度已由后端决定而非前端猜测。** 逐模块核对 `require_permission` 调用点后确认：存储模块**全部**端点要 `storage.manage`，用户模块要 `user.manage`，审计要 `audit.view` —— 后两者 Operator 角色都没有。因此**存储、用户与权限、审计日志三页只对管理员开放**，而系统设置对所有角色可看、仅管理员可写。前端按角色名判定，不按 19 个细粒度权限点，以便收敛后不波及页面。

**路由路径字面量写死，配套测试锁一致性。** 用 `moduleRoute(key: string)` 之类的辅助函数会把 `path` 退化成 `string`，TanStack Router 就无法为 `Link to={...}` 生成类型。改为 12 条路由逐条显式声明，代价是路径在 `routes/router.tsx` 与 `lib/navigation.ts` 各存一份——`routes/router.spec.ts` 断言两者一致。

## Related

- ADR-0013 — 前一版设计语言决策，其框架保留部分被本 ADR 取代
- `docs/FRONTEND-MODULE-MAP.md` — 12 个模块的逐页功能定义、路由表、Vue 页面映射与待裁决问题（本文档的配套）
- `docs/IMPLEMENTATION-MAP.md` — 三方职责与功能实现地图（本迁移不改后端契约）
- `docs/specs/0020-live-view-media-session.md` — 直播媒体会话规范
- `docs/specs/0006-historical-playback-timeline.md` — 回放时间轴规范
