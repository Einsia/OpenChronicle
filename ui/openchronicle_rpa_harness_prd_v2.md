# OpenChronicle RPA Harness 多 Provider 控制台 PRD v2.0

> 本文档替换旧版《OpenChronicle RPA Harness 实时调试控制台 PRD》。  
> 旧版定位偏“Android 手机自动化调试台”，新版统一升级为“多 RPA Provider 可插拔管理控制台”，并与 `openchronicle_rpa_harness_ui_spec_v2.json` 对齐，用于指导 Codex 复原最新 UI。

生成时间：2026-04-27T11:09:29

---

## 1. 产品定位

OpenChronicle RPA Harness 是一个面向多设备、多执行后端、多工作流的 Agent RPA 调试、录制、回放、审批和 Skill 沉淀控制台。

它不再只是“手机自动化控制台”，而是 OpenChronicle 的 RPA 可视化 Harness 层，负责把不同 RPA 后端统一接入、统一调试、统一审计、统一记录为 trace，并将稳定流程沉淀为可复用的 `workflow.json` 和 `skill.yaml`。

一句话定位：

> 人类演示与监督，OpenChronicle 记录学习，Codex 安全复现，Harness 负责桥接、录制、审计、回放和 Skill 沉淀。

核心链路：

```text
UI Console
  ↓
OpenChronicle API
  ↓
Provider Registry
  ↓
Adapter Layer
  ↓
Device / Browser / Worker
  ↓
Trace Writer
  ↓
Memory Center / Skill Builder
```

---

## 2. 与旧版冲突点及修正

| 旧版冲突点 | 最新修正 |
|---|---|
| 产品定位只写“手机自动化 Agent 调试与治理控制台” | 改为“多 RPA Provider 可插拔管理控制台” |
| 只强调 ADB MCP 和 Android 手机 | 扩展为 Android ADB、Windows UIA、Browser Playwright、API Worker，预留 iOS WDA、Harmony HDC |
| 导航只有录制器、技能构建、执行器等单页思路 | 新增 RPA Provider 管理、设备舰队、Workflow 库、Trace 回放 |
| 设备实时画面只展示手机 | 改为 Android / Windows / Browser / API 四种预览模式 |
| Skill Builder 只从 phone trace 生成 phone skill | 改为 Workflow / Skill Builder，可输出 `workflow.json` 和 `skill.yaml` |
| 状态机只描述手机页面状态 | 改为稳定录制流程：连接 Provider、识别页面、锚点定位、OCR/UI 校验、生成动作、安全检查、写入 Trace、生成 Workflow |
| 数据模型只有 ActionStep 和 PhoneSkill | 新增 RPAProvider、RPADevice、RPAWorkflow、RPARun、RPATraceStep、SafetyApproval、GeneratedSkill |
| 没有 Bridge / API Contract | 新增 Bridge Topology、Bridge Inspector 和 mock API contract |
| 默认像是每步依赖截图/视觉理解 | 明确默认轻量 observe，不默认全屏截图，不默认 VLM，只在关键帧/异常时使用截图 |
| 未体现 workflow schema version | 强制 `schema_version = "1.0"` |

---

## 3. 目标用户

主要用户包括：

- Agent 开发者
- RPA 流程设计人员
- App / 桌面自动化测试工程师
- OpenChronicle / Codex 调试人员
- 需要统一管理 Android、Windows、Browser、API 自动化的团队
- 需要将人工操作经验沉淀为 workflow / skill 的用户

---

## 4. 核心问题

当前让 Codex 或 Agent 直接操作设备，会遇到这些问题：

1. 不同 RPA 后端能力不统一，Android、Windows、Browser、API 难以集中管理。
2. Agent 不知道当前环境状态，容易盲目点击或误操作。
3. 只靠固定坐标不稳定，页面变化、弹窗、验证码、权限页容易导致失败。
4. 高危动作缺少统一审批，例如安装 APK、清除数据、支付页面、发送消息、读取隐私数据。
5. 操作过程难以追踪、回放、审计和复盘。
6. 成功流程没有沉淀为可复用 workflow / skill。
7. UI 与后端 Provider Registry、Workflow Runner、Trace Writer 之间缺少明确桥接协议。

因此需要一个统一 UI Harness，把多 RPA 执行过程变成可见、可控、可编辑、可回放、可学习。

---

## 5. MVP 目标

第一版仍先使用 mock 数据实现高保真前端，不强依赖真实后端。

MVP 必须实现两个核心页面：

```text
/rpa/realtime     实时调试控制台
/rpa/providers    RPA Provider 管理与 Workflow Studio
```

MVP 必须包含：

- 左侧导航栏
- 顶部 Provider selector
- KPI 指标卡片
- 多 Provider 设备预览区
- 稳定录制工作流
- Action Inspector
- Bridge Inspector / Bridge Topology
- 时间线与日志
- Workflow / Skill Builder
- 安全审批
- Provider Registry
- Provider Detail / Manifest Viewer
- Workflow 库
- 录制与编辑 Studio
- Skill 输出与版本管理

---

## 6. 导航结构

左侧导航必须使用最新版结构：

```text
OpenChronicle Harness
├─ 总览
├─ 实时调试
├─ RPA Provider 管理
├─ 设备舰队
├─ Workflow 库
├─ 技能构建
├─ 执行器
├─ Trace 回放
├─ 安全审批
├─ 记忆中心
└─ 设置
```

说明：

- “实时调试”用于执行中的 RPA 调试和录制。
- “RPA Provider 管理”用于管理 android_adb、windows_uia、playwright_browser、api_worker 等后端。
- “设备舰队”用于统一管理设备、桌面、浏览器会话和 API Worker。
- “Workflow 库”用于管理 `workflow.json`。
- “技能构建”用于从 trace / workflow 生成 skill。
- “Trace 回放”用于审计和复盘。
- “安全审批”用于审批高危动作。

---

## 7. 页面一：实时调试控制台

页面名称：

```text
实时调试控制台
```

路由建议：

```text
/rpa/realtime
```

### 7.1 顶部栏

必须包含：

- 页面标题：实时调试控制台
- Provider selector：
  - Android ADB
  - Windows UIA
  - Browser Playwright
  - API Worker
- 当前任务选择器
- 风险等级 Badge
- 全局搜索
- 通知
- 用户信息

### 7.2 KPI 卡片

必须展示：

- 在线 Provider 数：4 / 6
- 在线设备数：18 / 32
- Workflow 成功率：96.3%
- 录制成功率：92.1%
- 待审批任务数：6

### 7.3 设备实时画面 / Device Live View

旧版只展示手机，新版必须支持四种模式：

| 模式 | 展示内容 |
|---|---|
| Android | 手机镜像 mock、包名、Activity、电量、分辨率 |
| Windows | 桌面窗口 mock、进程名、窗口标题、UIA 状态 |
| Browser | 浏览器页面快照 mock、URL、DOM 状态 |
| API | 请求/响应面板 mock、endpoint、status code |

Android 默认展示：

- 设备名：Pixel 6 Pro
- 分辨率：1440 × 3120
- 电量：78%
- 包名：com.taobao.taobao
- Activity：com.taobao.home.MainActivity

操作按钮：

- 截图
- 读取 UI 树
- 点击模式
- 单步执行
- 录制中 00:12:47

轻量化要求：

- 不默认连续全屏截图。
- 点击“截图”时只生成 keyframe mock。
- 读取 UI 树时根据 provider 类型展示 UI tree / DOM / window tree / structured log。

### 7.4 录制工作流 / Recording Flow

替换旧版简单状态机，使用稳定录制流程：

```text
CONNECT_PROVIDER      连接 Provider
SCREEN_OBSERVED       识别页面
ANCHOR_LOCATED        锚点定位
OCR_UI_VERIFIED       OCR/UI树校验
ACTION_GENERATED      生成动作
SAFETY_CHECK          安全检查
TRACE_WRITTEN         写入 Trace
WORKFLOW_GENERATED    生成 Workflow
DONE                  完成
```

状态颜色：

- done：绿色
- current：蓝色
- pending：灰色
- failed：红色

必须展示“稳定录制策略”卡片：

- OCR 优先，减少坐标依赖
- fallback_area 多区域回退定位
- 关键步骤保存 keyframe 截图
- 高风险动作进入安全审批
- unknown action 直接拒绝
- `schema_version = "1.0"`

### 7.5 动作检查器 / Action Inspector

必须展示：

- Step ID
- Provider
- 动作类型
- 目标元素
- resource-id / selector / role / endpoint
- text / value
- 置信度
- 等待条件
- 超时时间
- 重试策略
- 风险等级
- 审批要求
- 当前动作 JSON
- 执行前 / 执行后截图缩略图

示例：

```json
{
  "action": "input_text",
  "provider": "android_adb",
  "target": {
    "type": "EditText",
    "resource_id": "com.taobao.taobao:id/searchEdit",
    "text": "",
    "index": 0
  },
  "value": "连衣裙夏季",
  "strategy": {
    "waitFor": "visible",
    "timeout": 10000,
    "retry": {
      "max": 3,
      "interval": 2000
    }
  },
  "confidence": 0.98
}
```

### 7.6 Bridge Inspector

实时调试页必须新增 Bridge Inspector：

```text
OpenChronicle API → Provider Registry → android_adb → Trace Writer
```

每个节点展示：

- 节点名称
- 状态
- 延迟
- 是否成功
- 错误提示

### 7.7 时间线与日志

表格字段升级为：

```text
步骤 / 时间 / Provider / 动作 / 页面状态或元素 / 结果 / 耗时
```

交互：

- 点击 Step 更新 Action Inspector。
- 当前 Step 高亮。
- 支持按 Provider 筛选。
- 支持搜索动作、元素、结果。
- 支持导出日志。

### 7.8 Workflow / Skill Builder

旧版 Skill Builder 升级为 Workflow / Skill Builder。

必须支持输出切换：

```text
workflow.json / skill.yaml
```

字段：

- 技能名称
- 技能描述
- 输入参数表
- 预览 Skill YAML
- 生成 Skill

必须体现：

- 从 trace 生成 workflow
- 从 workflow 生成 skill
- workflow 固定 `schema_version = "1.0"`

### 7.9 安全审批

保留旧版安全审批，但需要补充 provider 字段。

审批项示例：

- 安装 APK：L3 高风险
- 清除数据：L3 高风险
- 支付页面检测：L2 中风险
- 获取通讯录：L2 中风险
- 发送短信：L2 中风险
- 访问剪贴板：L1 低风险

规则：

- L0/L1 可自动执行并记录。
- L2 进入审批。
- L3 默认阻断，必须人工确认。
- 支付、删除、隐私读取、卸载、清数据类动作必须审批。
- 审批结果必须写入 timeline 和 trace。

---

## 8. 页面二：RPA Provider 管理与 Workflow Studio

页面名称：

```text
RPA Provider 管理与 Workflow Studio
```

路由建议：

```text
/rpa/providers
```

### 8.1 KPI 卡片

必须展示：

- 在线 Provider：4 / 6
- 设备健康度：96.4%
- 近7日运行数：1,284
- 平均恢复率：94.2%
- 待同步 Skills：23

### 8.2 Provider Registry

以卡片网格展示：

| Provider | 平台 | 状态 | Manifest | Observe | 操作 |
|---|---|---|---|---|---|
| android_adb | Android | 在线 | v1.2.1 | OCR、截图、层级树 | 测试连接 / 查看 manifest |
| windows_uia | Windows | 在线 | v1.3.0 | UIA、OCR、截图 | 测试连接 / 查看 manifest |
| playwright_browser | Browser | 在线 | v1.4.2 | DOM、OCR、截图 | 测试连接 / 查看 manifest |
| api_worker | API Worker | 在线 | v1.1.0 | 日志、HTTP、结构化 | 测试连接 / 查看 manifest |
| ios_wda | iOS | 预留 | v0.0.0 | - | 申请启用 / 查看路线图 |
| harmony_hdc | HarmonyOS | 预留 | v0.0.0 | - | 申请启用 / 查看路线图 |

### 8.3 Bridge Topology / 桥接拓扑

必须展示完整桥接链路：

```text
UI Console
  → OpenChronicle API
  → Provider Registry
  → Adapter Layer
  → Device / Browser / Worker
  → Trace Writer
  → Memory Center
  → Skill Builder
```

每个节点展示：

- 状态
- 延迟
- 健康度
- 是否可用

### 8.4 Provider Detail / Manifest Viewer

默认展示 `android_adb`：

- Provider Name
- Adapter Path
- Safety Level
- Observe Modes：keyframe / region / full
- Actions：tap、type、swipe、back、home、launch_app 等
- 当前设备
- Heartbeat
- Manifest JSON 预览
- 复制按钮

### 8.5 Workflow 库

必须展示 workflow 表格：

字段：

```text
名称 / schema_version / provider / platform / steps / success rate / last run / 操作
```

示例：

- android_open_app
- taobao_search_product
- browser_login_flow
- windows_export_report
- api_fetch_and_store

操作：

- 验证
- 运行
- 编辑 JSON
- 生成 Skill

### 8.6 录制与编辑 Studio

必须支持 workflow step 编辑。

工具按钮：

- 开始录制
- 插入步骤
- 条件分支
- 重试策略
- 预览 JSON
- 保存 Workflow

示例步骤：

```text
1. launch_app
2. tap_text
3. type
4. verify_ocr
5. safety_check
6. write_trace
```

每个 step 必须展示：

- step id
- action
- provider
- 简要说明
- 编辑 / 复制 / 删除按钮

必须展示“稳定录制原则”：

- OCR 优先，减少坐标依赖
- 失败时使用 fallback_area
- 关键帧 keyframe 截图保留
- schema_version 固定为 1.0
- unknown action 直接拒绝
- 自动重试与安全检查建议开启

### 8.7 Skill 输出与版本

必须展示：

- YAML / JSON 切换
- Skill 名称
- 描述
- Schema Version
- Provider
- 最新版本
- 版本历史
- 最近生成的 Skill
- 发布 Skill
- 导出 JSON

---

## 9. 数据模型

请以最新版为准，旧版 `ActionStep` 和 `PhoneSkill` 不再单独作为核心模型，只作为兼容模型保留。

### 9.1 RPAProvider

```ts
export type RPAPlatform = "android" | "windows" | "browser" | "api" | "ios" | "harmonyos";
export type RPAStatus = "online" | "offline" | "busy" | "error" | "reserved";
export type RiskLevel = "L0" | "L1" | "L2" | "L3";

export interface RPAProvider {
  name: string;
  platform: RPAPlatform;
  status: RPAStatus;
  manifestVersion: string;
  adapterPath: string;
  safetyLevel: "low" | "medium" | "high";
  actions: string[];
  observeModes: string[];
  successRate?: number;
}
```

### 9.2 RPADevice

```ts
export interface RPADevice {
  deviceId: string;
  provider: string;
  platform: RPAPlatform;
  status: RPAStatus;
  currentTarget: string;
  lastHeartbeat: string;
  currentTask?: string;
  riskLevel: RiskLevel;
}
```

### 9.3 RPAWorkflow

```ts
export interface RPAWorkflow {
  schemaVersion: "1.0";
  id: string;
  name: string;
  provider: string;
  platform: RPAPlatform;
  inputs: Record<string, unknown>;
  steps: WorkflowStep[];
}
```

### 9.4 WorkflowStep

```ts
export interface WorkflowStep {
  id: string;
  action: string;
  provider: string;
  target?: Record<string, unknown>;
  verify?: Record<string, unknown>;
  safety?: Record<string, unknown>;
  result?: "success" | "waiting" | "failed";
}
```

### 9.5 RPATraceStep

```ts
export interface RPATraceStep {
  taskId: string;
  workflowId: string;
  provider: string;
  stepId: string;
  timestamp: string;
  observation: Record<string, unknown>;
  action: Record<string, unknown>;
  result: Record<string, unknown>;
  safety: Record<string, unknown>;
}
```

### 9.6 SafetyApproval

```ts
export interface SafetyApproval {
  id: string;
  action: string;
  provider: string;
  riskLevel: RiskLevel;
  reason: string;
  status: "pending" | "approved" | "rejected";
  createdAt: string;
}
```

### 9.7 GeneratedSkill

```ts
export interface GeneratedSkill {
  name: string;
  version: string;
  sourceWorkflowId: string;
  provider: string;
  format: "skill.yaml" | "workflow.json";
  status: "draft" | "published";
}
```

---

## 10. Mock API Contract

第一版先 mock，不接真实后端。UI 代码要预留 API 封装层。

```text
GET  /api/rpa/providers
GET  /api/rpa/providers/:name
POST /api/rpa/providers/:name/test

GET  /api/rpa/devices

POST /api/rpa/workflows/validate
POST /api/rpa/workflows/run

GET  /api/rpa/runs/:task_id
GET  /api/rpa/traces/:task_id

POST /api/rpa/approvals/:id/approve
POST /api/rpa/approvals/:id/reject

POST /api/rpa/skills/generate
```

实时事件后续可接：

```text
provider_status_changed
device_heartbeat
run_started
step_completed
approval_required
trace_written
skill_generated
```

---

## 11. 推荐技术实现

技术栈：

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- lucide-react
- recharts
- Zustand 或 React Context

推荐目录：

```text
src/pages/rpa/
├─ RealtimeDebugConsole.tsx
├─ ProviderWorkflowStudio.tsx
├─ DeviceFleetPage.tsx
└─ WorkflowLibraryPage.tsx

src/components/layout/
├─ Sidebar.tsx
└─ Topbar.tsx

src/components/dashboard/
└─ KpiCard.tsx

src/components/rpa/
├─ ProviderSwitcher.tsx
├─ DeviceLiveView.tsx
├─ RecordingFlow.tsx
├─ ActionInspector.tsx
├─ BridgeInspector.tsx
├─ ProviderRegistry.tsx
├─ BridgeTopology.tsx
├─ ProviderDetail.tsx
├─ TimelineLog.tsx
├─ WorkflowSkillBuilder.tsx
├─ SafetyApproval.tsx
├─ WorkflowLibrary.tsx
├─ RecordingEditStudio.tsx
└─ SkillOutputVersion.tsx

src/mock/
└─ rpaHarnessMock.ts

src/types/
└─ rpa.ts

src/lib/
└─ rpaApi.ts
```

---

## 12. 视觉要求

整体风格必须参考最新 UI 图：

- 浅色背景
- 白色卡片
- 蓝色主色
- 绿色表示成功
- 黄色表示等待 / 中风险
- 红色表示失败 / 高风险
- 圆角卡片
- 精致阴影
- 高密度但不混乱
- 企业级调试平台质感
- 顶部保留 Provider selector
- 卡片内要体现真实业务字段，不要空壳 Demo

---

## 13. 交互要求

MVP 必须完成：

1. 点击左侧导航可切换“实时调试”和“RPA Provider 管理”两个主页面。
2. Provider selector 切换 Android / Windows / Browser / API 时，Device Live View 同步切换。
3. 点击时间线 Step，右侧 Action Inspector 更新内容。
4. 点击复制 JSON，将当前 Step JSON 复制到剪贴板。
5. 点击“单步执行”，Recording Flow 推进一步，并新增 timeline 日志。
6. 点击“截图”，生成 keyframe mock 日志。
7. 点击“读取 UI 树”，展示 mock UI tree / DOM / window tree。
8. 点击“生成 Skill”，新增 mock skill 版本记录。
9. 点击“批准 / 拒绝”，审批状态改变，并新增日志。
10. Provider Registry 中“测试连接 / 查看 manifest”有 mock 反馈。
11. Workflow Studio 中可插入、编辑、删除 mock step。
12. 点击“预览 JSON”展示当前 workflow JSON。

---

## 14. 验收标准

Codex 完成后必须满足：

1. 页面布局与最新两张参考设计一致。
2. 使用 mock 数据即可完整展示页面。
3. 实时调试页不再写死 Android，必须支持 Android / Windows / Browser / API 切换。
4. Provider 管理页必须展示 6 类 Provider。
5. Bridge Topology 必须清楚展示桥接链路。
6. Workflow Studio 必须展示稳定录制流程和编辑能力。
7. 时间线点击可以驱动 Action Inspector 更新。
8. 状态机当前节点明显高亮。
9. 风险等级和执行状态有颜色区分。
10. Skill Builder 和安全审批有基础交互。
11. 页面整体观感达到高保真产品原型水平。
12. 组件拆分清晰，便于后续接真实 OpenChronicle RPA API。
13. `npm build` 或项目现有构建命令通过。
14. 不出现 TypeScript 错误。

---

## 15. 给 Codex 的执行提示词

```text
你现在要复原 OpenChronicle RPA Harness 最新 UI。

请读取并严格参考：
1. openchronicle_rpa_harness_prd_v2.md
2. openchronicle_rpa_harness_ui_spec_v2.json
3. 最新 UI 参考图：automation_console_with_real_time_monitoring.png
4. 最新 UI 参考图：rpa_provider_and_workflow_studio_dashboard.png

目标：
把旧版 Android 手机实时调试台升级为多 RPA Provider 可插拔管理控制台。

技术栈：
React + TypeScript + Vite + Tailwind CSS + shadcn/ui + lucide-react + recharts。

必须实现两个页面：
1. /rpa/realtime：实时调试控制台
2. /rpa/providers：RPA Provider 管理与 Workflow Studio

必须支持 mock 数据，不要接真实 ADB、UIA、Playwright、API Worker。

必须实现：
- 左侧导航
- 顶部 Provider selector
- KPI 卡片
- Device Live View，支持 Android / Windows / Browser / API 四种 mock 预览
- Recording Flow，展示稳定录制流程
- Action Inspector，展示 action JSON、目标元素、风险、截图缩略图
- Bridge Inspector
- Timeline Log，点击 Step 更新 Action Inspector
- Workflow / Skill Builder
- Safety Approval
- Provider Registry
- Bridge Topology
- Provider Detail / Manifest Viewer
- Workflow 库
- 录制与编辑 Studio
- Skill 输出与版本

必须展示这些 Provider：
- android_adb
- windows_uia
- playwright_browser
- api_worker
- ios_wda
- harmony_hdc

必须体现稳定录制原则：
- OCR 优先
- fallback_area
- keyframe 截图
- schema_version = 1.0
- safety_check
- unknown action reject
- write_trace

实现限制：
- 不要修改无关后端文件
- 不要接真实 ADB
- 不要写死 Android 单设备
- 不要把所有代码堆在一个文件
- mock 数据放 src/mock/rpaHarnessMock.ts
- 类型放 src/types/rpa.ts
- API mock 放 src/lib/rpaApi.ts

完成后运行：
npm build

最后汇报：
1. 新增文件
2. 修改文件
3. 页面说明
4. mock 交互说明
5. npm build 结果
6. 未完成项
```

---

## 16. 最终交付物

Codex 应使用以下两个文件作为主参考：

```text
openchronicle_rpa_harness_prd_v2.md
openchronicle_rpa_harness_ui_spec_v2.json
```

旧版 `openchronicle_rpa_harness_prd.md` 中的“手机专用”描述，均以本文档为准。
