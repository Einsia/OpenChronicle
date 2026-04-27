import type { RPAWorkflow } from "../../types/rpa";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface WorkflowLibraryProps {
  workflows: RPAWorkflow[];
}

export function WorkflowLibrary({ workflows }: WorkflowLibraryProps) {
  return (
    <Card>
      <CardHeader className="min-w-0 flex-wrap">
        <CardTitle className="min-w-0 truncate">Workflow 库</CardTitle>
        <div className="flex min-w-0 flex-wrap gap-2">
          <input className="h-8 min-w-[150px] flex-1 rounded-lg border border-slate-200 px-3 text-xs" placeholder="搜索 workflow..." />
          <select className="h-8 rounded-lg border border-slate-200 px-2 text-xs"><option>全部 Provider</option></select>
        </div>
      </CardHeader>
      <CardContent className="min-w-0 pt-0">
        <div className="overflow-x-auto">
          <table className="min-w-[860px] w-full text-left text-xs">
            <thead className="text-slate-500">
              <tr className="border-b border-slate-100">
                {["名称", "schema_version", "provider", "platform", "steps", "success rate", "last run", "操作"].map((head) => (
                  <th key={head} className="py-2 font-medium">{head}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {workflows.map((workflow) => (
                <tr key={workflow.id} className="border-b border-slate-50 last:border-0">
                  <td className="py-2 font-medium text-blue-700">{workflow.name}</td>
                  <td><Badge tone="slate">{workflow.schemaVersion}</Badge></td>
                  <td>{workflow.provider}</td>
                  <td>{workflow.platform}</td>
                  <td>{workflow.steps.length}</td>
                  <td className="text-emerald-600">{workflow.successRate}%</td>
                  <td>{workflow.lastRun}</td>
                  <td className="flex gap-1 py-1">
                    <Button size="sm">验证</Button>
                    <Button size="sm">运行</Button>
                    <Button size="sm">编辑 JSON</Button>
                    <Button size="sm">生成 Skill</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
