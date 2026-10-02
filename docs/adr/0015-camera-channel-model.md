# ADR 0015 — 摄像机按「通道」管理：通道是系统资产，摄像头是可换的绑定

Status: **Proposed**（待裁决；本文不含任何已落地代码）

Date: 2026-10-02

Related: ADR-0008（产品事实持久化、运行态派生）、ADR-0012（v1 架构冻结基线）、
`docs/FRONTEND-CONTRACT-GAPS.md` G-38

Supersedes: 无。本文只描述一个尚未实现的模型，不改变任何现状行为。

## Context

### 产品意图

摄像机管理应当对齐海康 NVR 的心智模型：

- **通道**是系统里的固定位置，编号一旦分配就不再变。
- **摄像头**是绑在通道上的东西，可以随时换——ONVIF 换成 RTSP、换一台物理设备、
  换密码，都不应该动通道。
- 通道上挂的东西（录制计划、录像保护、告警范围、分组、直播布局、录像文件）
  与「背后是哪台设备」无关，因此换设备时它们全部保持不变。

这个模型直接对应一个今天非常刺眼的运维事实：**改一个摄像机密码，代价是删掉机位
重建整套配置**（G-38）。

### 现状：`Camera` 行已经就是那个「通道」，但有一个概念是反的

先把已经成立的部分说清楚，因为重构面比想象的小：

**已经稳定、不需要动的东西**——所有面向用户的引用都走 `Camera.id`（UUID），
不碰设备：录制策略、录像保护、告警、机位分组、直播布局、录像片段、事件。
`Camera` 行本身就是那个稳定槽位。`retired_at` + `POST /cameras/{id}/retire` /
`/restore`（`cameras/service.py:477-504`）已经提供了「摘掉但不销毁」的机制，
而且 restore 刻意不自动启用（`:494-496`），这个设计是对的。

**反掉的那一个概念**——`Camera.channel_key`（`cameras/models.py:225`）不是系统
分配的通道号，而是**设备自己报上来的标识**：

| 来源 | `channel_key` 取值 | 位置 |
|---|---|---|
| 手动 RTSP | 硬编码 `"manual-0"` | `cameras/service.py:188` |
| ONVIF | `video_source_token`（设备自报） | `onvif_onboarding.py:1170` |

唯一约束是 `uq_cameras_device_channel (device_id, channel_key)`
（`models.py:203-207`）——**通道身份的作用域是「一台设备之内」**。所以两台不同的
手动摄像机都叫 `manual-0`，这不冲突，只因为唯一键带了 `device_id`。

这意味着系统里**根本不存在**「通道 1 / 通道 2」这种东西。列表按名称字母序排
（`service.py:37`），没有编号，也不可能有稳定编号。

### 现状为什么让「换摄像头」不可能

`_reconfigure_existing`（`onvif_onboarding.py:590`）是今天唯一能轮换已录入 ONVIF
设备凭据的路径。它先做一次拓扑校验（`:626-648`）：对每个已记录的 profile，
要求设备这次报的 `video_source_token` 与 `camera.channel_key` 完全相等，否则
抛 409 `onvif_device_topology_changed`，`details` 里带着 `camera_id` 与
`profile_token`。

这个守卫本身是合理的（防止把 A 通道的录像地址悄悄改到 B 通道上）。但它和
「通道由系统拥有」直接冲突：**只要物理设备换了、或者设备重启后重排了通道，
系统就拒绝接受新凭据**。

后果在运维上很难解释：操作员填了新密码 → 设备用新密码**认证成功**、profile 全部
读回来了 → 然后系统在存凭据之前甩一个 409。新密码是有效的，只是不被接受。
（凭据轮换发生在 `:745-792`，拓扑校验在 `:626-648`，所以是干净回滚，不是半写。）

**所以「换一台设备到已有通道」这件事，被 `channel_key` 的定义从结构上堵死了。**

### 现状还有一处会静默出错

`CameraUpdate` 接受 `manufacturer` / `model` / `form_factor`
（`cameras/schemas.py:46-48`），但 `Camera` 表上**没有这三列**。写入逻辑把它们
落到 `Device` 上（`cameras/service.py:437-448`）。两种结局都不是编辑者想要的：

1. 机位没有 `device_id` → 静默丢弃，返回 `200`。
2. 多通道 NVR 的 N 个机位共用一台 `Device` → 写入**同时改掉全部 N 个通道**，
   而审计事件只记成 `camera.update` 一个机位（`cameras/api.py:1519-1528`）。

第 2 种比第 1 种危险得多：它成功、它有审计、它看起来是对的。React 侧的
`CameraEditor` 已经不提供这三个输入框，但当时的理由只覆盖了第 1 种。

### 还有一个约束：不能直接把 `channel_key` 改造成系统编号

ONVIF 事件路由靠 `channel_key` 把设备事件映射到机位（`events/onvif.py:113-119`，
按 `camera.channel_key == token` 匹配）。事件的 token 来自设备，改不了。

所以**必须拆成两个字段**，而不是重命名或复用现有的一个。

## Decision（待裁决）

把当前被 `channel_key` 一词承担的两件事拆开，并让通道身份归属于系统。

### 1. `cameras.channel_no`：系统拥有的稳定编号

- 类型 `Integer`，**全局唯一**（不是 per-device）。
- 分配一次，永不改变；退役后不复用（复用会让历史录像的归属变得不可解释）。
- 对外展示为「通道 1」「通道 2」。列表默认按 `channel_no` 排序，不再按名称。

### 2. `cameras.device_channel_key`：设备自报的通道标识

- 保留现有 `channel_key` 的语义与取值来源，ONVIF 事件路由照旧用它。
- 作用域仍是「一台设备之内」。

### 3. `PUT /cameras/{id}/binding`：换掉通道背后的绑定

这是让模型成立的关键端点，也是 G-38 的正解。语义与通知 / 备份 / Frigate 的
`keep|replace|clear` 动词协议一致：

```json
PUT /api/v1/cameras/{camera_id}/binding
{
  "source": "onvif" | "manual_rtsp",
  "device": { "host": "...", "port": 80, "adapter_type": "onvif" },
  "credentials_action": "keep" | "replace" | "clear",
  "credentials": { "username": "...", "password": "..." },
  "channel_key": "video_source_token 的新值，仅 ONVIF 需要"
}
```

调用方已经拥有的通道上的一切（`camera_id` 指向的行、录制策略、录像保护、
告警范围、分组、直播布局位置、录像文件）**一个都不动**。变的只有
`device_id`、`device_channel_key` 与码流 profile / 凭据 secret。

### 4. 通道级与设备级字段显式分家

`manufacturer` / `model` / `form_factor` 必须二选一：要么搬成 `Camera` 自己的列
（通道级，符合直觉），要么从 `CameraUpdate` 删掉、只允许在设备级编辑。
**不能维持现状**——现状是「一个通道级 API 会静默改到设备级」，这是第 2 种结局
的温床。

### 5. 前端呈现

摄像机页主列表变成「通道」列表：通道号（稳定）+ 名称 + 当前绑定摘要
（`adapter_type`、地址、在线状态）。编辑通道时不出现「换设备来源要重建机位」
这类提示，因为换绑定是编辑的一部分。

## Consequences

### 正面

- **G-38 从根上消失**：换密码、换地址、换设备来源都不再需要删除重建。
- 「通道 3 的摄像头坏了，换一台新的上去，计划和保护都不动」成为可执行操作。
- 设备级与通道级字段不再混淆，审计记录的粒度与实际影响面一致。
- 通道号稳定后，可以在 UI、录像文件名、导出里使用人类可读且不会漂移的标识。

### 代价

- **需要后端改动**：数据模型迁移（新列 + 回填）、事件路由改读新列、
  新端点、配置导入导出格式变更（`system/config_export.py:218`）。
- **与 ADR-0014 决策 4（契约冻结、零后端改动）冲突**。这需要单独裁决，
  不能顺手做。
- `channel_no` 的回填要一次性决定历史通道的编号顺序。建议按
  `created_at, id` 分配，之后不再变动。
- 配置导入导出的 `channel_key` 语义要明确：导出设备侧标识（`device_channel_key`），
  通道号在导入时重新分配，否则跨实例导入会撞号。

### 不做会怎样

维持现状的话，下面这些继续成立：

- 手动 RTSP 摄像机换密码 = 删除重建，丢失该机位上全部计划与保护。
- 换物理设备到已有通道 = 做不到（409 `onvif_device_topology_changed`）。
- 多通道 NVR 上「改厂商」会静默影响所有通道。
- 用户界面里不存在「通道」这个概念，只有按名称字母序排列的「机位」。

## 落地顺序建议

1. 加 `channel_no` 与 `device_channel_key` 两列，回填，不改行为（纯加法）。
2. 事件路由改读 `device_channel_key`，删掉旧列。
3. 加 `PUT /cameras/{id}/binding`，前端「重新导入以更新凭据」改走这个端点，
   不再依赖 `POST /cameras/onvif/import` 的隐式重配置副作用。
4. 解决 `manufacturer` / `model` / `form_factor` 的归属。
5. 前端改为通道列表。

前三步之间每一步都可以独立发布，第 1 步对现有行为零影响。
