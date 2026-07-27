# OpenChronicle UserEnter Signal V2 修改汇报

日期：2026-07-27

## 1. 修改背景

第一轮已经完成物理 Enter Signal 的基础接入：

- 普通 Return 和小键盘 Enter 均输出 `UserEnter`；
- Enter Signal 与 Snapshot 分开持久化；
- Signal 不受普通事件和 Snapshot 去重影响；
- Enter 后执行 AX-first Capture；
- Capture 失败、队列拥堵或应用切换时，Signal仍然保留；
- Signal 使用隐私字段白名单，不保存输入原文和 element value；
- 自动化、Swift 编译和多应用手动测试均已通过。

第一轮证明了 UserEnter 可以被可靠捕获，但第二轮 Review 指出了长期运行场景中的
数据建模、Capture 调度、并发一致性、隐私时序、shutdown 恢复和 Schema 演进问题。

本轮修改目标是：

> 每次有效物理 Enter 必须产生且只产生一条独立、持久化、不可重复的 Signal；
> Capture 可以合并、复用、延迟或明确失败，但不能导致 Signal 丢失、状态倒退、
> 隐私泄露或跨应用、跨窗口错误关联。

## 2. 本轮修改范围

本轮修改文件：

- `resources/mac-ax-watcher.swift`
- `resources/mac-ax-helper.swift`
- `src/openchronicle/capture/signal_store.py`
- `src/openchronicle/capture/event_dispatcher.py`
- `src/openchronicle/capture/scheduler.py`
- `src/openchronicle/capture/watcher.py`
- `src/openchronicle/paths.py`
- `tests/test_signal_store.py`
- `tests/test_event_dispatcher.py`
- `tests/test_capture_metadata.py`

未修改或纳入本轮工作的已有文件：

- `src/openchronicle/cli.py`
- `docs/background-silent-run-guide.md`
- `docs/troubleshooting-swift-bridging.md`

## 3. 八项修改完成情况

### 3.1 修正 ID 模型

#### 第一轮问题

第一轮让 `UserTextInput` 和 `UserEnter` 共用 `signal_id`。这样可以建立关联，
但同一个 ID 同时代表两个不同对象，容易在持久化、去重、索引和重放时产生主键
语义歧义。

#### V2 实现

现在每类对象拥有独立主键：

| 对象 | 主键 |
|---|---|
| UserEnter | `signal_id` |
| UserTextInput | `event_id` |
| Capture Group | `capture_request_id` |
| Capture Attempt | `attempt_id` |
| Snapshot | Snapshot 文件 ID |

`UserTextInput` 和 `UserEnter` 通过以下字段关联：

```text
UserTextInput.correlation_id
UserEnter.correlation_id
UserTextInput.related_signal_id → UserEnter.signal_id
```

Swift watcher 在收到 Enter 时：

1. 生成新的 `signal_id`；
2. 生成新的 `correlation_id`；
3. 如有待输出文字，先生成带独立 `event_id` 的 `UserTextInput`；
4. `UserTextInput.related_signal_id` 指向即将输出的 `UserEnter`；
5. 再输出 `UserEnter`。

无待输出文字时，仍然只产生 `UserEnter`，不产生空的 `UserTextInput`。

#### 解决的问题

- 不同持久化对象不再共用主键；
- watcher event 重放可以按对象主键独立幂等；
- Capture Group 和多个 Signal 可以建立多对一关系；
- 后续索引、查询和 Schema 演进具有明确对象边界。

### 3.2 固定 follow-up 改成条件式 Capture

#### 第一轮问题

第一轮对每次 Enter 固定执行：

```text
T+200ms primary Capture
T+1000ms follow-up Capture
```

该设计可以覆盖 800ms 后才更新的页面，但即使 primary 已取得高质量新 Snapshot，
follow-up 仍可能继续执行。第一轮 20 次 Enter 压力测试出现了 5 条最终
`queue_full`，说明固定双 Capture 会放大请求量。

#### V2 实现

T+200ms 的 primary 保留，follow-up 根据结果决定：

- primary 为 `new` 且 `quality_status=good`：
  - 结果已经明确；
  - 不再执行 follow-up。
- primary 为 `reused` 或 `unchanged`：
  - 允许最多一次 follow-up。
- primary 为 degraded：
  - 只有错误原因位于显式可重试白名单时才 follow-up。
- `privacy_blocked`、`app_changed`、`permission_denied`、`screen_locked`：
  - 不执行 follow-up。

当前可重试原因使用明确集合，不再根据任意 degraded 状态自动重试：

```text
ax_incomplete
capture_unavailable
duplicate_without_ref
queue_full
temporary_capture_error
```

#### 自然 AX 事件

等待 follow-up 期间，同应用、同进程和同窗口的自然 `AXValueChanged` 可以提前触发
一次 `natural_event` Capture。

自然事件不会仅凭“事件出现”就完成 Signal：

1. 验证候选 Capture Group；
2. 执行真实 Capture；
3. Capture 成功后完成关联；
4. Capture 失败或仍可重试时，恢复 follow-up 机会。

#### 解决的问题

- 高质量 primary 不再产生无价值的重复 Capture；
- 慢页面仍然拥有第二次观察机会；
- 自然 AX 变化可以减少固定等待；
- 队列压力和 `queue_full` 风险降低；
- 不可重试或隐私阻止场景不会继续采集。

### 3.3 Capture Group 与多 Signal 回写

#### 第一轮问题

同一窗口快速按五次 Enter 时，第一轮可能安排五次 primary 和五次 follow-up。
物理 Enter 不能合并，但重复 AX/Screenshot Capture 可以合并。

#### V2 实现

增加 `_CaptureGroup`，包含：

```text
capture_request_id
bundle_id
pid
window_identity
window_identity_confidence
member_signal_ids
created_at
due_at
phase
attempt_id
running
```

调度规则：

- 每次有效 Enter 仍然创建独立 Signal；
- 同应用、同进程和同窗口的 Enter 可以加入同一个等待执行的 Group；
- 同一窗口最多一个运行中 Group和一个等待 Group；
- Capture 开始时冻结本次 `member_signal_ids`；
- Capture 开始后到达的新 Enter 进入等待 Group；
- 新成员不会反复延长正在执行 Group 的 `due_at`；
- Group 完成后，将同一个结果分别回写给所有成员；
- 多成员结果使用 `association_mode=coalesced`；
- 每个成员仍保留独立 `signal_id` 和 attempt ledger。

自动化测试已验证：

```text
同窗口快速输入 5 个 UserEnter
→ 5 个独立 Signal 文件
→ 1 次共享 Capture 请求
→ 5 个成员均获得相同 result_snapshot_ref
→ association_mode=coalesced
```

`queue_full` 不再直接作为普通最终状态。primary 阶段队列拥堵先进入
`deferred_queue_full`，后续机会用尽后再转成 `unresolved`。

#### 解决的问题

- 高频 Enter 不再线性放大 Capture 请求；
- 保留物理事件数量准确性；
- 多 Signal 可以共享相同界面证据；
- Capture 合并不影响每条 Signal 的独立身份和状态。

### 3.4 区分按键前 Context 和按键后 Result

#### 第一轮问题

第一轮只有一个 `snapshot_ref`，无法区分：

- Enter 前最近一次 Snapshot；
- Enter 后内容相同，因此复用旧 Snapshot；
- Enter 后真正产生的新 Snapshot。

应用切换时，切换前 Snapshot 还可能被误读成 Enter 后结果。

#### V2 实现

Signal V2 拆分为：

```text
context_snapshot_ref
result_snapshot_ref
post_capture_status
quality_status
capture_attempts
```

`context_snapshot_ref` 在 Enter 进入 dispatcher 时冻结，只复用当前已知的同应用
Snapshot。

结果语义：

```text
Enter 前 A，Enter 后变化为 B
→ context=A, result=B, status=new

Enter 前 A，Enter 后确认内容相同
→ context=A, result=A, status=reused

Enter 后应用或高置信度窗口发生变化
→ context=A, result=null, status=app_changed
```

每次 Capture Attempt 记录：

- `attempt_id`
- `capture_request_id`
- `phase`
- `association_mode`
- `requested_at`
- `due_at`
- `started_at`
- `completed_at`
- `bundle_id`
- `window_identity`
- `window_identity_confidence`
- `status`
- `snapshot_ref`
- `quality_status`
- `error_reason`

支持的 phase：

```text
primary
natural_event
follow_up
recovery
```

#### 窗口身份

Swift watcher 和 AX helper 现在尝试读取 `AXWindowNumber`。

高置信度身份：

```text
bundle_id + pid + AXWindowNumber
```

无法取得窗口编号时，使用：

```text
bundle_id + pid
window_identity_confidence=low
```

高置信度窗口身份不一致时，Capture runner拒绝关联结果。

#### 解决的问题

- Enter 前证据和 Enter 后结果不再混淆；
- `reused` 表示 Enter 后重新观察并确认内容相同；
- 应用或窗口切换时不会把旧 Snapshot 描述成新结果；
- 每次 Capture 的时间、质量和失败原因均可追踪。

### 3.5 并发更新、Revision 和幂等

#### 第一轮问题

原子 replace 只能防止半截 JSON，不能防止两个异步任务同时读取旧对象并相互覆盖。

例如：

```text
primary 读取 revision 1
follow-up 读取 revision 1
primary 写入成功 Snapshot
follow-up 用旧对象写入 queue_full
```

最终文件虽然仍是合法 JSON，但 primary 的成功结果可能丢失。

#### V2 实现

##### Capture daemon singleton

- 同一 OpenChronicle 数据根目录只允许一个 Capture daemon；
- 使用 `fcntl.flock` 获取操作系统文件锁；
- 第二个 daemon 无法获取锁时抛出明确的 `already_running`；
- 进程崩溃或 `kill -9` 后，操作系统自动释放锁。

锁文件：

```text
<OPENCHRONICLE_ROOT>/.capture-daemon.lock
```

##### SignalStore 串行更新

- 每个 `signal_id` 使用独立 `RLock`；
- 所有关联更新统一调用 `update_linkage()`；
- 获得锁后重新读取磁盘最新对象；
- 每次只合并本次更新字段；
- 不使用 callback 前缓存的完整旧对象覆盖文件；
- 每次有效更新执行 `revision + 1`；
- `expected_revision` 不一致时基于最新 revision 合并；
- 相同 `attempt_id` 重复提交时幂等更新，不重复追加；
- Signal 核心字段在创建后不由 Capture 更新修改；
- `new/reused/unchanged` 成功结果不能被后续失败、queue-full 或 shutdown 降级。

##### Snapshot 文件名

Snapshot 文件名由：

```text
毫秒时间戳 + UUID
```

组成，避免同一毫秒并发文件名冲突。

#### 解决的问题

- primary 成功不会被 follow-up 失败覆盖；
- 两个 daemon 不会同时写同一数据目录；
- callback 重放不会重复创建 attempt；
- Signal JSON 始终可解析且 revision 可追踪；
- Snapshot 文件不会因并发时间戳相同而覆盖。

### 3.6 隐私策略前移

#### 第一轮问题

第一轮 excluded bundle 主要在 Python 侧过滤，但 Swift 在输出 `UserEnter` 前会先：

```text
flushText(reason="enter")
```

因此被排除应用的 `UserTextInput` 可能已经进入 stdout 和 dispatcher，之后 Python
才丢弃 `UserEnter`。“Signal 没有落盘”不等于“文字从未进入采集链路”。

#### V2 实现

Python 配置继续作为唯一真实来源：

```text
excluded_signal_bundle_ids
```

启动 watcher 时，Python 将以下信息作为参数传给 Swift：

- 排除 bundle 列表；
- `privacy_policy_version`。

Swift watcher：

- 在 `flushText()` 前检查 bundle；
- excluded app 不输出 `UserTextInput`；
- excluded app 不输出 `UserEnter`；
- 丢弃该应用待输出文本；
- UserTextInput 和 UserEnter 均携带相同策略版本；
- 缺少策略或版本不支持时以退出码 3 拒绝启动。

Python dispatcher：

- 对 `UserTextInput`、`UserEnter` 和其他后续 Capture 事件再次检查 bundle；
- 即使 Swift 输出异常，Python 仍执行防御性阻止；
- watcher 以退出码 3 结束时不进行不安全重启。

`input_target.identifier` 新增：

- 最大长度限制；
- 控制字符拒绝；
- 多行或疑似动态长内容清理。

#### 解决的问题

- excluded app 内容不会先离开 Swift 再被 Python 丢弃；
- Swift 和 Python 使用同一隐私策略来源和版本；
- 策略缺失时不会默认开放采集；
- identifier 不再被默认视为完全安全的结构字段。

### 3.7 Shutdown、重启和 Recovery

#### 第一轮问题

第一轮 shutdown 会取消尚未运行的 Enter timer：

```text
Enter 已持久化
→ 100ms 后 shutdown
→ T+200ms primary 被取消
→ Signal 可能永久保持 pending
```

#### V2 实现

shutdown 使用 producer → consumer 顺序：

1. 停止 watcher，不再产生新事件；
2. dispatcher 进入 draining；
3. 取消尚未执行的 Enter timer；
4. 将未完成 Signal 标记为 `deferred_shutdown`；
5. 追加 `cancelled_shutdown` attempt；
6. Capture worker排空已经进入队列的任务。

如果 primary 已成功而 follow-up 尚未开始：

- 保留 `result_snapshot_ref`；
- 保留成功状态；
- shutdown 不得将成功结果降级。

#### 启动恢复

在启动 watcher 前：

1. 扫描 signal-buffer；
2. 检查或迁移 Schema；
3. 查找 `pending/running/deferred_queue_full/deferred_shutdown`；
4. 旧 `running` 追加 `abandoned_process_exit`；
5. 已有可信结果时不再补采；
6. 未超时且窗口身份为高置信度时，允许一次 recovery Capture；
7. 超时转成 `unresolved/recovery_expired`；
8. 窗口身份无法可靠确认时转成 `unresolved/context_changed`。

Recovery 使用独立：

```text
phase=recovery
association_mode=recovery
attempt_id
```

#### 解决的问题

- shutdown 后不再留下无解释的永久 pending；
- DRAINING 前已经进入 dispatcher 的 Enter 仍然保留；
- 成功 primary 不会因取消 follow-up 而倒退；
- 进程异常退出后，旧 running 有明确处理路径；
- 无法证明上下文一致时宁可 unresolved，不进行错误补采。

### 3.8 Schema 版本和状态机

#### V2 Schema

新增版本字段：

```text
signal_schema_version = 2
capture_schema_version = 2
privacy_policy_version = 1
```

版本常量由存储层统一写入，调用方不自行声明。

#### V1 迁移

第一轮明确带有：

```text
schema_version = 1
```

的 UserEnter Signal 支持原子、幂等迁移到 V2。

迁移规则：

- 旧 `snapshot_status=captured` → `post_capture_status=new`
- 旧 `snapshot_status=reused` → `post_capture_status=reused`
- 旧 `snapshot_status=duplicate_without_ref` → `unchanged`
- 旧 `snapshot_status=queue_full` → `deferred_queue_full`
- 旧 `snapshot_status=app_changed` → `app_changed`
- 无法从 V1 确认的 context 保持 null；
- 不伪造不存在的历史 Capture Attempt；
- 添加 `migrated_from_schema_version=1`；
- 重复启动不会重复迁移。

缺少版本的文件视为 legacy；未知或未来版本：

- 不修改；
- 不降级；
- 不触发 Recovery Capture；
- 输出 `unsupported_schema` 诊断。

#### 状态拆分

证据质量：

```text
quality_status = good | degraded | failed
```

Enter 后结果：

```text
post_capture_status
```

成功终态：

```text
new
reused
unchanged
```

非终态：

```text
pending
running
deferred_queue_full
deferred_shutdown
```

明确终态：

```text
unresolved
app_changed
privacy_blocked
```

状态规则：

- 成功终态不能被失败或 shutdown 降级；
- 非法状态转换被拒绝并记录；
- follow-up 和 recovery 机会结束后，deferred 状态转成成功或 unresolved；
- quality 与业务关联状态不再混入同一个字段。

## 4. 更新后的数据流

```text
物理 Enter
  → Swift 检查 privacy policy
  → 生成 signal_id + correlation_id
  → 如有待输出文字：
       UserTextInput(event_id, correlation_id, related_signal_id)
  → UserEnter(signal_id, correlation_id)
  → Python 再次检查 excluded bundle
  → Signal V2 原子、幂等落盘
  → 冻结 context_snapshot_ref
  → 加入同窗口 Capture Group
  → T+200ms primary
       ├─ new + good → 完成，不 follow-up
       ├─ reused/unchanged → 最多一次 follow-up
       ├─ retryable degraded → 最多一次 follow-up
       ├─ natural AX success → 提前完成
       ├─ queue_full → deferred，保留后续机会
       └─ app/privacy/window mismatch → 明确终态
  → update_linkage() 对所有成员串行回写
  → shutdown/restart 时执行 deferred/recovery 收敛
```

## 5. 自动化和编译结果

最终验证结果：

```text
Python full suite: 139 passed
Changed-file Ruff: All checks passed
git diff --check: passed
Swift mac-ax-watcher build: passed
Swift Enter self-tests: passed
Swift mac-ax-helper build: passed
```

本轮新增或更新的自动化覆盖：

- V2 Signal Schema；
- ID 和事件关联关系；
- UserEnter 幂等；
- UserTextInput 独立 event ID；
- identifier 隐私清洗；
- revision 严格递增；
- stale update 基于最新对象合并；
- attempt ID 幂等；
- 成功状态不可降级；
- 五 Signal 合并一次 Capture；
- Capture Group 多成员结果回写；
- high-quality primary 取消 follow-up；
- reused primary 允许一次 follow-up；
- context/result 字段；
- 应用切换拒绝关联；
- shutdown 转 `deferred_shutdown`；
- singleton daemon lock；
- V1 → V2 幂等迁移；
- Snapshot UUID 文件名。
- attempt 完成更新保留原请求时间；
- UserTextInput 最小化 event-buffer 持久化；
- Capture Group 最多一次 natural-event attempt；
- excluded app Capture 前后双重检查；
- excluded app 普通事件入队前静默拦截。

## 6. 真实 macOS 手动验收

真实 macOS 手动验收已经完成，详细证据和测试中发现的修复见：

[`docs/user-enter-signal-v2-manual-test-report.md`](user-enter-signal-v2-manual-test-report.md)

验收结论：

- TextEdit 基础 ID/关联和 attempt ledger：通过；
- UserTextInput 最小化独立持久化：通过；
- 快速五次 Enter 与 Capture Group：通过；
- 连续 20 次 Enter、无丢失、无 queue full：通过；
- excluded app 事件、Signal、Capture、内容落盘均为 0：通过；
- Secure Input Enter 抑制且测试秘密未落盘：通过；
- singleton daemon lock：通过；
- SIGTERM 优雅关闭、队列收敛、锁释放和同 root 重启：通过。

限制：

- 测试机器没有独立数字小键盘，未做真实 keypad Enter 手测；
- 强制崩溃后的 incomplete recovery 仍主要由自动化测试覆盖；
- `AXWindowNumber` 在不支持它的应用中继续使用低置信度 fallback。

## 7. 当前工作区状态

本轮 V2 修改尚未创建 commit，也未 push。

当前分支：

```text
codex/capture-fixes-20260724
```

上一轮 UserEnter commit：

```text
1819e31 feat(capture): add durable UserEnter signals
```

建议在主管确认 V2 数据模型和功能对照后：

1. 先执行真实 macOS 手动验收；
2. 根据测试结果修正；
3. 只暂存本轮 V2 文件；
4. 创建独立 V2 commit；
5. 再决定是否 push 或提交 PR。

## 8. 总结

第二轮已经将 UserEnter 从第一轮的“可靠物理信号 + 固定延迟 Capture”升级为：

- 对象主键清晰；
- Signal 与 Capture 生命周期解耦；
- 条件式 Capture；
- 多 Signal Capture Group；
- Context/Result/Attempt 语义明确；
- 并发更新可合并且幂等；
- Swift/Python 双层隐私阻止；
- shutdown 和启动恢复可收敛；
- Schema 和状态机可版本化演进。

当前自动化、编译检查和真实 macOS 核心行为验收均通过。测试过程中发现的
attempt 合并、UserTextInput 持久化、natural-event 重复、excluded-app
快照竞态和日志反馈循环均已修复并加入回归覆盖。下一步是整理本轮文件并创建独立
V2 commit，交由主管 review。
