export type RPAPlatform = "android" | "windows" | "browser" | "api" | "ios" | "harmonyos";
export type RPAStatus = "online" | "offline" | "busy" | "error" | "reserved";
export type RiskLevel = "L0" | "L1" | "L2" | "L3";
export type ApprovalStatus = "pending" | "approved" | "rejected";
export type FlowStatus = "done" | "current" | "pending" | "failed";
export type SkillOutputFormat = "YAML" | "JSON";
export type SkillArtifactFormat = "skill.yaml" | "workflow.json";

export interface RPAProvider {
  name: string;
  label: string;
  platform: RPAPlatform;
  status: RPAStatus;
  manifestVersion: string;
  adapterPath: string;
  safetyLevel: "low" | "medium" | "high";
  actions: string[];
  observeModes: string[];
  successRate?: number;
  latencyMs?: number;
}

export interface RPADevice {
  deviceId: string;
  provider: string;
  platform: RPAPlatform;
  status: RPAStatus;
  currentTarget: string;
  lastHeartbeat: string;
  currentTask?: string;
  riskLevel: RiskLevel;
  metadata: Record<string, string>;
}

export interface WorkflowStep {
  id: string;
  action: string;
  provider: string;
  description: string;
  target?: Record<string, unknown>;
  verify?: Record<string, unknown>;
  safety?: Record<string, unknown>;
  result?: "success" | "waiting" | "failed";
}

export interface RPAWorkflow {
  schemaVersion: "1.0";
  id: string;
  name: string;
  provider: string;
  platform: RPAPlatform;
  inputs: Record<string, unknown>;
  steps: WorkflowStep[];
  successRate: number;
  lastRun: string;
}

export interface RPATraceStep {
  taskId: string;
  workflowId: string;
  provider: string;
  stepId: string;
  timestamp: string;
  actionName: string;
  pageState: string;
  duration: string;
  observation: Record<string, unknown>;
  action: Record<string, unknown>;
  result: Record<string, unknown>;
  safety: Record<string, unknown>;
}

export interface SafetyApproval {
  id: string;
  action: string;
  provider: string;
  riskLevel: RiskLevel;
  reason: string;
  status: ApprovalStatus;
  createdAt: string;
}

export interface GeneratedSkill {
  name: string;
  version: string;
  sourceWorkflowId: string;
  provider: string;
  format: SkillArtifactFormat;
  status: "draft" | "published";
  generatedAt: string;
}

export interface KpiMetric {
  title: string;
  value: string;
  subtitle: string;
  tone: "blue" | "green" | "orange" | "red";
  data: Array<{ value: number }>;
}

export interface RecordingFlowStep {
  id: string;
  label: string;
  description: string;
  status: FlowStatus;
}

export interface BridgeNode {
  id: string;
  label: string;
  detail: string;
  status: "healthy" | "warning" | "error";
  latencyMs: number;
  available: boolean;
}

export interface ProviderPreview {
  provider: string;
  platform: RPAPlatform;
  title: string;
  subtitle: string;
  metadata: Record<string, string>;
  treeLabel: string;
  treePreview: string;
}
