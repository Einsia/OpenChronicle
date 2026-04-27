import { CheckCircle2, CircleDot, XCircle } from "lucide-react";

import { stableRecordingRules } from "../../mock/rpaHarnessMock";
import { cn } from "../../lib/utils";
import type { RecordingFlowStep } from "../../types/rpa";
import { Badge } from "../ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface RecordingFlowProps {
  steps: RecordingFlowStep[];
}

export function RecordingFlow({ steps }: RecordingFlowProps) {
  return (
    <Card className="h-full">
      <CardHeader className="min-w-0">
        <CardTitle className="min-w-0 truncate">录制工作流 / Recording Flow</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        <div className="grid grid-cols-1 gap-4 min-[1500px]:grid-cols-[minmax(0,1fr)_180px]">
          <div className="space-y-2">
            {steps.map((step, index) => (
              <div
                key={step.id}
                className={cn(
                  "relative rounded-xl border p-3 pl-11",
                  step.status === "current" && "border-blue-300 bg-blue-50 shadow-lift",
                  step.status === "done" && "border-emerald-100 bg-white",
                  step.status === "pending" && "border-slate-200 bg-white",
                  step.status === "failed" && "border-red-200 bg-red-50"
                )}
              >
                {index < steps.length - 1 ? <span className="absolute left-[22px] top-9 h-7 w-px bg-slate-200" /> : null}
                <span className="absolute left-4 top-3.5">{iconFor(step.status)}</span>
                <div className="flex min-w-0 items-center justify-between gap-2">
                  <div className="min-w-0 truncate text-sm font-semibold text-slate-900">{step.label}</div>
                  <Badge tone={step.status === "done" ? "green" : step.status === "current" ? "blue" : step.status === "failed" ? "red" : "slate"}>{step.id}</Badge>
                </div>
                <div className="mt-1 text-xs text-slate-500">{step.description}</div>
              </div>
            ))}
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="mb-3 text-sm font-semibold text-slate-900">稳定录制策略</div>
            <ul className="space-y-2 text-xs text-slate-600">
              {stableRecordingRules.map((rule) => (
                <li key={rule} className="flex gap-2">
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 flex-none text-emerald-500" />
                  <span>{rule}</span>
                </li>
              ))}
            </ul>
            <div className="mt-4 rounded-xl bg-white p-3">
              <div className="text-xs text-slate-500">稳定性指数</div>
              <div className="mt-1 text-2xl font-semibold text-emerald-600">98 / 100</div>
              <div className="mt-2 h-2 rounded-full bg-slate-200">
                <div className="h-2 w-[98%] rounded-full bg-emerald-500" />
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function iconFor(status: RecordingFlowStep["status"]) {
  if (status === "done") return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === "current") return <CircleDot className="h-4 w-4 text-blue-600" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-red-500" />;
  return <CircleDot className="h-4 w-4 text-slate-300" />;
}
