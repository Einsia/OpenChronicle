import { useMemo, useState } from "react";

import { KpiCard } from "../../components/dashboard/KpiCard";
import { ActionInspector } from "../../components/rpa/ActionInspector";
import { DeviceLiveView } from "../../components/rpa/DeviceLiveView";
import { RecordingFlow } from "../../components/rpa/RecordingFlow";
import { SafetyApprovalPanel } from "../../components/rpa/SafetyApprovalPanel";
import { TimelineLog } from "../../components/rpa/TimelineLog";
import { WorkflowSkillBuilder } from "../../components/rpa/WorkflowSkillBuilder";
import { rpaApi } from "../../lib/rpaApi";
import {
  bridgeInspectorNodes,
  realtimeKpis,
  recordingFlow,
  safetyApprovals as initialApprovals,
  traceSteps
} from "../../mock/rpaHarnessMock";
import type { ApprovalStatus, GeneratedSkill, RecordingFlowStep, RPATraceStep, SafetyApproval } from "../../types/rpa";

interface RealtimeConsoleProps {
  activeProvider: string;
  onProviderChange: (provider: string) => void;
}

export function RealtimeConsole({ activeProvider, onProviderChange }: RealtimeConsoleProps) {
  const [flow, setFlow] = useState<RecordingFlowStep[]>(recordingFlow);
  const [timeline, setTimeline] = useState<RPATraceStep[]>(traceSteps);
  const [selectedStepId, setSelectedStepId] = useState(traceSteps[2].stepId);
  const [approvals, setApprovals] = useState<SafetyApproval[]>(initialApprovals);
  const selectedStep = useMemo(() => timeline.find((step) => step.stepId === selectedStepId) ?? timeline[0], [selectedStepId, timeline]);

  function appendMockStep(actionName: string, pageState: string, result = "success") {
    const nextNumber = timeline.length + 1;
    const next: RPATraceStep = {
      ...selectedStep,
      stepId: `Step ${nextNumber}`,
      provider: activeProvider,
      timestamp: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      actionName,
      pageState,
      duration: actionName === "capture_keyframe" ? "0.42s" : "0.78s",
      observation: {
        ...selectedStep.observation,
        keyframe: actionName === "capture_keyframe",
        tree: actionName === "read_ui_tree" ? "mock UI tree / DOM / window tree" : undefined
      },
      action: {
        ...selectedStep.action,
        action: actionName,
        provider: activeProvider
      },
      result: {
        status: result,
        schema_version: "1.0",
        write_trace: true
      }
    };
    setTimeline((current) => [...current, next]);
    setSelectedStepId(next.stepId);
  }

  function runStep() {
    setFlow((current) => {
      const currentIndex = current.findIndex((step) => step.status === "current");
      if (currentIndex < 0 || currentIndex === current.length - 1) return current;
      return current.map((step, index) => {
        if (index <= currentIndex) return { ...step, status: "done" };
        if (index === currentIndex + 1) return { ...step, status: "current" };
        return step;
      });
    });
    appendMockStep("safety_check", "POLICY_GATE");
  }

  async function decideApproval(approval: SafetyApproval, status: ApprovalStatus) {
    const updated = await rpaApi.updateApproval(approval, status);
    setApprovals((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    appendMockStep(status === "approved" ? "approval_approved" : "approval_rejected", approval.action, status === "approved" ? "success" : "failed");
  }

  async function generateSkill(format: GeneratedSkill["format"]) {
    const skill = await rpaApi.generateSkill(format);
    appendMockStep("skill_generated", skill.name);
    return skill;
  }

  return (
    <div className="space-y-4">
      <div className="kpi-grid grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {realtimeKpis.map((metric, index) => <KpiCard key={metric.title} metric={metric} index={index} />)}
      </div>
      <div className="rpa-page-grid xl:grid-cols-2 min-[1720px]:grid-cols-[minmax(0,1.05fr)_minmax(0,0.82fr)_minmax(0,1.25fr)]">
        <DeviceLiveView
          activeProvider={activeProvider}
          onProviderChange={onProviderChange}
          onCaptureKeyframe={() => appendMockStep("capture_keyframe", "KEYFRAME_SAVED")}
          onReadTree={() => appendMockStep("read_ui_tree", "TREE_OBSERVED")}
          onRunStep={runStep}
        />
        <RecordingFlow steps={flow} />
        <ActionInspector traceStep={selectedStep} bridgeNodes={bridgeInspectorNodes.map((node) => node.id === "provider" ? { ...node, label: activeProvider } : node)} />
      </div>
      <div className="rpa-page-grid xl:grid-cols-2 min-[1720px]:grid-cols-[minmax(0,1.12fr)_minmax(0,0.94fr)_minmax(0,1fr)]">
        <TimelineLog rows={timeline} selectedStepId={selectedStepId} onSelect={(step) => setSelectedStepId(step.stepId)} />
        <WorkflowSkillBuilder onGenerateSkill={generateSkill} />
        <SafetyApprovalPanel approvals={approvals} onDecision={(approval, status) => void decideApproval(approval, status)} />
      </div>
    </div>
  );
}
