import { Copy, FileJson, GitBranchPlus, Pencil, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { formatJson } from "../../lib/utils";
import { stableRecordingRules } from "../../mock/rpaHarnessMock";
import type { RPAWorkflow, WorkflowStep } from "../../types/rpa";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface RecordingEditStudioProps {
  workflow: RPAWorkflow;
  initialSteps: WorkflowStep[];
  onSave: (steps: WorkflowStep[]) => Promise<void>;
}

export function RecordingEditStudio({ workflow, initialSteps, onSave }: RecordingEditStudioProps) {
  const [steps, setSteps] = useState(initialSteps);
  const [selectedStepId, setSelectedStepId] = useState(initialSteps[0]?.id ?? "1");
  const [showJson, setShowJson] = useState(false);
  const selectedStep = steps.find((step) => step.id === selectedStepId) ?? steps[0];
  const workflowJson = useMemo(() => ({ ...workflow, schemaVersion: "1.0", steps }), [steps, workflow]);

  function insertStep() {
    const next: WorkflowStep = {
      id: String(steps.length + 1),
      action: "verify_ocr",
      provider: "android_adb",
      description: "新增 OCR 校验步骤",
      result: "waiting",
      verify: { ocr_priority: true, fallback_area: "primary_content" }
    };
    setSteps((current) => [...current, next]);
    setSelectedStepId(next.id);
  }

  function editStep() {
    setSteps((current) =>
      current.map((step) =>
        step.id === selectedStepId
          ? { ...step, description: `${step.description}（已编辑）`, safety: { safety_check: true, unknown_action: "reject" } }
          : step
      )
    );
  }

  function deleteStep() {
    setSteps((current) => current.filter((step) => step.id !== selectedStepId));
    setSelectedStepId(steps[0]?.id ?? "1");
  }

  return (
    <Card className="h-full">
      <CardHeader className="min-w-0 flex-wrap">
        <CardTitle className="min-w-0 truncate">录制与编辑 Studio</CardTitle>
        <select className="h-8 max-w-full rounded-lg border border-slate-200 px-2 text-xs" defaultValue={workflow.name}>
          <option>{workflow.name}</option>
          <option>browser_login_flow</option>
        </select>
      </CardHeader>
      <CardContent className="grid min-w-0 grid-cols-1 gap-4 min-[1500px]:grid-cols-[minmax(0,1fr)_220px]">
        <div className="min-w-0">
          <div className="mb-3 flex flex-wrap gap-2">
            <Button size="sm" variant="danger"><span className="h-2 w-2 rounded-full bg-red-500" />开始录制</Button>
            <Button size="sm" onClick={insertStep}><Plus className="h-3.5 w-3.5" />插入步骤</Button>
            <Button size="sm"><GitBranchPlus className="h-3.5 w-3.5" />条件分支</Button>
            <Button size="sm"><RotateCcw className="h-3.5 w-3.5" />重试策略</Button>
            <Button size="sm" onClick={() => setShowJson((value) => !value)}><FileJson className="h-3.5 w-3.5" />预览 JSON</Button>
            <Button size="sm" variant="primary" onClick={() => void onSave(steps)}><Save className="h-3.5 w-3.5" />保存 Workflow</Button>
          </div>
          {showJson ? (
            <pre className="h-[302px] min-w-0 overflow-auto rounded-xl bg-slate-950 p-4 font-mono text-xs leading-5 text-slate-100">{formatJson(workflowJson)}</pre>
          ) : (
            <div className="min-w-0 space-y-2">
              {steps.map((step) => (
                <button
                  key={step.id}
                  className={`grid w-full min-w-0 grid-cols-[34px_minmax(0,1fr)_96px_68px] items-center gap-2 rounded-xl border p-2 text-left text-xs transition ${
                    selectedStepId === step.id ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"
                  }`}
                  onClick={() => setSelectedStepId(step.id)}
                >
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 font-semibold">{step.id}</span>
                  <span className="min-w-0">
                    <span className="block truncate font-mono font-semibold text-slate-900">{step.action}</span>
                    <span className="block truncate text-slate-500">{step.description}</span>
                  </span>
                  <Badge tone={step.provider === "system" ? "slate" : "green"}>{step.provider}</Badge>
                  <span className="flex gap-1">
                    <Pencil className="h-3.5 w-3.5 text-slate-400" />
                    <Copy className="h-3.5 w-3.5 text-slate-400" />
                    <Trash2 className="h-3.5 w-3.5 text-slate-400" />
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="mb-3 text-sm font-semibold text-slate-900">稳定录制原则</div>
          <ul className="space-y-2 text-xs text-slate-600">
            {stableRecordingRules.map((rule) => <li key={rule}>● {rule}</li>)}
          </ul>
          <div className="mt-4 rounded-xl bg-white p-3 text-xs">
            <div className="font-semibold text-slate-900">当前 Step</div>
            <div className="mt-2 truncate font-mono text-blue-700">{selectedStep?.action}</div>
            <div className="mt-1 text-slate-500">{selectedStep?.description}</div>
            <div className="mt-3 flex gap-2">
              <Button size="sm" onClick={editStep}>编辑</Button>
              <Button size="sm" variant="danger" onClick={deleteStep}>删除</Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
