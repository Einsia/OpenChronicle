import {
  Bot,
  Database,
  FileClock,
  FolderKanban,
  GitBranch,
  Home,
  MonitorSmartphone,
  Network,
  PlayCircle,
  Settings,
  ShieldCheck
} from "lucide-react";

import { cn } from "../../lib/utils";
import { Badge } from "../ui/badge";

const iconByLabel = {
  总览: Home,
  实时调试: PlayCircle,
  "RPA Provider 管理": Network,
  设备舰队: MonitorSmartphone,
  "Workflow 库": FolderKanban,
  技能构建: GitBranch,
  执行器: Bot,
  "Trace 回放": FileClock,
  安全审批: ShieldCheck,
  记忆中心: Database,
  设置: Settings
};

interface SidebarProps {
  active: string;
  onNavigate: (label: string) => void;
}

export function Sidebar({ active, onNavigate }: SidebarProps) {
  return (
    <aside className="fixed left-0 top-0 z-20 flex h-screen w-[232px] shrink-0 flex-col overflow-hidden border-r border-slate-200 bg-white">
      <div className="flex h-[86px] shrink-0 items-center gap-3 border-b border-slate-100 px-6">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-lift">
          <Network className="h-6 w-6" />
        </div>
        <div className="min-w-0">
          <div className="truncate text-base font-semibold leading-5 text-slate-950">OpenChronicle</div>
          <div className="truncate text-base font-semibold leading-5 text-slate-950">Harness</div>
        </div>
      </div>
      <nav className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-5">
        {Object.entries(iconByLabel).map(([label, Icon]) => {
          const isActive = active === label;
          return (
            <button
              key={label}
              className={cn(
                "flex h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium transition",
                isActive ? "bg-blue-50 text-blue-700 ring-1 ring-blue-100" : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"
              )}
              onClick={() => onNavigate(label)}
            >
              <Icon className="h-5 w-5 shrink-0" />
              <span className="min-w-0 flex-1 truncate">{label}</span>
              {label === "安全审批" ? <Badge tone="red" className="h-5 shrink-0 px-2">6</Badge> : null}
            </button>
          );
        })}
      </nav>
      <div className="shrink-0 space-y-2 border-t border-slate-100 p-4 text-xs text-slate-500">
        <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">← 收起侧边栏</div>
        <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">
          <div>企业版 v2.4.1</div>
          <div className="mt-1 flex items-center gap-1 text-emerald-600">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            在线
          </div>
        </div>
        <div>© 2024 OpenChronicle Inc.</div>
      </div>
    </aside>
  );
}
