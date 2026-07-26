# OpenChronicle UserEnter Signal 实现汇报

日期：2026-07-26

## 1. 背景与目标

本次工作为 OpenChronicle 增加物理 Enter 键 Signal，使系统能够在不把 Enter
直接解释成“发送、提交或执行”的前提下，获得一个可靠的用户交互时间锚点。

OpenChronicle 仍保持 AX-first：

- Enter 是 AX 状态提取的触发器和时间边界；
- AX Tree、focused element、URL 和 visible text 是主要结果证据；
- Screenshot 继续沿用原有 Capture 配置和去重逻辑，只作为辅助信息；
- Enter Signal 独立于 Snapshot 存储，Capture 失败不能导致 Signal 丢失。

## 2. 设计思路

### 2.1 Signal 与 Snapshot 分离

新的数据流为：

```text
物理 Enter
  → Swift watcher 捕获按键时的应用和安全 AX target
  → 如有待输出文字，先输出 UserTextInput(reason=enter)
  → 输出 UserEnter（与 UserTextInput 共用 signal_id）
  → Python 隐私清洗
  → signal-buffer 原子、幂等落盘
  → T+200ms 请求正常 AX-first Capture
  → T+1000ms 进行一次受限 follow-up，覆盖 800ms 后才更新的页面
  → 新 Snapshot / 复用旧 Snapshot / 失败或跨应用状态回写
```

Signal 文件位于：

```text
~/.openchronicle/signal-buffer/<signal_id>.json
```

Snapshot 仍位于：

```text
~/.openchronicle/capture-buffer/<snapshot_id>.json
```

### 2.2 Enter 的语义边界

所有 Enter 仅代表物理按键事件：

```json
{
  "event_type": "UserEnter",
  "semantic_intent": "unknown"
}
```

系统不直接生成 `send`、`submit`、`execute` 等语义。聊天发送、Terminal
执行、网页提交以及中文输入法候选确认，需要由后续上下文判断，不能只凭 Enter
推断。

### 2.3 按键时 target 与按键后 Snapshot 分离

- `input_target` 在 keyDown 时立即读取，回答“Enter 发生在哪里”；
- `snapshot_ref` 指向 Enter 后的 AX-first Capture，回答“界面之后是什么状态”；
- 后续焦点变化不能覆盖 `input_target`；
- 后续 Snapshot bundle 与按键时 bundle 不一致时，不进行关联。

### 2.4 隐私前置与字段白名单

UserEnter Signal 只允许保存：

- `timestamp`
- `pid`
- `app_name`
- `bundle_id`
- `key_variant`
- `modifiers`
- `input_target.role`
- `input_target.subrole`
- `input_target.identifier`
- `input_target_status`
- `semantic_intent`
- Snapshot 关联状态

以下内容不会进入 Signal：

- element `value`
- element `title`
- 用户输入原文
- 输入法候选词
- 默认窗口标题
- URL
- Screenshot
- 推断出的发送、提交或执行语义

`signal_id` 还经过安全字符校验，避免被用于构造越界文件路径。配置项
`excluded_signal_bundle_ids` 可以在写入和日志记录之前完全排除指定应用。

## 3. 代码修改

### 3.1 Swift watcher

文件：`resources/mac-ax-watcher.swift`

- 识别普通 Return（keyCode 36）；
- 识别小键盘 Enter（keyCode 76），统一输出 `UserEnter`；
- Enter 检测位于 Command/Control 快捷键过滤之前；
- 支持 Shift、Command、Control、Option 修饰键；
- 过滤 `.keyboardEventAutorepeat`；
- keyDown 时立即读取 frontmost app 和 focused AX element；
- Signal target 使用结构字段专用白名单，不读取 title/value；
- Enter 前调用 `flushText(reason: "enter", associationID: signalID)`；
- 无待 flush 文本时不产生空 `UserTextInput`；
- `UserTextInput` 和 `UserEnter` 共用同一个 `signal_id`；
- 增加 `--self-test`，覆盖 Return、小键盘 Enter、普通字符、auto-repeat 和修饰键。

### 3.2 SignalStore

文件：`src/openchronicle/capture/signal_store.py`

- 新增 UserEnter 隐私清洗；
- 新增严格字段 allowlist；
- 新增 excluded bundle 过滤；
- 使用 `signal_id` 作为幂等键；
- 使用临时文件加原子 replace 落盘；
- 支持 Snapshot 状态和 `snapshot_ref` 回写；
- Snapshot 状态使用优先级，避免后续失败覆盖已成功关联的 Snapshot；
- 日志只输出 Signal ID、事件类型、bundle 和状态。

### 3.3 路径与配置

文件：

- `src/openchronicle/paths.py`
- `src/openchronicle/config.py`

改动：

- 新增 `signal_buffer_dir()`；
- `ensure_dirs()` 自动创建 `signal-buffer`；
- 新增 `excluded_signal_bundle_ids` 配置。

### 3.4 Python dispatcher

文件：`src/openchronicle/capture/event_dispatcher.py`

- UserEnter 使用专用处理路径；
- UserEnter 绕过普通 1 秒事件去重和 5 秒同窗口事件去重；
- Signal 必须先成功写入，之后才能请求 Capture；
- 相同 `signal_id` 的重复 watcher event 不会重复写入或重复触发 Capture；
- 初始 Capture 延迟约 200ms；
- follow-up Capture 在约 1 秒执行，以覆盖 T+800ms 的页面更新；
- `UserTextInput` 的关联 ID 继续传递到 Snapshot trigger；
- shutdown 会取消尚未执行的 Enter timer。

### 3.5 Capture runner

文件：`src/openchronicle/capture/scheduler.py`

- 将 `UserEnter` 加入 `_AX_RETRY_EVENTS`；
- 保留原有 150ms、350ms AX 完整性重试；
- Capture fingerprint 和 Snapshot 去重继续启用；
- 内容相同时向 Signal 回写已有 `snapshot_ref`；
- 内容变化时回写新 Snapshot；
- bundle 改变时记录 `app_changed`，不关联错误 Snapshot；
- AX/Capture 失败、暂停、队列拥堵时回写失败状态，但 Signal 保留；
- Capture 文件时间戳增加毫秒，避免同一秒内文件名冲突。

### 3.6 自动化测试

文件：

- `tests/test_signal_store.py`
- `tests/test_event_dispatcher.py`
- `tests/test_capture_metadata.py`

新增覆盖：

- Signal 字段白名单；
- element value/title、窗口标题和推断语义清除；
- secure target 清除；
- excluded bundle；
- 不安全 signal ID 拒绝；
- signal ID 幂等；
- UserEnter 绕过事件去重；
- UserTextInput/Enter 关联 ID；
- 800ms 后更新的 follow-up 升级；
- 相同 Snapshot 复用；
- 应用切换后拒绝错误关联。

## 4. 测试结果

### 4.1 自动化与编译

```text
Python full suite: 127 passed
Ruff: All checks passed
git diff --check: passed
Swift watcher build: passed
Swift Enter self-tests: passed
```

Swift 自测覆盖：

- Return keyCode 36；
- keypad Enter keyCode 76；
- 普通字符不产生 UserEnter；
- Return/keypad Enter auto-repeat 被过滤；
- Shift/Command/Control/Option 修饰键顺序与内容正确。

### 4.2 TextEdit

- 普通 Return 成功生成 UserEnter；
- `input_target` 为安全的 `AXTextArea / First Text View`；
- 有待输入文本时，`UserTextInput(reason=enter)` 与 UserEnter 共用 signal ID；
- 无待输入文本时不生成空 UserTextInput；
- Shift、Command、Control、Option 分别记录正确；
- 长按 Return 只保留第一条 Signal；
- 同画面多次 Enter 复用相同 Snapshot。

### 4.3 Terminal

- Enter 成功记录；
- target 为安全的 `AXTextArea`；
- `semantic_intent=unknown`，未标记为执行；
- 测试命令文本没有进入 signal-buffer。

### 4.4 Chrome

- 地址栏 Enter 的 target 为 `AXTextField`；
- 跳转后的 URL 由 AX Snapshot 获取，Signal 本身不保存 URL；
- 本地测试页在 Enter 后 800ms 更新标题；
- 初始观察复用旧 Snapshot，1 秒 follow-up 捕获更新结果并升级 `snapshot_ref`；
- Chrome 页面无法提供 focused element 时，Signal 保留且记录 `ax_unavailable`。

### 4.5 密码框

使用唯一测试标记检查：

- signal-buffer 中不存在密码文本；
- capture-buffer 的 AX/文本 JSON 中不存在密码文本；
- capture 日志和错误信息中不存在密码文本；
- Signal 只保留 `AXTextField` 等结构字段；
- 即使 Chrome 没有可靠暴露 secure subrole，字段白名单仍阻止 value 泄露。

### 4.6 中文输入法

- 使用 Return 确认候选词时生成一个物理 UserEnter；
- `semantic_intent=unknown`；
- 没有生成发送、提交或执行语义；
- AX target 不可用时正确记录降级状态。

### 4.7 飞书和 VS Code

- 飞书无法提供可靠 target 时记录 `ax_unavailable`，Signal 不丢失；
- VS Code 提供 `AXTextArea` target；
- 快速执行“Enter → 切换应用”时，Signal 保持关联切换前的 VS Code Snapshot；
- 后续飞书激活没有覆盖该关联，观察到的错误跨应用关联数为 0。

### 4.8 20 次 Enter 压力测试

测试结果：

```text
物理 Enter：20
新增 Signal：20
唯一 signal_id：20
Signal 丢失：0
唯一 Snapshot ref：3
```

最终状态包括：

- 9 条复用 Snapshot；
- 3 条生成新 Snapshot；
- 3 条在随后切换应用后记录 `app_changed`；
- 5 条在 Capture 队列拥堵时记录 `queue_full`。

即使 Capture 队列拥堵，20 条 Signal 仍全部保留；同时没有为了 20 次 Enter
保存 20 份重复截图。

## 5. 最终结论

UserEnter 已作为独立、可靠、隐私最小化的物理交互 Signal 接入
OpenChronicle。实现保持 AX-first：Enter 用于切分输入和触发 AX 状态观察，
Snapshot 继续使用原有内容去重，Screenshot 没有成为 Signal 的必要条件。

Signal 与 Snapshot 的生命周期已经解耦，因此 AX 不可用、Screenshot 失败、
Capture 队列拥堵、内容重复或应用切换都不会导致 Enter 丢失，也不会产生错误的
跨应用关联。

## 6. 当前边界

- 没有数字小键盘硬件，因此 keypad Enter 使用 watcher 纯函数自测验证；
- signal-buffer 的长期清理/保留周期尚未单独产品化，目前与测试记录一起保留在本地；
- 测试使用 capture-only 模式，未让测试输入进入 timeline、writer 或 LLM 流程；
- 测试结束后临时 localhost 页面和 OpenChronicle capture-only daemon 均已关闭。
