# D-2 决策材料：录制事件过滤与告警匹配是两套真相源

**状态**：待裁决。本文只提供事实与代价对比，**不给倾向性建议**。
**影响**：阻塞 PR-0（RBAC 收敛批次）与 PR-5（告警规则页），是迁移链上唯一的硬阻塞。
**调研日期**：2026-10-02 · 基线 `codex/frontend-react-shell`

---

## 0. 一句话结论

两套过滤**不能合并**，因为它们的 `zones` 字段在同一个事件上读的是**不同数据**。这不是配置重复，是两种不同的判断。

---

## 1. 字段对照表

两侧都是白名单制：出现未知 key 直接 400（录制 `recording_event_filter_invalid` @ `recordings/policy.py:215`；告警 `alert_policy_match_invalid` @ `alerts/service.py:183`）。但白名单大小悬殊：**录制 3 个 key，告警 12 个**。

| key | 录制侧 `event_filter_json` | 告警侧 `match_json` | 语义一致？ |
|---|---|---|---|
| `labels` | `list[str]` ≤**64** 项 | `list[str]` ≤**128** 项 | 判定一致，**但上限不同** |
| `zones` | `list[str]`，对事件 **`metadata_json["zones"]`（列表）**取交集 | `list[str]`，对事件 **`Event.zone`（标量）**成员判断 | ⛔ **否——读的是不同字段** |
| `min_confidence` | 0–1 浮点 | 0–1 浮点 | ✅ 完全一致（唯一对齐的共享字段） |
| `camera_ids` | —（策略行本身按摄像机唯一） | `list[UUID]` ≤256，校验存在性 | 录制侧无此概念 |
| `sources` | — | `list[str]` ≤128 | — |
| `categories` | — | `list[str]` | — |
| `severities` | — | `list[str]`，取值 ⊆ {info,warning,critical} | — |
| `min_duration_seconds` | — | 0–86400 浮点；`ended_at is None` 直接否决 | — |
| `weekdays` | — | `list[int]` 0–6（周一=0） | — |
| `time_start` / `time_end` | — | `"HH:MM"`，须成对且不相等，支持跨午夜 | — |
| `timezone` | — | str；**不设则整个时间窗判定直接返回 True** | — |

### 1.1 概念相同但结构不同的两处

| 概念 | 录制侧 | 告警侧 |
|---|---|---|
| 时间窗 | `schedule.windows[{days,start,end}]` + `schedule_timezone`，语义是**录像基线窗口** | `weekdays`+`time_*`+`timezone` 四个扁平字段，语义是**告警门控** |
| 摄像机范围 | 策略行按 `uq_recording_policies_camera_id` 唯一（1:1） | `match_json.camera_ids` 列表（1:N，全局策略） |

---

## 2. 决定性事实：`zones` 在两侧读的不是同一个值

这是本材料最重要的一条，直接否掉了「合并为一套」。

Frigate 事件 `entered_zones=["driveway"]`、`current_zones=["driveway","sidewalk"]` 时：

```text
Event.zone                  = "driveway"                    # entered_zones[0]
Event.metadata_json["zones"] = ["driveway", "sidewalk"]      # 全集
```

于是：

| | 读什么 | 配 `zones: ["sidewalk"]` 的结果 |
|---|---|---|
| 录制侧 `triggers.py:106-109` | `metadata_json["zones"]` 取交集 | **触发录像** |
| 告警侧 `service.py:643` | `Event.zone` 成员判断 | **不告警** |

**录像里有这段，但没有告警，而两份配置看起来「完全一致」。**

这不是 bug 可以顺手修掉的程度——它可能是**有意设计**：一个事件跨越多个区域时，录像覆盖全部区域（取证需要），但只对主区域告警（避免重复打扰）。如果是这个意图，那么合并就等于**删掉一种真实存在的行为**。

> ⚠️ **未确认**：代码里没有任何注释说明这个基数差异是历史遗留还是刻意取舍。这是裁决前最值得向原作者确认的一点。它直接决定「合并」是可行还是本质错误。

（ONVIF 路径下两侧等价——`onvif.py:372-376` 把单个 `event.zone` 包成单元素列表。差异只在 Frigate 这类多区域 provider 上出现。）

---

## 3. 结构性障碍：两套配置之间没有连接键

```text
recording_policies   每摄像机恰好一条   (uq_recording_policies_camera_id, models.py:102)
alert_policies       全局，无 camera_id 列 (alerts/models.py:25-63)
                     摄像机范围只能写在 match_json.camera_ids 里
```

即 **1 条录制策略 ↔ N 条全局告警策略**，且单条告警策略可跨多摄像机。任何「同步」方案都是**扇出语义**，必须先回答「一条录制策略同步到哪几条告警策略」「一条多摄像机告警策略从哪台机取过滤」。

---

## 4. 可复现的分叉场景

| # | 场景 | 后果 |
|---|---|---|
| **1** | Frigate 多区域事件，两侧配同样的 `zones` | **录像有、告警无**，且配置看不出差异 |
| **2** | 告警接受 128 个 label，录制只接受 64 | 把告警标签集照抄到录制策略 → 400 |
| **3** | Vue 录制页保存时**始终**写 `min_confidence: 0.6`（`RecordingScheduleView.vue:585`），告警编辑器默认不写该 key | 仅经录制 UI 保存过的策略隐式带 0.6 阈值，两侧独立漂移 |
| **4** | 录制过滤**只对新事件判定**（`triggers.py:166` `if existing is None`），已存在的 trigger 直接放行；告警每次事件重新匹配 | 收紧录制过滤**不会**撤掉已生成的录像，收紧告警过滤**立刻**生效——「改配置」的时间语义不同 |
| **5** | 部署的 Vue 前端**没有录制事件过滤 UI**（`RecordingScheduleView.vue:109-115` 注释：原样回写） | 生产 UI 下 `event_filter_json` 只能经 API 或配置导入写入，用户看不到当前值 |
| **6** | `SystemAlertRulesPanel.vue:275-298` 的 `buildMatch()` **从零重建** match，不保留未暴露的 key | 含 `severities` 的规则在 UI 点一次保存就**静默丢失该字段** |

场景 6 与 D-2 独立，但影响任何改动该面板的方案。

---

## 5. 消费端：唯一的跨模块写入

```text
事件源 → EventService.upsert_provider_event → events 表
          ├─▶ 录制侧 _event_matches（仅对不存在 trigger 的新事件）
          │      匹配 → 写 RecordingTrigger（planned_start = 事件开始 - pre_roll）
          └─▶ 告警侧 evaluate_event → 遍历全部 enabled 策略
                 匹配 → 写 Alert 行 + 通知投递
                        └─ action.protect_recording → 写 RecordingProtection
```

- 两侧判定**完全独立**，`events/frigate.py:65-90` 是两次顺序调用，中间无短路。
- 唯一的跨模块写入是告警动作 `protect_recording`，它**保护已有录像不被清理**，不启动录制，也不受 `event_filter` 影响。

---

## 6. 三种方案的代价

| 维度 | 方案 1：合并为一套 | 方案 2：保持分离 + 同步 | 方案 3：保持分离，告警页只读引用录制过滤作模板 |
|---|---|---|---|
| **后端改动** | 7–8 文件 + Alembic 迁移 | 2–3 文件 + Alembic（同步状态列） | **0** |
| **数据迁移** | 需要，且要处理同名 key 取值冲突 | 需要回填初始同步状态 | **不需要** |
| **影响现有配置** | 是，一方必然降级 | 是，收紧任一侧会改变另一侧行为 | **否** |
| **结构性障碍** | 告警独有的 9 个 key 无处安放 | **无连接键**（§3），扇出语义需先定义 | 无 |
| **前端改动** | Vue 2 文件（录制页需**从零新建**过滤 UI） | Vue 2 文件 + 冲突确认交互 | Vue 1 文件 ~30 行 |
| **React 前端** | AlertsView / SchedulesView 同步 | 同左 | 调整 `AlertsView.tsx` 现有横幅文案 |
| **配置导入导出** | 结构变化，影响已有备份文件 | 需保证往返一致 | 不改 |
| **配置冻结测试** | `test_recording_schema_freeze.py:53` 用子集断言，新增列不违规 | 同左 | 不涉及 |

### 方案 1 的额外前提

即便不考虑代价，方案 1 还需要先回答 §2 的 `zones` 问题。**如果两侧读不同字段是刻意设计，合并就会删掉一种真实行为**——合并前必须先决定「多区域事件到底该不该对次要区域告警」，这是产品决策，不是重构决策。

---

## 7. 既有文档立场（供对照，非本次结论）

- `docs/FRONTEND-MODULE-MAP.md:608-616` 已有 D-2 条目，并写入建议 (b)：**明确分工、删掉一边重叠字段**，理由是「录但不告警」无法用合并表达。同时标注为迁移阻塞项。
- `docs/IMPLEMENTATION-MAP.md:462, 666-670` 记录同一病灶。
- ⚠️ `docs/IMPLEMENTATION-MAP.md:485` 写作 `days_of_week`，代码实为 `weekdays`（`alerts/service.py:283`）——**既有文档的字段清单不可直接采信**，本材料以代码为准。

---

## 8. 裁决前建议补齐的两个事实

1. **向原作者确认 `zones` 基数差异的意图**（§2 的未确认项）。它决定方案 1 是「可合并」还是「本质错误」。
2. **查生产库两套 JSON 的实际取值分布**（两个 `SELECT` 即可），量化场景 1/2/3 的真实发生面。仓库内无生产数据快照，场景 1 是否已在线上发生无法从代码判断。

---

## 9. 与迁移进度的关系

| 批次 | 被 D-2 阻塞的部分 | 不受影响 |
|---|---|---|
| PR-0 | RBAC 收敛与 D-2 同批进行 | 无（该批次整体待定） |
| PR-5 | 告警规则页 `AlertsView` | 摄像机、录制计划、系统设置、文件导出、用户、审计、时间轴 |
| PR-6 | 需要 D-2 落地才能删 `frontend/` | 无 |

**若 D-2 短期无法裁决**：PR-5 的其余六个页面与 PR-4 已完成的媒体页不受影响，可以继续推进。告警规则页可以先按方案 3 的只读引用形态实现——**该形态在任何裁决结果下都不会是错的**，因为它不改变后端行为，只在界面上提供一次显式的「从录制过滤导入」动作。
