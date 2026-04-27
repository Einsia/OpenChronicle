import { Copy } from "lucide-react";

import { formatJson } from "../../lib/utils";
import type { RPAProvider } from "../../types/rpa";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface ProviderDetailProps {
  provider: RPAProvider;
}

export function ProviderDetail({ provider }: ProviderDetailProps) {
  const manifest = {
    provider: provider.name,
    version: provider.manifestVersion,
    platform: provider.platform,
    adapter_path: provider.adapterPath,
    safety_level: provider.safetyLevel,
    observe: provider.observeModes,
    actions: provider.actions,
    capabilities: {
      ocr: provider.observeModes.includes("OCR"),
      ui_tree: provider.observeModes.some((mode) => mode.includes("tree")),
      screenshot: provider.observeModes.includes("keyframe")
    }
  };

  return (
    <Card className="h-full">
      <CardHeader className="min-w-0">
        <CardTitle className="min-w-0 truncate">Provider Detail / {provider.name}</CardTitle>
        <Badge tone={provider.status === "online" ? "green" : "slate"}>{provider.status === "online" ? "在线" : "预留"}</Badge>
      </CardHeader>
      <CardContent className="min-w-0 space-y-3">
        <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-y-2 text-xs">
          <span className="text-slate-500">Provider Name</span><span className="min-w-0 break-all font-mono text-slate-900">{provider.name}</span>
          <span className="text-slate-500">Adapter Path</span><span className="min-w-0 break-all font-mono text-slate-900">{provider.adapterPath}</span>
          <span className="text-slate-500">安全等级</span><Badge tone={provider.safetyLevel === "high" ? "green" : "orange"}>{provider.safetyLevel}</Badge>
          <span className="text-slate-500">Observe Modes</span>
          <span className="flex min-w-0 flex-wrap gap-1">{provider.observeModes.map((mode) => <Badge key={mode} tone="blue">{mode}</Badge>)}</span>
          <span className="text-slate-500">支持动作</span><span className="min-w-0 break-words">{provider.actions.length ? `${provider.actions.length} (${provider.actions.slice(0, 5).join(", ")}...)` : "-"}</span>
          <span className="text-slate-500">当前设备</span><span>3 台在线 / 1 台离线</span>
          <span className="text-slate-500">Heartbeat</span><span className="text-emerald-600">● {provider.latencyMs || 0}ms 前</span>
        </div>
        <div className="min-w-0 overflow-hidden rounded-xl border border-slate-200">
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-3 py-2 text-xs font-semibold">
            <span className="min-w-0 truncate">Manifest ({provider.manifestVersion})</span>
            <Button size="sm" className="shrink-0"><Copy className="h-3.5 w-3.5" />复制</Button>
          </div>
          <pre className="max-h-[250px] min-w-0 overflow-auto bg-slate-50 p-3 font-mono text-[11px] leading-5 text-blue-900">{formatJson(manifest)}</pre>
        </div>
      </CardContent>
    </Card>
  );
}
