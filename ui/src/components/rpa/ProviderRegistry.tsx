import { MoreVertical, TestTube2 } from "lucide-react";

import type { RPAProvider } from "../../types/rpa";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface ProviderRegistryProps {
  providers: RPAProvider[];
  activeProvider: string;
  onSelect: (provider: string) => void;
  onTest: (provider: string) => void;
}

export function ProviderRegistry({ providers, activeProvider, onSelect, onTest }: ProviderRegistryProps) {
  return (
    <Card className="h-full">
      <CardHeader className="min-w-0">
        <CardTitle className="min-w-0 truncate">Provider Registry</CardTitle>
      </CardHeader>
      <CardContent className="grid min-w-0 grid-cols-1 gap-3 min-[1500px]:grid-cols-2 min-[1900px]:grid-cols-3">
        {providers.map((provider) => (
          <button
            key={provider.name}
            className={`min-w-0 rounded-2xl border p-3 text-left transition hover:shadow-lift ${
              activeProvider === provider.name ? "border-blue-300 bg-blue-50/60" : "border-slate-200 bg-white"
            }`}
            onClick={() => onSelect(provider.name)}
          >
            <div className="flex min-w-0 items-center justify-between gap-2">
              <div className="min-w-0 truncate font-mono text-sm font-semibold text-slate-900">{provider.name}</div>
              <Badge tone={provider.status === "online" ? "green" : provider.status === "reserved" ? "slate" : "red"}>
                {provider.status === "reserved" ? "预留" : provider.status === "online" ? "在线" : "离线"}
              </Badge>
            </div>
            <div className="mt-3 grid grid-cols-[58px_minmax(0,1fr)] gap-y-1 text-xs text-slate-500">
              <span>平台</span><span className="truncate text-slate-800">{provider.platform}</span>
              <span>Manifest</span><span className="truncate text-slate-800">{provider.manifestVersion}</span>
              <span>支持动作</span><span className="truncate text-slate-800">{provider.actions.length || "-"}</span>
              <span>Observe</span><span className="truncate text-slate-800">{provider.observeModes.join("、") || "-"}</span>
              <span>成功率</span><span className="truncate text-slate-800">{provider.successRate ? `${provider.successRate}%` : "-"}</span>
            </div>
            <div className="mt-3 h-1.5 rounded-full bg-slate-100">
              <div className="h-1.5 rounded-full bg-emerald-500" style={{ width: `${provider.successRate ?? 12}%` }} />
            </div>
            <div className="mt-3 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_32px] gap-2">
              <Button size="sm" className="px-2" onClick={(event) => { event.stopPropagation(); onTest(provider.name); }}><TestTube2 className="h-3.5 w-3.5" />测试</Button>
              <Button size="sm" className="px-2">Manifest</Button>
              <Button size="icon"><MoreVertical className="h-4 w-4" /></Button>
            </div>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}
