import { FileJson, Wand2 } from "lucide-react";
import { useMemo, useState } from "react";

import { stableRecordingRules } from "../../mock/rpaHarnessMock";
import type { GeneratedSkill, SkillArtifactFormat } from "../../types/rpa";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface WorkflowSkillBuilderProps {
  onGenerateSkill: (format: SkillArtifactFormat) => Promise<GeneratedSkill>;
}

export function WorkflowSkillBuilder({ onGenerateSkill }: WorkflowSkillBuilderProps) {
  const [format, setFormat] = useState<SkillArtifactFormat>("workflow.json");
  const [lastSkill, setLastSkill] = useState<GeneratedSkill | null>(null);
  const preview = useMemo(() => {
    if (format === "workflow.json") {
      return `{
  "schema_version": "1.0",
  "name": "taobao_search_product",
  "provider": "android_adb",
  "principles": ["OCR first", "fallback_area", "keyframe", "safety_check", "write_trace"]
}`;
    }
    return `name: taobao_search_product
version: v1.2.1
provider: android_adb
schema_version: "1.0"
artifacts:
  - workflow.json
  - trace.jsonl
rules:
  unknown_action: reject
  safety_check: required`;
  }, [format]);

  async function handleGenerate() {
    setLastSkill(await onGenerateSkill(format));
  }

  return (
    <Card>
      <CardHeader className="min-w-0 flex-wrap">
        <CardTitle className="min-w-0 truncate">Workflow / Skill Builder</CardTitle>
        <div className="flex shrink-0 items-center gap-2 text-xs">
          <span>输出</span>
          <button className={format === "workflow.json" ? "text-blue-700" : "text-slate-500"} onClick={() => setFormat("workflow.json")}>workflow.json</button>
          <button className={format === "skill.yaml" ? "text-blue-700" : "text-slate-500"} onClick={() => setFormat("skill.yaml")}>skill.yaml</button>
        </div>
      </CardHeader>
      <CardContent className="grid min-w-0 grid-cols-1 gap-4 min-[1500px]:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <div className="min-w-0 space-y-3">
          <label className="block text-xs font-medium text-slate-600">
            技能名称
            <input className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm" defaultValue="taobao_search_product" />
          </label>
          <label className="block text-xs font-medium text-slate-600">
            技能描述
            <textarea className="mt-1 h-16 w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm" defaultValue="在淘宝 App 中搜索商品的通用技能" />
          </label>
          <div className="min-w-0 overflow-hidden rounded-xl border border-slate-200">
            {["keyword", "category", "page"].map((param, index) => (
              <div key={param} className="grid grid-cols-[minmax(0,1fr)_64px_56px_minmax(0,1fr)] border-b border-slate-100 px-3 py-2 text-xs last:border-0">
                <span className="truncate font-medium">{param}</span>
                <span>string</span>
                <span>{index !== 1 ? "必填" : "可选"}</span>
                <span className="truncate text-slate-500">{index === 0 ? "搜索关键词" : index === 1 ? "商品分类" : "页码"}</span>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button className="min-w-[150px] flex-1"><FileJson className="h-4 w-4" />预览 {format}</Button>
            <Button className="min-w-[150px] flex-1" variant="primary" onClick={handleGenerate}><Wand2 className="h-4 w-4" />生成 Skill</Button>
          </div>
          {lastSkill ? <div className="rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-700">已生成 {lastSkill.name} {lastSkill.version} ({lastSkill.format})</div> : null}
        </div>
        <div className="min-w-0">
          <pre className="h-full min-h-[230px] min-w-0 overflow-auto rounded-xl bg-slate-950 p-4 font-mono text-xs leading-5 text-slate-100">{preview}</pre>
          <div className="mt-2 flex flex-wrap gap-1">
            {stableRecordingRules.slice(0, 4).map((rule) => <span key={rule} className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">{rule}</span>)}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
