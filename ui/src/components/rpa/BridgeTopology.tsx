import { ArrowDown, ArrowRight, CheckCircle2 } from "lucide-react";

import type { BridgeNode } from "../../types/rpa";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface BridgeTopologyProps {
  nodes: BridgeNode[];
}

export function BridgeTopology({ nodes }: BridgeTopologyProps) {
  const top = nodes.slice(0, 5);
  const bottom = nodes.slice(5);

  return (
    <Card className="h-full">
      <CardHeader className="min-w-0">
        <CardTitle className="min-w-0 truncate">Bridge Topology / 桥接拓扑</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0 space-y-4">
        <div className="space-y-3">
          {top.map((node, index) => (
            <div key={node.id} className="flex min-w-0 items-center gap-3">
              <TopologyNode node={node} />
              {index < top.length - 1 ? <ArrowRight className="h-4 w-4 shrink-0 text-slate-300" /> : null}
            </div>
          ))}
        </div>
        <div className="flex justify-center">
          <ArrowDown className="h-5 w-5 text-slate-300" />
        </div>
        <div className="grid grid-cols-1 gap-3">
          {bottom.map((node) => <TopologyNode key={node.id} node={node} />)}
        </div>
      </CardContent>
    </Card>
  );
}

function TopologyNode({ node }: { node: BridgeNode }) {
  return (
    <div className="flex min-h-[64px] min-w-0 flex-1 items-center gap-3 rounded-2xl border border-blue-100 bg-blue-50/35 p-3">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-blue-700">
        <CheckCircle2 className="h-5 w-5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-slate-900">{node.label}</div>
        <div className="truncate text-xs text-slate-500">{node.detail}</div>
      </div>
      <div className="shrink-0 text-xs text-emerald-600">● {node.latencyMs}ms</div>
    </div>
  );
}
