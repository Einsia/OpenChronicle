# OpenChronicle UserEnter Signal V2 手动测试报告

日期：2026-07-27

平台：macOS

分支：`codex/capture-fixes-20260724`

测试模式：隔离 `OPENCHRONICLE_ROOT` + `--capture-only`

## 1. 测试结论

UserEnter Signal V2 的核心功能和第二轮修改要求已经通过真实 macOS
手动验证。测试期间发现四类实现问题和一个测试方法问题；实现问题均已修复并复测，
最终完整 Python 测试为 `139 passed`。

最终结论：

- UserEnter 与 UserTextInput 使用独立主键，并通过关联字段正确连接；
- UserTextInput 有独立、最小化、可持久化的关系记录；
- 条件式 Capture、自然 AX 触发和 Capture Group 工作正常；
- 快速输入和连续 20 次 Enter 没有丢失 Signal；
- excluded app 在事件、Signal、Capture 和落盘内容四个层面均被阻止；
- Secure Input 中的 Enter 被抑制，测试秘密没有落盘；
- 单实例锁、优雅关闭、队列收敛和同 root 重启均正常；
- 所有检查结束后没有 `pending`、`running`、临时文件或 `queue_full` 遗留。

## 2. 测试边界与方法

为避免测试内容进入用户的正式 OpenChronicle 记忆，本轮使用多个
`/tmp/openchronicle-user-enter-v2-run*` 隔离目录，并配置：

```toml
[capture]
event_driven = true
heartbeat_minutes = 0
include_screenshot = true
ax_depth = 100
ax_timeout_seconds = 3
debounce_seconds = 3
min_capture_gap_seconds = 0
dedup_interval_seconds = 0
same_window_dedup_seconds = 0

[reducer]
enabled = false

[mcp]
auto_start = false
```

隐私排除测试额外配置：

```toml
excluded_signal_bundle_ids = ["com.apple.TextEdit"]
```

每组操作完成后直接检查：

- `event-buffer/*.json`
- `signal-buffer/*.json`
- `capture-buffer/*.json`
- `logs/capture.log`
- `index.db`
- 临时文件残留

测试未运行 reducer、writer 或 MCP，避免测试文本进入长期记忆或模型流程。

## 3. 功能测试结果

### 3.1 TextEdit 基础关联

操作：在 TextEdit 输入普通文本并按 Enter。

结果：

- UserTextInput 和 UserEnter 均生成；
- `event_id` 与 `signal_id` 各自独立；
- 两者的 `correlation_id` 相同；
- `UserTextInput.related_signal_id` 精确指向 UserEnter；
- UserTextInput 先于 UserEnter 持久化；
- Capture attempt 能得到明确最终结果。

结论：通过。

### 3.2 Attempt 时间字段完整性

首次测试发现：attempt 从 `running` 更新为完成状态时，
`requested_at`、`due_at`、`started_at` 被空值覆盖。

修复：

- 合并已有 attempt 时忽略值为 `None` 的更新字段；
- 增加 `test_attempt_completion_preserves_requested_timestamps`。

复测结果：

- primary 和 follow-up 的请求、计划、开始、结束时间均完整；
- attempt ID 保持稳定；
- 状态更新没有丢失前序字段。

结论：修复后通过。

### 3.3 UserTextInput 独立持久化

首次测试发现：当关联 Capture 被内容去重时，UserTextInput 的独立关系证据没有持久化。

修复：

- 新增 `event-buffer`；
- UserTextInput 在 Capture 前原子持久化；
- 使用独立 `event_id`；
- 重复 `event_id` 幂等，不重复触发 Capture；
- 只允许关系字段和安全的 AX 结构字段落盘；
- 不保存输入值、窗口标题或文本内容。

复测结果：

- event 文件数量正确；
- ID 和关联关系正确；
- event 中没有输入内容、value 或 title；
- Capture 去重不影响事件关系证据。

结论：修复后通过。

### 3.4 快速五次 Enter 与 Capture Group

操作：在同一窗口快速按五次 Enter。

结果：

- 五条独立 Signal；
- 五个唯一 `signal_id`；
- Signal 被合并到少量 Capture Group，而不是一键一张截图；
- 所有 Group 成员均得到最终结果；
- `pending=0`；
- `queue_full=0`。

首次测试还发现：同一 Capture Group 可能因重复 `AXValueChanged`
执行多次 `natural_event` attempt。

修复：

- Group 新增 `natural_attempted` 状态；
- 每个 Group 最多执行一次 natural-event Capture；
- 增加并发回归测试。

复测中五条 Signal 分为 `4+1` 两个 Group；第一组只有一次
natural-event attempt，所有成员最终均为 `reused/good`。

结论：修复后通过。

### 3.5 连续 20 次 Enter 压力测试

用户实际在约 5.2 秒内完成 20 次 Enter，比计划的每秒一次更激进。

结果：

- Signal：20；
- 唯一 `signal_id`：20；
- 丢失：0；
- Capture Group：4 个，成员数为 `6+6+6+2`；
- 最终 `reused/good`：20；
- `pending=0`；
- `queue_full=0`；
- 每个 attempt 的时间字段完整；
- 同一个物理 Capture 可被多个 Signal 安全复用。

结论：通过。

### 3.6 Excluded App

目标应用：TextEdit。

最终测试标记：`V2_EXCLUDED_RACE_FINAL_0727_K4M`。

第一轮排除测试中，TextEdit 的 UserTextInput 和 UserEnter 已为 0，
但来自其他应用的已排队事件可能在切换到 TextEdit 后执行，从而持久化 TextEdit 快照。

第一项修复：

- Capture 前读取当前前台应用；
- AX Capture 后再次检查实际 Snapshot bundle；
- 任一阶段命中排除策略即在截图和写盘前停止。

复测后 TextEdit 快照为 0，但发现日志反馈循环：
daemon 向 Terminal 写日志可产生 Terminal `AXValueChanged`，
该事件在 TextEdit 为前台时进入 Capture，然后又记录“隐私跳过”日志。

第二项修复：

- 对没有 Signal 关联的普通事件，在进入 Capture 队列前检查当前前台应用；
- 命中 excluded app 时静默丢弃；
- Signal 关联请求仍允许进入 worker，以保证 attempt ledger 能够收敛。

最终 run9 结果：

- TextEdit UserTextInput：0；
- TextEdit UserEnter：0；
- TextEdit Capture/Snapshot：0；
- 测试标记落盘：0；
- 隐私跳过循环日志：0；
- `queue_full`：0；
- 临时文件：0。

结论：修复后通过。

### 3.7 Secure Input

测试使用原生 AppleScript 隐藏输入框。

第一次测试的密码框 Enter 已被正确抑制，但 `osascript` 默认把对话框结果输出到
Terminal，导致测试标记随后以普通终端文本形式被正常 Capture。该结果属于测试工具
回显，不是从 Secure Input 或键盘事件中读取，因此该轮隐私落盘结论作废。

第二次使用：

```bash
osascript -e 'display dialog "OpenChronicle Secure Input Retest" default answer "" with hidden answer buttons {"Cancel", "OK"} default button "OK"' >/dev/null
```

最终测试标记：`V2_SECURE_NOREPLAY_0727_R6Y`。

复测结果：

- 执行命令时的普通 Terminal Enter 正常记录；
- 密码框内的 Enter 没有生成 UserEnter；
- 密码框内没有生成 UserTextInput；
- 测试标记在事件、Signal、Capture、日志和 `index.db` 中均为 0；
- `queue_full=0`。

结论：通过。

### 3.8 单实例锁

在 run10 daemon 运行期间，用同一个 `OPENCHRONICLE_ROOT` 启动第二个 daemon。

结果：

```text
Already running (pid 21942)
```

第二个进程立即退出，没有启动第二个 watcher。

结论：通过。

### 3.9 Shutdown、队列收敛与重启

先说明一个测试操作差异：`openchronicle start` 默认后台运行，因此在 shell
提示符处按 `Control-C` 不会停止 daemon。最终使用正式命令：

```bash
openchronicle stop
```

关闭时，执行 stop 命令本身产生了一条 Terminal UserEnter。该 Signal
先进入 `deferred_shutdown`，随后已进入 worker 的 Capture 完成，
最终收敛为 `reused`。

关闭后结果：

- `.pid` 文件删除；
- Capture 日志停止增长；
- 日志包含 `AX watcher stopped`；
- 日志包含 `shutdown signal received` 和 `daemon stopped`；
- session 以 `daemon-shutdown` 正常结束；
- Signal 最终状态：`reused=8`、`new=2`；
- `pending/running=0`；
- 临时文件：0。

随后使用同一个 root 重启：

- 新 daemon PID：`23132`；
- 新 watcher PID：`23133`；
- 锁正常释放；
- watcher 和启动 Capture 正常；
- 历史 Signal 未被重复处理；
- 重启后无 `pending/running/deferred_shutdown`。

结论：通过。

## 4. 自动化回归

最终完整测试：

```text
139 passed in 2.46s
```

代码风格检查：

```text
Changed-file Ruff: All checks passed
```

测试环境因为工作区权限无法写 `.pytest_cache`，pytest 输出一个 cache warning；
该 warning 不影响测试执行和结果。

本轮手测过程中新增的关键回归覆盖：

- attempt 完成更新保留 requested/due/started 时间；
- UserTextInput 关系事件原子、最小化、幂等持久化；
- Capture Group 最多一次 natural-event attempt；
- Capture 时的前台 excluded-app 双重检查；
- excluded app 普通事件在进入 Capture 队列前静默丢弃。

## 5. 测试中发现并修复的问题

| 问题 | 风险 | 修复结果 |
|---|---|---|
| attempt 完成时空值覆盖时间字段 | 审计链不完整 | 忽略空值覆盖并增加回归 |
| UserTextInput 依赖 Capture 才有证据 | 去重后关联事件丢失 | 新增最小化 event-buffer |
| Capture Group 重复 natural attempt | 多余 Capture 与不稳定 ledger | 每 Group 最多一次 |
| 已排队事件跨入 excluded app | 排除应用快照可能落盘 | Capture 前后双重 bundle 检查 |
| 隐私跳过日志触发 Terminal AX 反馈 | 重复无效 Capture 请求 | 入队前静默前台检查 |

## 6. 未覆盖或需要持续观察的边界

- 当前 Mac 没有独立数字小键盘，因此没有真实验证 keypad Enter；
  Return 键及其 key variant 已验证，映射逻辑由 Swift self-test 覆盖。
- 真实崩溃或 `SIGKILL` 后的 incomplete recovery 主要由自动化测试覆盖；
  本轮真实系统测试覆盖的是 SIGTERM 优雅关闭、队列收敛、锁释放和同 root 重启。
- 不同应用对 `AXWindowNumber` 的支持不一致，低置信度
  `bundle_id:pid` fallback 仍需在后续真实使用中持续观察。

## 7. 最终建议

本轮修改已经达到提交主管 review 的条件。建议：

1. 更新 V2 实现汇报中的测试状态；
2. 只暂存 UserEnter V2 相关代码、测试和两份报告；
3. 保留 `src/openchronicle/cli.py` 及其他无关文档修改，不混入本次 commit；
4. 创建独立 V2 commit；
5. 在主管确认后再 push 或创建 PR。
