import { ArrowRight, CheckCircle2 } from "lucide-react";

import type { BridgeNode } from "../../types/rpa";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface BridgeInspectorProps {
  nodes: BridgeNode[];
}

export function BridgeInspector({ nodes }: BridgeInspectorProps) {
  return (
    <Card>
      <CardHeader className="min-w-0 py-2">
        <CardTitle className="min-w-0 truncate text-sm">Bridge Inspector</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 items-center gap-2 overflow-x-auto py-3">
        {nodes.map((node, index) => (
          <div key={node.id} className="flex shrink-0 items-center gap-2">
            <div className="w-[150px] rounded-xl border border-slate-200 bg-white p-3 text-xs">
              <div className="flex items-center justify-between gap-2 font-semibold text-slate-800">
                <span className="truncate">{node.label}</span>
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
              </div>
              <div className="mt-1 truncate text-slate-500">{node.detail}</div>
              <div className="mt-1 text-emerald-600">● {node.latencyMs}ms</div>
            </div>
            {index < nodes.length - 1 ? <ArrowRight className="h-4 w-4 shrink-0 text-slate-300" /> : null}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
