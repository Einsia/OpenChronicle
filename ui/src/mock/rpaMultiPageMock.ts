export const overviewKpis = [
  { title: "Provider 在线", value: "5 / 6", note: "83% online", tone: "blue" },
  { title: "设备在线数", value: "128", note: "较昨日 +12", tone: "green" },
  { title: "Workflow 成功率", value: "96.2%", note: "近 7 日 +2.3pp", tone: "green" },
  { title: "今日执行次数", value: "1,842", note: "较昨日 +18.6%", tone: "blue" },
  { title: "异常恢复率", value: "92.7%", note: "自动恢复 511 次", tone: "green" },
  { title: "待审批", value: "6", note: "2 个高危待处理", tone: "orange" }
];

export const providerHealthRows = [
  { provider: "android_adb", states: ["healthy", "healthy", "healthy", "healthy", "healthy"] },
  { provider: "windows_uia", states: ["healthy", "healthy", "healthy", "healthy", "healthy"] },
  { provider: "playwright_browser", states: ["healthy", "degraded", "healthy", "healthy", "healthy"] },
  { provider: "api_worker", states: ["healthy", "degraded", "degraded", "healthy", "healthy"] },
  { provider: "ios_wda", states: ["unhealthy", "unhealthy", "degraded", "healthy", "offline"] },
  { provider: "harmony_hdc", states: ["offline", "offline", "offline", "offline", "offline"] }
];

export const executionTrend = [
  { day: "Mon", success: 1234, failure: 76 },
  { day: "Tue", success: 1421, failure: 82 },
  { day: "Wed", success: 1512, failure: 71 },
  { day: "Thu", success: 1635, failure: 64 },
  { day: "Fri", success: 1704, failure: 78 },
  { day: "Sat", success: 1809, failure: 69 },
  { day: "Sun", success: 1842, failure: 71 }
];

export const recentFailures = [
  { id: "task_1f9a8c3d", provider: "playwright_browser", reason: "Element not found", risk: "L2", time: "10 min ago" },
  { id: "task_8e7b2d11", provider: "windows_uia", reason: "UIA timeout", risk: "L1", time: "24 min ago" },
  { id: "task_7c4d9a22", provider: "android_adb", reason: "Device disconnected", risk: "L3", time: "36 min ago" },
  { id: "task_3a6f1e90", provider: "api_worker", reason: "HTTP 500", risk: "L2", time: "52 min ago" }
];

export const pendingActions = [
  { title: "待安全审批", desc: "高风险动作等待人工确认", count: 6, tone: "orange" },
  { title: "异常 Provider", desc: "ios_wda / harmony_hdc 需要处理", count: 2, tone: "red" },
  { title: "低成功率 Workflow", desc: "成功率低于 90%", count: 4, tone: "orange" },
  { title: "最近生成 Skill", desc: "等待审核或发布", count: 5, tone: "blue" }
];

export const fleetSummary = [
  { title: "在线设备", value: "42", note: "较昨日 +8" },
  { title: "忙碌设备", value: "15", note: "35.7% of online" },
  { title: "离线设备", value: "9", note: "较昨日 -3" },
  { title: "风险告警", value: "7", note: "需关注设备风险" }
];

export const fleetDevices = [
  { id: "android_31a7c2", provider: "android_adb", platform: "Android 12", status: "online", target: "淘宝搜索商品流程", task: "Step 02 · tap search", risk: "L2", heartbeat: "6s ago" },
  { id: "android_9f58b1", provider: "android_adb", platform: "Android 11", status: "online", target: "京东下单流程", task: "Step 04 · confirm order", risk: "L1", heartbeat: "9s ago" },
  { id: "android_b72d9e", provider: "android_adb", platform: "Android 13", status: "busy", target: "拼多多商品采集", task: "Step 06 · scroll list", risk: "L1", heartbeat: "12s ago" },
  { id: "desktop_7FK3", provider: "windows_uia", platform: "Windows 11", status: "online", target: "Report Studio", task: "Step 03 · export", risk: "L1", heartbeat: "8s ago" },
  { id: "chromium_124", provider: "playwright_browser", platform: "Chromium", status: "online", target: "console login", task: "Step 05 · verify", risk: "L2", heartbeat: "14s ago" },
  { id: "api_worker_01", provider: "api_worker", platform: "HTTP Worker", status: "busy", target: "POST /orders/search", task: "Step 02 · request", risk: "L0", heartbeat: "2s ago" },
  { id: "android_3c91de", provider: "android_adb", platform: "Android 12", status: "offline", target: "-", task: "-", risk: "L3", heartbeat: "3m 22s ago" }
];

export const heartbeatStream = [
  "19:31:20  android_31a7c2  online  Step 02 · tap search  6s ago",
  "19:31:18  android_9f58b1  online  Step 04 · confirm order  9s ago",
  "19:31:17  android_b72d9e  busy    Step 06 · scroll list  12s ago",
  "19:31:15  desktop_7FK3    online  Step 03 · export  8s ago"
];

export const anomalyLogs = [
  { level: "L3", text: "android_3c91de · Device offline > 180s", time: "3m 22s ago" },
  { level: "L2", text: "android_31a7c2 · Element not found: search_btn", time: "4m 34s ago" },
  { level: "L2", text: "android_1f0b88 · Screenshot mismatch > 30%", time: "5m 46s ago" },
  { level: "L1", text: "android_7a65c0 · Slow response: 8.2s", time: "7m 5s ago" }
];

export const workflowAssets = [
  { name: "淘宝搜索商品流程", schema: "1.1.3", provider: "android_adb", platform: "Android", steps: 17, success: "98.6%", lastRun: "2m ago", status: "ready" },
  { name: "浏览器登录回归", schema: "1.0.2", provider: "playwright_browser", platform: "Web", steps: 14, success: "97.1%", lastRun: "51m ago", status: "draft" },
  { name: "Windows 任务录制", schema: "1.0.0", provider: "windows_uia", platform: "Windows", steps: 22, success: "99.1%", lastRun: "2h ago", status: "ready" },
  { name: "移动端登录重试", schema: "1.0.0", provider: "android_adb", platform: "Android", steps: 12, success: "96.4%", lastRun: "3h ago", status: "validated" },
  { name: "API 数据抓取流程", schema: "1.0.0", provider: "api_worker", platform: "API", steps: 8, success: "99.8%", lastRun: "4h ago", status: "ready" }
];

export const workflowRuns = [
  { run: "run_20240515_193125", by: "admin", env: "Android_S23", steps: "17 / 17", result: "success", rate: "100%", duration: "00:01:24" },
  { run: "run_20240515_184211", by: "tester_02", env: "Pixel_7_Pro", steps: "17 / 17", result: "success", rate: "98.6%", duration: "00:01:37" },
  { run: "run_20240515_160344", by: "admin", env: "Android_S23", steps: "16 / 17", result: "partial", rate: "94.1%", duration: "00:01:56" }
];

export const skillSources = [
  { title: "淘宝搜索商品流程", id: "trace_20240508_193120", provider: "android_adb · Pixel 6", status: "success" },
  { title: "京东搜索商品流程", id: "trace_20240508_184512", provider: "android_adb · Pixel 6", status: "success" },
  { title: "拼多多浏览商品流程", id: "trace_20240508_175233", provider: "android_adb · Pixel 6", status: "success" },
  { title: "登录并进入首页", id: "trace_20240508_171104", provider: "android_adb · Pixel 6", status: "partial" }
];

export const skillGroups = [
  { id: "G1", name: "启动应用与进入搜索页", from: "6 steps", to: "1 step", saved: "83%" },
  { id: "G2", name: "输入搜索关键词", from: "5 steps", to: "1 step", saved: "80%" },
  { id: "G3", name: "执行搜索", from: "4 steps", to: "1 step", saved: "75%" },
  { id: "G4", name: "筛选与排序（可选）", from: "18 steps", to: "3 steps", saved: "83%" },
  { id: "G5", name: "浏览搜索结果", from: "42 steps", to: "5 steps", saved: "88%" }
];

export const executionQueue = [
  { priority: "P0", task: "淘宝搜索商品流程", id: "#a1b2c3d4", status: "运行中", progress: "45%", eta: "01:30", submitted: "19:35:12" },
  { priority: "P0", task: "Windows 任务录制", id: "#e5f6g7h8", status: "运行中", progress: "12%", eta: "02:10", submitted: "19:34:58" },
  { priority: "P1", task: "Browser 登录回归", id: "#i9j0k1l2", status: "排队中", progress: "-", eta: "01:45", submitted: "19:34:41" },
  { priority: "P1", task: "淘宝搜索商品流程", id: "#m3n4o5p6", status: "排队中", progress: "-", eta: "01:30", submitted: "19:34:30" },
  { priority: "P2", task: "API 数据抓取流程", id: "#u1v2w3x4", status: "成功", progress: "100%", eta: "01:32", submitted: "19:31:02" },
  { priority: "P0", task: "淘宝搜索商品流程", id: "#k7l8m9n0", status: "失败", progress: "18%", eta: "01:12", submitted: "19:27:14" }
];

export const executionLogs = [
  "19:36:00.125 INFO  [Engine] Execution started · workflow=淘宝搜索商品流程 · provider=android_adb",
  "19:36:00.236 INFO  [Device] Connected to android-0014 (emulator-5554)",
  "19:36:01.543 INFO  [Step 02] Observe Keyframe · screenshot captured · ui tree updated",
  "19:36:03.112 INFO  [Step 03] Action Inspector · tap search field",
  "19:36:03.678 WARN  [Step 03] Element not found on first attempt, retrying (1/3)",
  "19:36:04.889 INFO  [Step 03] Action executed successfully"
];

export const traceList = [
  { id: "task_20240522_0017", workflow: "wf_taobao_search", status: "failed", note: "Step 04 failed" },
  { id: "task_20240522_0016", workflow: "wf_taobao_search", status: "partial", note: "Step 06 failed" },
  { id: "task_20240522_0015", workflow: "wf_taobao_search", status: "success", note: "completed" },
  { id: "task_20240522_0014", workflow: "wf_login_flow", status: "success", note: "completed" }
];

export const traceReplaySteps = [
  { step: "1", title: "Observe Home Screen", action: "observe · android_adb", status: "success", time: "00:00.000" },
  { step: "2", title: "Tap Search Input", action: "tap · android_adb", status: "success", time: "00:07.421" },
  { step: "3", title: "Input Keyword", action: "input_text · android_adb", status: "success", time: "00:18.932" },
  { step: "4", title: "Tap Search Button", action: "tap · android_adb", status: "failed", time: "00:31.114" },
  { step: "5", title: "Observe Result List", action: "observe · android_adb", status: "skipped", time: "00:45.672" }
];

export const approvals = [
  { action: "安装 APK", device: "Pixel_7_001", resource: "com.example.malicious.apk", risk: "L3", time: "2 分钟前" },
  { action: "卸载 App", device: "Pixel_3a_002", resource: "com.bank.mobile", risk: "L3", time: "5 分钟前" },
  { action: "支付", device: "Pixel_7_001", resource: "¥1,299.00", risk: "L3", time: "8 分钟前" },
  { action: "下单", device: "Pixel_4a_003", resource: "Order #A20240518001", risk: "L2", time: "12 分钟前" },
  { action: "发消息", device: "Pixel_3a_002", resource: "To: +86 188****1234", risk: "L2", time: "15 分钟前" },
  { action: "读取通讯录", device: "Pixel_7_001", resource: "Access contacts", risk: "L2", time: "18 分钟前" },
  { action: "访问剪贴板", device: "Pixel_4a_003", resource: "clipboard content", risk: "L2", time: "22 分钟前" },
  { action: "删除文件", device: "Pixel_3a_002", resource: "/sdcard/Download/report.pdf", risk: "L1", time: "25 分钟前" }
];

export const memoryCategories = [
  { name: "Trace Memory", count: 1248, desc: "从 Trace 中提炼观察与模式" },
  { name: "Workflow Memory", count: 642, desc: "Workflow 设计与优化经验" },
  { name: "Skill Memory", count: 389, desc: "Skill 构建与调优知识" },
  { name: "Recovery Experience", count: 287, desc: "异常恢复与错误处理经验" },
  { name: "Success Experience", count: 523, desc: "高成功率方案与模式" },
  { name: "Candidate Skills", count: 176, desc: "待验证技能片段" }
];

export const memoryItems = [
  { title: "淘宝搜索页 - 关键词输入稳定定位", relevance: "0.96", fresh: "2h ago", type: "Trace", compression: "原始" },
  { title: "搜索商品流程 - 结果页加载等待策略", relevance: "0.92", fresh: "6h ago", type: "Workflow", compression: "压缩 60%" },
  { title: "滑动到底部的通用实现", relevance: "0.89", fresh: "1d ago", type: "Skill", compression: "压缩 45%" },
  { title: "输入法弹出导致元素遮挡的恢复经验", relevance: "0.88", fresh: "2d ago", type: "Recovery", compression: "压缩 70%" },
  { title: "搜索无结果时的分支处理模式", relevance: "0.81", fresh: "3d ago", type: "Workflow", compression: "原始" }
];

export const settingsSections = [
  "Provider Config", "API Base URL", "Data Directory", "Screenshot Policy", "OCR", "Safety Policy", "Approval Rules", "Log Retention", "Skill Output Format", "Theme", "User Permissions"
];
