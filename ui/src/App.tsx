import { useEffect, useMemo, useState } from "react";

import { Sidebar } from "./components/layout/Sidebar";
import { Topbar } from "./components/layout/Topbar";
import { DeviceFleetPage } from "./pages/rpa/DeviceFleetPage";
import { ExecutorPage } from "./pages/rpa/ExecutorPage";
import { MemoryCenterPage } from "./pages/rpa/MemoryCenterPage";
import { OverviewDashboard } from "./pages/rpa/OverviewDashboard";
import { ProviderStudio } from "./pages/rpa/ProviderStudio";
import { RealtimeConsole } from "./pages/rpa/RealtimeConsole";
import { SafetyApprovalPage } from "./pages/rpa/SafetyApprovalPage";
import { SettingsPage } from "./pages/rpa/SettingsPage";
import { SkillBuilderPage } from "./pages/rpa/SkillBuilderPage";
import { TraceReplayPage } from "./pages/rpa/TraceReplayPage";
import { WorkflowLibraryPage } from "./pages/rpa/WorkflowLibraryPage";

const routeByNav: Record<string, string> = {
  总览: "/rpa/overview",
  实时调试: "/rpa/realtime",
  "RPA Provider 管理": "/rpa/providers",
  设备舰队: "/rpa/fleet",
  "Workflow 库": "/rpa/workflows",
  技能构建: "/rpa/skills",
  执行器: "/rpa/executor",
  "Trace 回放": "/rpa/traces",
  安全审批: "/rpa/safety",
  记忆中心: "/rpa/memory",
  设置: "/rpa/settings"
};

const titleByRoute: Record<string, string> = {
  "/rpa/overview": "总览 · Global Operations Cockpit",
  "/rpa/realtime": "实时调试控制台",
  "/rpa/providers": "RPA Provider 管理与 Workflow Studio",
  "/rpa/fleet": "设备舰队",
  "/rpa/workflows": "Workflow 库",
  "/rpa/skills": "技能构建",
  "/rpa/executor": "执行器",
  "/rpa/traces": "Trace 回放",
  "/rpa/safety": "安全审批",
  "/rpa/memory": "记忆中心",
  "/rpa/settings": "设置"
};

function normalizePath(pathname: string) {
  if (pathname === "/" || pathname === "/rpa") {
    return "/rpa/overview";
  }
  return Object.values(routeByNav).includes(pathname) ? pathname : "/rpa/overview";
}

export function App() {
  const [path, setPath] = useState(() => normalizePath(window.location.pathname));
  const [activeProvider, setActiveProvider] = useState("android_adb");
  const activeNav = Object.entries(routeByNav).find(([, route]) => route === path)?.[0] ?? "总览";
  const title = titleByRoute[path] ?? "OpenChronicle RPA Harness";

  useEffect(() => {
    const normalized = normalizePath(window.location.pathname);
    if (window.location.pathname !== normalized) {
      window.history.replaceState(null, "", normalized);
    }
    const onPop = () => setPath(normalizePath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const page = useMemo(() => {
    switch (path) {
      case "/rpa/realtime":
        return <RealtimeConsole activeProvider={activeProvider} onProviderChange={setActiveProvider} />;
      case "/rpa/providers":
        return <ProviderStudio activeProvider={activeProvider} onProviderChange={setActiveProvider} />;
      case "/rpa/fleet":
        return <DeviceFleetPage />;
      case "/rpa/workflows":
        return <WorkflowLibraryPage />;
      case "/rpa/skills":
        return <SkillBuilderPage />;
      case "/rpa/executor":
        return <ExecutorPage />;
      case "/rpa/traces":
        return <TraceReplayPage />;
      case "/rpa/safety":
        return <SafetyApprovalPage />;
      case "/rpa/memory":
        return <MemoryCenterPage />;
      case "/rpa/settings":
        return <SettingsPage />;
      case "/rpa/overview":
      default:
        return <OverviewDashboard />;
    }
  }, [activeProvider, path]);

  function navigate(label: string) {
    const nextPath = routeByNav[label] ?? "/rpa/overview";
    window.history.pushState(null, "", nextPath);
    setPath(nextPath);
  }

  return (
    <div className="h-screen min-h-0 w-full overflow-hidden bg-slate-50">
      <Sidebar active={activeNav} onNavigate={navigate} />
      <div className="flex h-full min-h-0 min-w-0 flex-col pl-[232px]">
        <Topbar title={title} activeProvider={activeProvider} onProviderChange={setActiveProvider} />
        <main className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-4 lg:p-5">{page}</main>
      </div>
    </div>
  );
}
