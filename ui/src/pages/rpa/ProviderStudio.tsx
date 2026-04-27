import { useMemo, useState } from "react";

import { KpiCard } from "../../components/dashboard/KpiCard";
import { BridgeTopology } from "../../components/rpa/BridgeTopology";
import { ProviderDetail } from "../../components/rpa/ProviderDetail";
import { ProviderRegistry } from "../../components/rpa/ProviderRegistry";
import { RecordingEditStudio } from "../../components/rpa/RecordingEditStudio";
import { SkillOutputVersion } from "../../components/rpa/SkillOutputVersion";
import { WorkflowLibrary } from "../../components/rpa/WorkflowLibrary";
import { rpaApi } from "../../lib/rpaApi";
import {
  bridgeTopologyNodes,
  generatedSkills as initialSkills,
  providerKpis,
  providers,
  workflows,
  workflowSteps
} from "../../mock/rpaHarnessMock";
import type { GeneratedSkill, WorkflowStep } from "../../types/rpa";

interface ProviderStudioProps {
  activeProvider: string;
  onProviderChange: (provider: string) => void;
}

export function ProviderStudio({ activeProvider, onProviderChange }: ProviderStudioProps) {
  const [selectedProvider, setSelectedProvider] = useState(activeProvider);
  const [connectionMessage, setConnectionMessage] = useState("Codex Ready");
  const [steps, setSteps] = useState(workflowSteps);
  const [skills, setSkills] = useState<GeneratedSkill[]>(initialSkills);
  const provider = useMemo(() => providers.find((item) => item.name === selectedProvider) ?? providers[0], [selectedProvider]);

  async function testConnection(providerName: string) {
    const result = await rpaApi.testProvider(providerName);
    setConnectionMessage(`${result.provider}: ${result.message}`);
  }

  async function saveWorkflow(nextSteps: WorkflowStep[]) {
    await rpaApi.saveWorkflow(workflows[1], nextSteps);
    setSteps(nextSteps);
    setSkills((current) => [
      {
        name: "taobao_search_product",
        version: `v1.2.${current.length}`,
        sourceWorkflowId: "wf-taobao-search",
        provider: selectedProvider,
        format: "workflow.json",
        status: "draft",
        generatedAt: new Date().toLocaleTimeString("zh-CN", { hour12: false })
      },
      ...current
    ]);
  }

  function selectProvider(providerName: string) {
    setSelectedProvider(providerName);
    if (["android_adb", "windows_uia", "playwright_browser", "api_worker"].includes(providerName)) {
      onProviderChange(providerName);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <div className="flex max-w-full flex-wrap gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 shadow-card">
          <span>React + TypeScript</span>
          <span>Tailwind</span>
          <span>shadcn/ui</span>
          <span className="text-emerald-600">● {connectionMessage}</span>
        </div>
      </div>
      <div className="kpi-grid grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {providerKpis.map((metric, index) => <KpiCard key={metric.title} metric={metric} index={index} />)}
      </div>
      <div className="rpa-page-grid xl:grid-cols-2 min-[1720px]:grid-cols-[minmax(0,1.15fr)_minmax(0,0.9fr)_minmax(0,1.05fr)]">
        <ProviderRegistry providers={providers} activeProvider={selectedProvider} onSelect={selectProvider} onTest={(name) => void testConnection(name)} />
        <BridgeTopology nodes={bridgeTopologyNodes} />
        <ProviderDetail provider={provider} />
      </div>
      <div className="rpa-page-grid xl:grid-cols-2 min-[1720px]:grid-cols-[minmax(0,1.1fr)_minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <WorkflowLibrary workflows={workflows} />
        <RecordingEditStudio workflow={workflows[1]} initialSteps={steps} onSave={saveWorkflow} />
        <SkillOutputVersion skills={skills} />
      </div>
    </div>
  );
}
