import {
  bridgeInspectorNodes,
  bridgeTopologyNodes,
  devices,
  generatedSkills,
  providers,
  recordingFlow,
  safetyApprovals,
  traceSteps,
  workflows,
  workflowSteps
} from "../mock/rpaHarnessMock";
import type { ApprovalStatus, GeneratedSkill, RPAWorkflow, SafetyApproval, WorkflowStep } from "../types/rpa";

const delay = (ms = 180) => new Promise((resolve) => window.setTimeout(resolve, ms));

export const rpaApi = {
  async getProviders() {
    await delay();
    return providers;
  },
  async getProvider(name: string) {
    await delay();
    return providers.find((provider) => provider.name === name) ?? providers[0];
  },
  async testProvider(name: string) {
    await delay(240);
    return { provider: name, ok: true, message: "Mock connection healthy" };
  },
  async getDevices() {
    await delay();
    return devices;
  },
  async getRun() {
    await delay();
    return { flow: recordingFlow, traceSteps, bridgeInspectorNodes };
  },
  async getBridgeTopology() {
    await delay();
    return bridgeTopologyNodes;
  },
  async getWorkflows() {
    await delay();
    return workflows;
  },
  async validateWorkflow(workflow: RPAWorkflow) {
    await delay();
    return {
      ok: workflow.schemaVersion === "1.0",
      message: workflow.schemaVersion === "1.0" ? "schema_version 1.0 valid" : "schema_version must be 1.0"
    };
  },
  async saveWorkflow(workflow: RPAWorkflow, steps: WorkflowStep[]) {
    await delay(240);
    return { ...workflow, steps };
  },
  async updateApproval(approval: SafetyApproval, status: ApprovalStatus) {
    await delay(160);
    return { ...approval, status };
  },
  async generateSkill(format: GeneratedSkill["format"] = "skill.yaml") {
    await delay(280);
    return {
      name: "taobao_search_product",
      version: "v1.2.1",
      sourceWorkflowId: "wf-taobao-search",
      provider: "android_adb",
      format,
      status: "draft",
      generatedAt: new Date().toLocaleTimeString("zh-CN", { hour12: false })
    } satisfies GeneratedSkill;
  },
  getDefaultWorkflowSteps() {
    return workflowSteps;
  },
  getGeneratedSkills() {
    return generatedSkills;
  }
};
