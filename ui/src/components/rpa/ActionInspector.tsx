import { ArrowRight, Copy } from "lucide-react";

import { formatJson } from "../../lib/utils";
import type { BridgeNode, RPATraceStep } from "../../types/rpa";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { BridgeInspector } from "./BridgeInspector";

interface ActionInspectorProps {
  traceStep: RPATraceStep;
  bridgeNodes: BridgeNode[];
}

export function ActionInspector({ traceStep, bridgeNodes }: ActionInspectorProps) {
  const action = traceStep.action;
  const risk = String(traceStep.safety.riskLevel ?? "L1");

  async function copyJson() {
    await navigator.clipboard?.writeText(formatJson(action));
  }

  return (
    <Card className="h-full">
      <CardHeader className="min-w-0 flex-wrap">
        <CardTitle className="min-w-0 truncate">动作检查器 / Action Inspector</CardTitle>
        <div className="flex shrink-0 items-center gap-2 text-xs text-slate-500">
          <span>{traceStep.stepId}</span>
          <Button size="sm" onClick={copyJson}><Copy className="h-3.5 w-3.5" />复制 JSON</Button>
        </div>
      </CardHeader>
      <CardContent className="min-w-0 space-y-4">
        <div className="grid grid-cols-1 gap-4 min-[1720px]:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div className="min-w-0 overflow-hidden rounded-xl border border-slate-200">
            {[
              ["动作类型", String(action.action)],
              ["Provider", traceStep.provider],
              ["目标元素", String((action.target as Record<string, unknown>)?.type ?? "EditText")],
              ["resource-id / selector", String((action.target as Record<string, unknown>)?.resource_id ?? "selector")],
              ["text / value", String(action.value ?? (action.target as Record<string, unknown>)?.text ?? "-")],
              ["置信度", String(action.confidence ?? "-")],
              ["等待条件", "visible"],
              ["超时时间", "10s"],
              ["重试策略", "最多 3 次，间隔 2s"],
              ["风险等级", risk],
              ["审批要求", risk === "L2" || risk === "L3" ? "需要审批" : "无需审批"]
            ].map(([label, value]) => (
              <div key={label} className="grid grid-cols-[120px_minmax(0,1fr)] border-b border-slate-100 text-xs last:border-b-0">
                <div className="bg-slate-50 px-3 py-2 text-slate-500">{label}</div>
                <div className="min-w-0 break-words px-3 py-2 font-medium text-slate-800">
                  {label === "风险等级" ? <Badge tone={risk === "L3" ? "red" : risk === "L2" ? "orange" : "green"}>{value}</Badge> : value}
                </div>
              </div>
            ))}
          </div>
          <pre className="max-h-[300px] min-w-0 overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-4 font-mono text-[11px] leading-5 text-blue-900">
            {formatJson(action)}
          </pre>
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-slate-600">执行截图</div>
          <div className="grid grid-cols-[minmax(0,1fr)_40px_minmax(0,1fr)] items-center gap-3">
            <ScreenshotThumb label="执行前截图" />
            <ArrowRight className="mx-auto h-5 w-5 text-slate-400" />
            <ScreenshotThumb label="执行后截图" />
          </div>
        </div>
        <BridgeInspector nodes={bridgeNodes} />
      </CardContent>
    </Card>
  );
}

function ScreenshotThumb({ label }: { label: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-slate-200 bg-white p-2">
      <div className="mb-2 truncate text-xs text-slate-500">{label}</div>
      <div className="h-20 rounded-lg border border-orange-100 bg-gradient-to-r from-orange-50 to-red-50 p-2">
        <div className="h-5 rounded-full border border-orange-200 bg-white" />
        <div className="mt-3 grid grid-cols-4 gap-2">
          {Array.from({ length: 4 }).map((_, index) => <div key={index} className="h-6 rounded-lg bg-orange-300" />)}
        </div>
      </div>
    </div>
  );
}
