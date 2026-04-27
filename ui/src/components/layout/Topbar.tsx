import { Bell, ChevronDown, Search, UserCircle } from "lucide-react";

import { Badge } from "../ui/badge";
import { ProviderSwitcher } from "../rpa/ProviderSwitcher";

interface TopbarProps {
  title: string;
  activeProvider: string;
  onProviderChange: (provider: string) => void;
}

export function Topbar({ title, activeProvider, onProviderChange }: TopbarProps) {
  return (
    <header className="flex h-[72px] shrink-0 items-center gap-3 overflow-hidden border-b border-slate-200 bg-white/95 px-4 backdrop-blur lg:px-6">
      <h1 className="w-[clamp(210px,22vw,420px)] shrink-0 truncate text-xl font-semibold tracking-normal text-slate-950 2xl:text-2xl">{title}</h1>
      <div className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden">
        <ProviderSwitcher activeProvider={activeProvider} onProviderChange={onProviderChange} />
        <select className="hidden h-10 max-w-[190px] shrink-0 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 xl:block">
          <option>淘宝搜索商品流程</option>
          <option>生产环境 (Prod)</option>
          <option>Browser 登录回归</option>
        </select>
        <Badge tone="orange" className="hidden h-10 shrink-0 rounded-xl px-4 xl:inline-flex">L2 中风险</Badge>
        <div className="ml-auto flex h-10 min-w-[120px] max-w-[280px] flex-1 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-400">
          <Search className="h-4 w-4 shrink-0" />
          <input className="min-w-0 flex-1 border-0 bg-transparent outline-none" placeholder="搜索设备、流程、动作..." />
          <span className="hidden shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500 2xl:inline">⌘K</span>
        </div>
        <button className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600">
          <Bell className="h-5 w-5" />
          <span className="absolute -right-1 -top-1 rounded-full bg-red-500 px-1.5 text-[10px] font-semibold text-white">12</span>
        </button>
        <div className="hidden shrink-0 items-center gap-2 xl:flex">
          <UserCircle className="h-9 w-9 text-slate-700" />
          <div className="text-xs">
            <div className="font-semibold text-slate-900">张工程师</div>
            <div className="text-slate-500">管理员</div>
          </div>
          <ChevronDown className="h-4 w-4 text-slate-400" />
        </div>
      </div>
    </header>
  );
}
