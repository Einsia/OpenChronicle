import type {
  BridgeNode,
  GeneratedSkill,
  KpiMetric,
  ProviderPreview,
  RecordingFlowStep,
  RPADevice,
  RPAProvider,
  RPATraceStep,
  RPAWorkflow,
  SafetyApproval,
  WorkflowStep
} from "../types/rpa";

export const providerSwitchers = [
  { label: "Android ADB", provider: "android_adb" },
  { label: "Windows UIA", provider: "windows_uia" },
  { label: "Browser Playwright", provider: "playwright_browser" },
  { label: "API Worker", provider: "api_worker" }
];

export const navigationItems = [
  "总览",
  "实时调试",
  "RPA Provider 管理",
  "设备舰队",
  "Workflow 库",
  "技能构建",
  "执行器",
  "Trace 回放",
  "安全审批",
  "记忆中心",
  "设置"
];

export const providers: RPAProvider[] = [
  {
    name: "android_adb",
    label: "Android ADB",
    platform: "android",
    status: "online",
    manifestVersion: "v1.2.1",
    adapterPath: "adapters/android/adb_bridge",
    safetyLevel: "high",
    actions: ["tap", "type", "swipe", "back", "home", "launch_app"],
    observeModes: ["OCR", "keyframe", "region", "ui_tree"],
    successRate: 98.6,
    latencyMs: 28
  },
  {
    name: "windows_uia",
    label: "Windows UIA",
    platform: "windows",
    status: "online",
    manifestVersion: "v1.3.0",
    adapterPath: "adapters/windows/uia_bridge",
    safetyLevel: "high",
    actions: ["click", "type", "hotkey", "select", "read_window"],
    observeModes: ["UIA", "OCR", "keyframe", "window_tree"],
    successRate: 97.1,
    latencyMs: 32
  },
  {
    name: "playwright_browser",
    label: "Browser Playwright",
    platform: "browser",
    status: "online",
    manifestVersion: "v1.4.2",
    adapterPath: "adapters/browser/playwright_bridge",
    safetyLevel: "medium",
    actions: ["goto", "click", "fill", "wait_for_selector", "evaluate"],
    observeModes: ["DOM", "OCR", "keyframe", "network"],
    successRate: 95.7,
    latencyMs: 38
  },
  {
    name: "api_worker",
    label: "API Worker",
    platform: "api",
    status: "online",
    manifestVersion: "v1.1.0",
    adapterPath: "adapters/api/http_worker",
    safetyLevel: "medium",
    actions: ["request", "assert_json", "transform", "write_trace"],
    observeModes: ["HTTP", "logs", "structured_result"],
    successRate: 97.8,
    latencyMs: 19
  },
  {
    name: "ios_wda",
    label: "iOS WDA",
    platform: "ios",
    status: "reserved",
    manifestVersion: "v0.0.0",
    adapterPath: "adapters/ios/wda_bridge",
    safetyLevel: "high",
    actions: [],
    observeModes: [],
    latencyMs: 0
  },
  {
    name: "harmony_hdc",
    label: "Harmony HDC",
    platform: "harmonyos",
    status: "reserved",
    manifestVersion: "v0.0.0",
    adapterPath: "adapters/harmony/hdc_bridge",
    safetyLevel: "high",
    actions: [],
    observeModes: [],
    latencyMs: 0
  }
];

export const devices: RPADevice[] = [
  {
    deviceId: "pixel-6-pro",
    provider: "android_adb",
    platform: "android",
    status: "busy",
    currentTarget: "com.taobao.taobao / MainActivity",
    lastHeartbeat: "12s 前",
    currentTask: "taobao_search_product",
    riskLevel: "L1",
    metadata: {
      设备: "Pixel 6 Pro",
      分辨率: "1440 × 3120",
      电量: "78%",
      包名: "com.taobao.taobao",
      Activity: "com.taobao.home.MainActivity"
    }
  },
  {
    deviceId: "desktop-7FK3",
    provider: "windows_uia",
    platform: "windows",
    status: "online",
    currentTarget: "财务导出工具 - Report Studio",
    lastHeartbeat: "8s 前",
    riskLevel: "L1",
    metadata: {
      窗口: "Report Studio",
      进程: "report-studio.exe",
      UIA: "Available",
      分辨率: "2560 × 1440"
    }
  },
  {
    deviceId: "chromium-124",
    provider: "playwright_browser",
    platform: "browser",
    status: "online",
    currentTarget: "https://console.openchronicle.dev/login",
    lastHeartbeat: "4s 前",
    riskLevel: "L2",
    metadata: {
      Browser: "Chromium 124",
      URL: "console.openchronicle.dev/login",
      DOM: "stable",
      Network: "2 pending"
    }
  },
  {
    deviceId: "api-worker-01",
    provider: "api_worker",
    platform: "api",
    status: "online",
    currentTarget: "POST /api/orders/search",
    lastHeartbeat: "2s 前",
    riskLevel: "L0",
    metadata: {
      Endpoint: "POST /api/orders/search",
      Status: "200 OK",
      Latency: "142ms",
      Schema: "validated"
    }
  }
];

export const realtimeKpis: KpiMetric[] = [
  { title: "在线 Provider 数", value: "4 / 6", subtitle: "较昨日 ↑ 1", tone: "blue", data: trend([18, 16, 17, 19, 17, 20, 24, 21, 25]) },
  { title: "在线设备数", value: "18 / 32", subtitle: "较昨日 ↑ 3", tone: "blue", data: trend([11, 12, 10, 14, 12, 16, 15, 21, 19]) },
  { title: "Workflow 成功率", value: "96.3%", subtitle: "较昨日 ↑ 2.4%", tone: "green", data: trend([88, 91, 89, 94, 92, 96, 95, 98, 97]) },
  { title: "录制成功率", value: "92.1%", subtitle: "较昨日 ↑ 1.8%", tone: "blue", data: trend([72, 74, 73, 77, 76, 81, 84, 87, 89]) },
  { title: "待审批任务数", value: "6", subtitle: "较昨日 ↓ 2", tone: "orange", data: trend([12, 10, 11, 9, 8, 9, 7, 6, 6]) }
];

export const providerKpis: KpiMetric[] = [
  { title: "在线 Provider", value: "4 / 6", subtitle: "在线率 66.7%", tone: "blue", data: trend([3, 3, 4, 4, 4, 5, 4, 4, 4]) },
  { title: "设备健康度", value: "96.4%", subtitle: "较昨日 ↑ 2.1%", tone: "blue", data: trend([84, 88, 87, 91, 90, 94, 97, 96, 95]) },
  { title: "近7日运行数", value: "1,284", subtitle: "较上周 ↑ 18.6%", tone: "green", data: trend([80, 86, 84, 91, 89, 95, 94, 101, 98]) },
  { title: "平均恢复率", value: "94.2%", subtitle: "较上周 ↑ 3.4%", tone: "blue", data: trend([70, 74, 73, 78, 79, 82, 84, 89, 91]) },
  { title: "待同步 Skills", value: "23", subtitle: "较昨日 ↓ 2", tone: "orange", data: trend([30, 29, 28, 27, 25, 26, 24, 23, 23]) }
];

export const previewByProvider: Record<string, ProviderPreview> = {
  android_adb: {
    provider: "android_adb",
    platform: "android",
    title: "淘宝搜索商品流程",
    subtitle: "Pixel 6 Pro / com.taobao.taobao",
    metadata: devices[0].metadata,
    treeLabel: "UI Tree",
    treePreview: "FrameLayout > HomeTab > SearchBox#searchEdit > RecyclerView[resultList]"
  },
  windows_uia: {
    provider: "windows_uia",
    platform: "windows",
    title: "Windows 报表导出流程",
    subtitle: "Report Studio / report-studio.exe",
    metadata: devices[1].metadata,
    treeLabel: "Window Tree",
    treePreview: "Window[Report Studio] > Toolbar[Export] > Grid[MonthlyData] > Button[Save]"
  },
  playwright_browser: {
    provider: "playwright_browser",
    platform: "browser",
    title: "Browser 登录回归流程",
    subtitle: "Chromium / console.openchronicle.dev",
    metadata: devices[2].metadata,
    treeLabel: "DOM Snapshot",
    treePreview: "html > body > main.login > form#login > input[name=email] > button[type=submit]"
  },
  api_worker: {
    provider: "api_worker",
    platform: "api",
    title: "API 数据读取与入库",
    subtitle: "HTTP Worker / structured result",
    metadata: devices[3].metadata,
    treeLabel: "Structured Log",
    treePreview: "request.body.keyword -> response.items[0].sku -> transform.persist -> write_trace"
  }
};

export const recordingFlow: RecordingFlowStep[] = [
  { id: "CONNECT_PROVIDER", label: "连接 Provider", description: "Provider bridge ready", status: "done" },
  { id: "SCREEN_OBSERVED", label: "识别页面", description: "页面状态已观察", status: "done" },
  { id: "ANCHOR_LOCATED", label: "锚点定位", description: "fallback_area 已登记", status: "done" },
  { id: "OCR_UI_VERIFIED", label: "OCR/UI树校验", description: "OCR 与结构树一致", status: "done" },
  { id: "ACTION_GENERATED", label: "生成动作", description: "Step 3: input_text", status: "current" },
  { id: "SAFETY_CHECK", label: "安全检查", description: "等待执行 safety_check", status: "pending" },
  { id: "TRACE_WRITTEN", label: "写入 Trace", description: "等待 write_trace", status: "pending" },
  { id: "WORKFLOW_GENERATED", label: "生成 Workflow", description: "schema_version = 1.0", status: "pending" },
  { id: "DONE", label: "Done", description: "等待完成", status: "pending" }
];

export const stableRecordingRules = [
  "OCR 优先，减少坐标依赖",
  "fallback_area 多区域回退定位",
  "关键帧保存 keyframe 截图",
  "schema_version = 1.0",
  "safety_check 覆盖高风险动作",
  "unknown action reject",
  "write_trace 写入 trace.jsonl"
];

export const traceSteps: RPATraceStep[] = [
  trace("Step 1", "android_adb", "launch_app", "HOME_PAGE", "success", "1.32s"),
  trace("Step 2", "android_adb", "tap_text", "SEARCH_BOX", "success", "0.85s"),
  trace("Step 3", "android_adb", "input_text", "SEARCH_BOX", "success", "1.21s"),
  trace("Step 4", "android_adb", "tap", "SEARCH_BUTTON", "waiting", "3.45s"),
  trace("Step 5", "windows_uia", "export_report", "EXPORT_DIALOG", "success", "2.31s"),
  trace("Step 6", "api_worker", "assert_json", "RESULT_LIST", "failed", "4.12s")
];

export const bridgeInspectorNodes: BridgeNode[] = [
  { id: "api", label: "OpenChronicle API", detail: "REST / WS", status: "healthy", latencyMs: 16, available: true },
  { id: "registry", label: "Provider Registry", detail: "Manifest resolved", status: "healthy", latencyMs: 24, available: true },
  { id: "provider", label: "android_adb", detail: "Adapter bridge", status: "healthy", latencyMs: 28, available: true },
  { id: "trace", label: "Trace Writer", detail: "write_trace ready", status: "healthy", latencyMs: 21, available: true }
];

export const bridgeTopologyNodes: BridgeNode[] = [
  { id: "ui", label: "UI Console", detail: "实时操作台", status: "healthy", latencyMs: 120, available: true },
  { id: "api", label: "OpenChronicle API", detail: "REST / WS", status: "healthy", latencyMs: 68, available: true },
  { id: "registry", label: "Provider Registry", detail: "Registry & Manifest", status: "healthy", latencyMs: 45, available: true },
  { id: "adapter", label: "Adapter Layer", detail: "Bridge Adapter", status: "healthy", latencyMs: 32, available: true },
  { id: "target", label: "Device / Browser / Worker", detail: "Android / Windows / Browser / API", status: "healthy", latencyMs: 38, available: true },
  { id: "trace", label: "Trace Writer", detail: "Trace / Artifact / Log", status: "healthy", latencyMs: 27, available: true },
  { id: "memory", label: "Memory Center", detail: "Snapshot / Memory", status: "healthy", latencyMs: 24, available: true },
  { id: "skill", label: "Skill Builder", detail: "Skill / Workflow / Version", status: "healthy", latencyMs: 21, available: true }
];

export const workflowSteps: WorkflowStep[] = [
  { id: "1", action: "launch_app", provider: "android_adb", description: "启动应用 Taobao", result: "success" },
  { id: "2", action: "tap_text", provider: "android_adb", description: "点击文本“搜索框”", result: "success" },
  { id: "3", action: "type", provider: "android_adb", description: "输入文本 ${keyword}", result: "waiting" },
  { id: "4", action: "verify_ocr", provider: "android_adb", description: "验证 OCR 包含“搜索”", result: "waiting" },
  { id: "5", action: "safety_check", provider: "system", description: "安全检查（商品名称）", result: "waiting" },
  { id: "6", action: "write_trace", provider: "system", description: "写入 Trace", result: "waiting" }
];

export const workflows: RPAWorkflow[] = [
  workflow("wf-android-open", "android_open_app", "android_adb", "android", 6, 98.7, "10:21:33"),
  workflow("wf-taobao-search", "taobao_search_product", "android_adb", "android", 12, 96.4, "10:18:07"),
  workflow("wf-browser-login", "browser_login_flow", "playwright_browser", "browser", 9, 97.2, "10:15:42"),
  workflow("wf-windows-export", "windows_export_report", "windows_uia", "windows", 8, 95.1, "10:11:05"),
  workflow("wf-api-fetch", "api_fetch_and_store", "api_worker", "api", 7, 98.9, "10:08:12")
];

export const safetyApprovals: SafetyApproval[] = [
  { id: "ap-1", action: "安装 APK", provider: "android_adb", riskLevel: "L3", reason: "安装外部包需要人工确认", status: "pending", createdAt: "10:20:15" },
  { id: "ap-2", action: "清除数据", provider: "android_adb", riskLevel: "L3", reason: "会删除应用本地数据", status: "pending", createdAt: "10:18:42" },
  { id: "ap-3", action: "支付页面检测", provider: "android_adb", riskLevel: "L2", reason: "支付页面必须进入审批", status: "pending", createdAt: "10:17:33" },
  { id: "ap-4", action: "获取通讯录", provider: "android_adb", riskLevel: "L2", reason: "读取隐私数据", status: "pending", createdAt: "10:15:21" },
  { id: "ap-5", action: "发送短信", provider: "android_adb", riskLevel: "L2", reason: "对外发送消息", status: "pending", createdAt: "10:12:09" },
  { id: "ap-6", action: "访问剪贴板", provider: "windows_uia", riskLevel: "L1", reason: "低风险读取，仍需写入 Trace", status: "pending", createdAt: "10:11:05" }
];

export const generatedSkills: GeneratedSkill[] = [
  { name: "taobao_search_product", version: "v1.2.0", sourceWorkflowId: "wf-taobao-search", provider: "android_adb", format: "skill.yaml", status: "published", generatedAt: "10:21:33" },
  { name: "browser_login_flow", version: "v1.1.0", sourceWorkflowId: "wf-browser-login", provider: "playwright_browser", format: "workflow.json", status: "draft", generatedAt: "10:15:42" },
  { name: "windows_export_report", version: "v1.1.0", sourceWorkflowId: "wf-windows-export", provider: "windows_uia", format: "skill.yaml", status: "published", generatedAt: "10:11:05" }
];

function trend(values: number[]) {
  return values.map((value) => ({ value }));
}

function trace(stepId: string, provider: string, actionName: string, pageState: string, status: string, duration: string): RPATraceStep {
  return {
    taskId: "task-taobao-20260427",
    workflowId: "wf-taobao-search",
    provider,
    stepId,
    timestamp: `10:24:0${stepId.replace("Step ", "")}.789`,
    actionName,
    pageState,
    duration,
    observation: {
      strategy: "OCR first",
      keyframe: stepId === "Step 3",
      fallback_area: ["search_header", "top_input_region"]
    },
    action: {
      action: actionName,
      provider,
      target: {
        type: actionName === "assert_json" ? "response.body" : "EditText",
        resource_id: "com.taobao.taobao:id/searchEdit",
        text: actionName === "input_text" ? "" : "搜索"
      },
      value: actionName === "input_text" ? "连衣裙夏季" : undefined,
      strategy: {
        waitFor: "visible",
        timeout: 10000,
        retry: { max: 3, interval: 2000 }
      },
      confidence: actionName === "assert_json" ? 0.72 : 0.98
    },
    result: {
      status,
      schema_version: "1.0",
      trace: "write_trace"
    },
    safety: {
      riskLevel: actionName === "assert_json" ? "L2" : "L1",
      safety_check: true,
      unknown_action_policy: "reject"
    }
  };
}

function workflow(id: string, name: string, provider: string, platform: RPAWorkflow["platform"], steps: number, successRate: number, lastRun: string): RPAWorkflow {
  return {
    schemaVersion: "1.0",
    id,
    name,
    provider,
    platform,
    inputs: { keyword: "连衣裙夏季", category: "女装", page: 1 },
    steps: workflowSteps.slice(0, Math.min(steps, workflowSteps.length)),
    successRate,
    lastRun
  };
}
