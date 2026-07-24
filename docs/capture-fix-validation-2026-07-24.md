# Capture 修复验证记录（2026-07-24）

## 目的

根据《Open chronicle测试及相关capture修复》中的问题清单，验证本轮
capture 模块修复：

1. `focused_element` 不再从第一层 AX 节点猜测。
2. `window_meta.title` 与同一次 AX snapshot 保持一致。
3. TextEdit 刚激活时正文缺失的情况得到控制。
4. 内容不变时，连续点击不会制造重复 capture。
5. 测试数据不进入 timeline、reducer、classifier 或长期 memory。

## 隔离方式

测试使用独立数据根目录：

```text
/private/tmp/openchronicle-capture-test
```

配置：

```toml
[capture]
event_driven = true
heartbeat_minutes = 0
include_screenshot = true
ax_depth = 100
ax_timeout_seconds = 3

[reducer]
enabled = false

[mcp]
auto_start = false
```

启动方式：

```bash
OPENCHRONICLE_ROOT=/tmp/openchronicle-capture-test \
UV_CACHE_DIR=/tmp/openchronicle-uv-cache \
uv run openchronicle start --capture-only
```

验证期间 `timeline.log` 和 `writer.log` 为空，memory 文件数为 0。
`status` 命令曾执行模型连通性检查，但调用因缺少认证失败；后台 capture
未进入模型处理流程。

## 自动化验证

代码修改后的完整测试结果：

```text
112 passed in 1.73s
```

静态检查：

```text
Ruff: All checks passed
git diff --check: passed
mac-ax-helper: compiled successfully
```

新增覆盖：

- 不再把第一个 `AXStaticText` 或 `AXTextArea` 猜作焦点。
- 递归 fallback 只接受明确的 `focused=true`。
- TextEdit 不完整 AX snapshot 可通过有限重试恢复。
- 重试期间切换应用时拒绝跨 `bundle_id` 的 snapshot。
- AX snapshot 标题优先，匹配 trigger 次之，System Events 最后兜底。
- Chrome 嵌套 `AXComboBox` 地址栏、URL 规范化及页面输入框误判防护。
- dispatcher 只保留安全的 element 结构字段。

## TextEdit 第一轮：问题复现

测试内容：

```text
OC_TEXTEDIT_BODY_001
OpenChronicle capture validation.
FOCUS_CHECK_001
```

失败证据：

| Capture 文件 | Trigger | 标题 | 焦点 | 正文标记 | 结论 |
|---|---|---|---|---|---|
| `2026-07-24T13-14-21p08-00.json` | `UserTextInput` | `未命名` | 空 | 缺失 | AX 尚未提供正文 |
| `2026-07-24T13-14-24p08-00.json` | `AXApplicationActivated` | `未命名` | 空 | 缺失 | AX 尚未提供正文 |
| `2026-07-24T13-14-27p08-00.json` | `AXApplicationActivated` | `未命名` | 空 | 缺失 | AX 尚未提供正文 |

这三帧均能取得 focused window，但 app 级 `focused_element` 为 `null`；
窗口内只有无子节点的 `AXScrollArea`、Toolbar 和标题，证明缺失发生在
AX snapshot 层，而不是 S1 parser 丢弃正文。

恢复证据：

| Capture 文件 | Trigger | 焦点 | 正文标记 | 标题来源 |
|---|---|---|---|---|
| `2026-07-24T13-14-39p08-00.json` | `UserMouseClick` | `AXTextArea` | 完整 | `ax_snapshot` |

该帧返回 `identifier = First Text View`，正文长度为 70。

## 针对性修复

当交互或应用切换事件产生的 AX snapshot 具有 focused window，但缺少真实
`focused_element` 时：

1. 等待 150 ms 后重试。
2. 若仍不完整，再等待 350 ms 重试一次。
3. 每次重试必须与首帧 `bundle_id` 一致。
4. 检测到应用已切换时立即停止，并丢弃跨应用 snapshot。
5. 在 `ax_metadata` 中记录 `retry_count` 和 `app_consistent`。

## TextEdit 第二轮：通过

有效 capture 共 6 帧：

| Capture 文件 | Trigger | 焦点 | 正文 | 标题来源 | Retry | 一致性 |
|---|---|---|---|---|---:|---|
| `2026-07-24T13-20-07p08-00.json` | `AXApplicationActivated` | `AXTextArea` | 完整 | `ax_snapshot` | 0 | true |
| `2026-07-24T13-20-18p08-00.json` | `UserMouseClick` | `AXTextArea` | 完整 | `ax_snapshot` | 0 | true |
| `2026-07-24T13-20-26p08-00.json` | `UserMouseClick` | `AXTextArea` | 完整 | `ax_snapshot` | 0 | true |
| `2026-07-24T13-20-33p08-00.json` | `UserMouseClick` | `AXTextArea` | 完整 | `ax_snapshot` | 0 | true |
| `2026-07-24T13-20-38p08-00.json` | `UserMouseClick` | `AXTextArea` | 完整 | `ax_snapshot` | 0 | true |
| `2026-07-24T13-20-43p08-00.json` | `AXApplicationActivated` | `AXTextArea` | 完整 | `ax_snapshot` | 0 | true |

所有帧：

- `focused_element.role = AXTextArea`
- `focused_element.identifier = First Text View`
- `focused_element.is_editable = true`
- `focused_element.value_length = 70`
- 两个测试标记均出现在 `visible_text`
- `window_meta.title = 未命名`
- 内容 fingerprint 一致
- 未发生跨应用 snapshot 混合

`retry_count = 0` 表示第二轮中 AX 首次读取已经完整；有限重试的实际分支由
自动化测试覆盖。最后连续点击未产生三份额外 TextEdit capture，去重符合预期。

## 当前结论

TextEdit 验收通过。第一轮明确复现了 AX 未稳定问题；加入有限重试和一致性
保护后，第二轮所有样本均能从首帧取得正确焦点、正文和标题。下一项为
Chrome URL 与标签页切换验证。

## Chrome 第一轮：URL 与标签页切换通过

测试页面：

```text
https://example.com/?oc_case=A01
https://example.org/?oc_case=A02
```

关键证据：

| Capture 文件 | 操作 | 焦点 | URL | URL 来源 | 一致性 |
|---|---|---|---|---|---|
| `2026-07-24T13-43-09p08-00.json` | A01 正文 | 空 | A01 | `ax_address_bar` | true |
| `2026-07-24T13-43-24p08-00.json` | A01 地址栏 | `AXTextField` | A01 | `ax_address_bar` | true |
| `2026-07-24T13-43-30p08-00.json` | A01 正文 | 空 | A01 | `ax_address_bar` | true |
| `2026-07-24T13-43-35p08-00.json` | A02 正文 | 空 | A02 | `ax_address_bar` | true |
| `2026-07-24T13-43-42p08-00.json` | A02 地址栏 | `AXTextField` | A02 | `ax_address_bar` | true |
| `2026-07-24T13-43-47p08-00.json` | A02 正文 | 空 | A02 | `ax_address_bar` | true |
| `2026-07-24T13-43-56p08-00.json` | 标签切至 A01 | 空 | A01 | `ax_address_bar` | true |
| `2026-07-24T13-44-04p08-00.json` | 标签切至 A02 | 空 | A02 | `ax_address_bar` | true |
| `2026-07-24T13-44-09p08-00.json` | 标签切至 A01 | 空 | A01 | `ax_address_bar` | true |
| `2026-07-24T13-44-26p08-00.json` | 最终 A02 点击 | 空 | A02 | `ax_address_bar` | true |

结论：

- 网页正文获得焦点时，仍能从地址栏取得当前 URL。
- 地址栏获得焦点时返回 `AXTextField`，value 与当前 URL 一致。
- A01/A02 标签页往返切换时，URL 始终跟随当前标签页。
- 所有有效样本均为 `title_source = ax_snapshot`、`app_consistent = true`。
- 页面正文中的链接没有被误认为地址栏 URL。
- 最后连续点击未产生三份额外 capture。

观察到正文点击样本通常为 `focused_element` 空，但仍触发两次 AX 重试。
这是性能问题而不是数据正确性问题：Chrome 页面正文没有可编辑焦点时，
地址栏 URL 和页面 AX 内容已经完整，不需要为了空焦点等待 500 ms。

已修复：浏览器 focused window 已能取得唯一 `ax_address_bar` URL 时，将
snapshot 视为完整，不再因页面正文缺少 focused element 重试。新增自动化
测试确认 provider 只调用一次、`retry_count = 0`，同时保留正确 URL。
修复后全量测试为 `113 passed`。

现场复验通过：

| Capture 文件 | 操作 | 焦点 | URL | URL 来源 | Retry | 一致性 |
|---|---|---|---|---|---:|---|
| `2026-07-24T13-51-53p08-00.json` | A02 正文点击 | 空 | A02 | `ax_address_bar` | 0 | true |

与修复前同类正文点击的 `retry_count = 2` 相比，修复后降为 0，URL 和
snapshot 一致性保持正确。

## Chrome 测试期间发现的隐私问题

隔离测试开始后、正式 A01/A02 用例之前，Chrome 曾打开账户认证页面。原始
capture 中可能包含邮箱、认证页面可见文字及 URL 查询参数中的临时认证信息。
这些数据只位于隔离目录，未进入 timeline、writer、模型或长期 memory，
并且没有复制到本报告。

后续修复应对 URL 查询参数实施敏感键脱敏，并在测试结束后删除隔离目录。
原始 Chrome 认证 capture 不应提交到 Git 或作为汇报附件。

## 飞书搜索框：未通过

测试词：

```text
OC_FEISHU_SEARCH_001_X9Q7
```

测试产生 15 个飞书 capture。窗口标题和应用一致性正常，但搜索框及测试词
未进入 AX Tree。

关键证据：

| Capture 文件 | 窗口 | Focused element | Retry | 一致性 | 测试词 |
|---|---|---|---:|---|---|
| `2026-07-24T13-53-48p08-00.json` | `ModalWebViewWidget - search:search-command-bar:default` | 空 | 2 | true | 缺失 |
| `2026-07-24T13-53-52p08-00.json` | `飞书` | `AXGroup` | 0 | true | 缺失 |
| `2026-07-24T13-54-08p08-00.json` | `ModalWebViewWidget - search:search-command-bar:default` | 空 | 2 | true | 缺失 |
| `2026-07-24T13-54-37p08-00.json` | `ModalWebViewWidget - search:search-command-bar:default` | 空 | 2 | true | 缺失 |

结构检查：

- 搜索弹窗 focused window 能正确识别。
- 弹窗 AX Tree 只有 6 个嵌套 `AXGroup`，最大深度为 5。
- 没有 `AXTextField`、`AXTextArea`、`AXComboBox` 或文本 value。
- app 级 `kAXFocusedUIElementAttribute` 在弹窗中返回空。
- 主窗口偶尔返回真实 focused element，但角色仅为 `AXGroup`。
- watcher 点击目标只到 `AXScrollArea`，没有搜索输入框标识。

因此本次失败不是 S1 parser 错选节点：当前飞书搜索弹窗没有通过所抓取的
macOS AX 接口暴露输入控件或搜索文字。继续递归也无法恢复不存在的节点。
后续需要单独评估 Electron renderer accessibility、飞书特定适配，或
OCR/视觉 fallback；在无法可靠确认输入目标时继续返回空，避免猜测。

## VS Code 编辑器：未通过

测试标记：

```text
OC_VSCODE_EDITOR_001
EDITOR_FOCUS_001
```

测试产生 14 个 VS Code capture。窗口标题能跟随 Untitled 文档变化，但
编辑器正文和真实焦点没有通过 AX Tree 暴露。

关键证据：

| Capture 文件 | Trigger | 窗口标题 | Focused element | Retry | 一致性 |
|---|---|---|---|---:|---|
| `2026-07-24T13-56-38p08-00.json` | `AXValueChanged` | 含第一个测试标记 | 空 | 0 | true |
| `2026-07-24T13-57-16p08-00.json` | `AXValueChanged` | 含第一个测试标记 | 空 | 0 | true |
| `2026-07-24T13-57-59p08-00.json` | `AXApplicationActivated` | 含第一个测试标记 | 空 | 2 | true |
| `2026-07-24T13-58-15p08-00.json` | `AXApplicationActivated` | 含第一个测试标记 | 空 | 2 | true |

结构检查：

- focused window 能正确识别，标题稳定来自 `ax_snapshot`。
- app 级 `kAXFocusedUIElementAttribute` 返回空。
- 编辑窗口 AX Tree 只有 7 个嵌套 `AXGroup`，最大深度为 6。
- 没有 `AXTextArea`、`AXTextField`、`AXWebArea` 或编辑器文本 value。
- 第一个测试标记只出现在窗口标题，不存在于任何 AX element。
- 第二个测试标记没有出现在 focused value 或 visible text。
- 短暂出现的 `AXSheet` 焦点属于警告弹窗，不是编辑器。

因此不能把“窗口标题包含首行文字”视为正文读取成功。该结果与飞书搜索弹窗
相似，表明两个 Electron 应用可能共享 renderer accessibility 未启用的问题。
应先调查如何可靠启用 Electron/Chromium AX renderer，再考虑 parser fallback。

## Electron AX renderer 适配

根据 Electron 官方的第三方 macOS accessibility 接入方式，Swift helper
现在会在抓取 allowlist 中的 Electron 应用之前，对 application AX element
设置：

```text
AXManualAccessibility = true
```

默认配置：

```toml
[capture]
enable_electron_accessibility = true
electron_accessibility_bundles = [
  "com.microsoft.VSCode"
]
```

实现约束：

- 只对显式 bundle allowlist 生效，不影响其他应用。
- 在读取 focused element、focused window 和 renderer tree 之前设置属性。
- 现有 150 ms / 350 ms 有限重试用于等待 renderer AX tree 初始化。
- helper 在 app JSON 中记录 requested、succeeded 和 AX error code。
- Python provider 将结果提升到 `ax_metadata.manual_accessibility`，便于审计。
- 配置可整体关闭，也可替换 bundle allowlist。

验证结果：

```text
mac-ax-helper: compiled successfully
115 passed in 1.91s
changed-file Ruff checks: passed
git diff --check: passed
```

下一步需要在带有 Terminal 辅助功能权限的隔离 daemon 中重新测试飞书和
VS Code，确认 renderer tree 是否从纯 `AXGroup` 展开为可用的输入控件和文本。

### VS Code Electron 复验：通过

`AXManualAccessibility` 设置结果：

```json
{
  "bundle_id": "com.microsoft.VSCode",
  "requested": true,
  "succeeded": true,
  "error_code": 0
}
```

启用前后结构对比：

| 状态 | 节点数 | 最大深度 | 关键角色 |
|---|---:|---:|---|
| 启用前 | 7 | 6 | 仅 `AXGroup` |
| 启用后 | 约 177 | 30 | `AXWebArea`、`AXTextArea`、Toolbar、Button、StaticText 等 |

关键证据：

| Capture 文件 | Trigger | 焦点 | 可编辑 | 测试正文 | 一致性 |
|---|---|---|---|---|---|
| `2026-07-24T14-42-37p08-00.json` | `AXValueChanged` | 空 | false | renderer tree 已展开 | true |
| `2026-07-24T14-42-44p08-00.json` | `UserMouseClick` | `AXTextArea` | true | 编辑器已识别 | true |
| `2026-07-24T14-43-42p08-00.json` | `AXValueChanged` | `AXTextArea` | true | focus 标记存在 | true |
| `2026-07-24T14-43-51p08-00.json` | `AXApplicationActivated` | `AXTextArea` | true | focus 标记存在 | true |
| `2026-07-24T14-44-06p08-00.json` | `AXApplicationActivated` | `AXTextArea` | true | focus 标记存在 | true |

成功样本中 focused value 长度为 66，测试标记同时进入 focused value 和
visible text。VS Code 原验收项“编辑区不再返回空或标题文字”通过。

### 飞书 Electron 复验：仍未通过

`AXManualAccessibility` 设置结果：

```json
{
  "bundle_id": "com.electron.lark",
  "requested": true,
  "succeeded": false,
  "error_code": -25205
}
```

macOS AX error `-25205` 表示 attribute unsupported。飞书主 application AX
element 不接受 `AXManualAccessibility`，因此 renderer tree 没有展开：

- 主窗口仍只有有限的 Group/Button/Unknown 等节点。
- 搜索弹窗仍只有 6 个嵌套 `AXGroup`。
- 搜索输入框、测试词和真实 focused element 均缺失。
- 两次有限重试无法改变结构。

结论：通用 Electron 适配对 VS Code 有效，但飞书的定制 Electron/多进程
实现不支持该 application-level 属性。飞书需要独立调查子进程 AX、应用自身
accessibility 开关或视觉/OCR fallback，不能继续通过 parser 猜测。

### 最终范围决定

本轮不继续实现飞书专用子进程 AX 适配，也暂不实现 OCR。原因如下：

- 飞书使用定制 Lark Framework 和多个 renderer 子进程。
- 主 application AX element 明确返回 attribute unsupported。
- 按 renderer PID 做映射会绑定飞书私有进程结构，版本升级后容易失效。
- 该方案只能服务单个应用，维护成本高、泛化价值低。

因此默认 Electron allowlist 已移除 `com.electron.lark`，避免每次飞书 capture
重复执行必然失败的属性设置。当前默认只保留已经现场验证成功的：

```toml
electron_accessibility_bundles = ["com.microsoft.VSCode"]
```

飞书继续使用现有 AX 结果；无法可靠确定搜索框时 `focused_element` 保持空，
不从 `AXGroup` 猜测输入控件。OCR/视觉 fallback 作为后续独立设计事项，
不属于本轮修复范围。

## Terminal：通过

测试标记：

```text
OC_TERMINAL_INPUT_001
OC_TERMINAL_FOCUS_001
```

测试产生 13 个 Terminal capture。真实焦点、输入内容、窗口标题和应用一致性
均符合预期。

关键证据：

| Capture 文件 | Trigger | 焦点 | 测试标记 | Retry | 一致性 |
|---|---|---|---|---:|---|
| `2026-07-24T14-00-56p08-00.json` | `AXValueChanged` | `AXTextArea` | 第一个标记 | 0 | true |
| `2026-07-24T14-01-17p08-00.json` | `AXValueChanged` | `AXTextArea` | 第一个标记 | 0 | true |
| `2026-07-24T14-01-39p08-00.json` | `AXValueChanged` | `AXTextArea` | 两个标记 | 0 | true |
| `2026-07-24T14-01-51p08-00.json` | `UserMouseClick` | `AXTextArea` | 两个标记 | 0 | true |
| `2026-07-24T14-02-03p08-00.json` | `AXApplicationActivated` | `AXTextArea` | 两个标记 | 0 | true |

所有有效样本：

- `focused_element.role = AXTextArea`
- `focused_element.is_editable = true`
- 测试标记同时存在于 focused value 和 visible text
- `title_source = ax_snapshot`
- `retry_count = 0`
- `app_consistent = true`
- watcher 点击目标正确保留 `role = AXTextArea`

最后连续点击未产生三份额外 Terminal capture。该原生 macOS AX 应用的通过
结果进一步表明，飞书和 VS Code 的失败集中在 Electron renderer AX 暴露，
而不是通用 focused-element parser。

## 证据保留说明

原始 capture JSON 和截图当前仍位于：

```text
/private/tmp/openchronicle-capture-test/capture-buffer
```

该目录可能在系统重启后消失，并且包含测试期间其他应用的本地截图与可见文字，
不应直接提交到 Git 或发送给他人。对外汇报建议使用本报告中的脱敏字段摘要；
如确需原始证据，应只导出上述表格列出的 TextEdit JSON，并先删除 screenshot
及与结论无关的可见内容。
