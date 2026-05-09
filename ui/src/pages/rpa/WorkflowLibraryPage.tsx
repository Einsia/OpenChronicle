import { Code2, Download, History, Play, Search } from "lucide-react";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { workflowAssets, workflowRuns } from "../../mock/rpaMultiPageMock";

const workflowJson = `{
  "name": "淘宝搜索商品流程",
  "version": "3",
  "schema_version": "1.1.3",
  "provider": "android_adb",
  "platform": "android",
  "description": "在淘宝 APP 中搜索商品并返回结果列表",
  "steps": [
    { "id": "Step 01", "action": "observe", "target": "home_screen", "timeout": 5000 },
    { "id": "Step 02", "action": "tap", "target": "search_input", "timeout": 3000 }
  ]
}`;

export function WorkflowLibraryPage() {
  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-4">
        {[["Total Workflows","34","All reusable workflow assets"],["Validated","22","64.7% of total"],["Drafts","8","Pending validation"],["Avg Success Rate","98.3%","Last 30 days"]].map(([title,value,note]) => (
          <Card key={title} className="p-4"><div className="text-sm text-slate-500">{title}</div><div className="mt-2 text-3xl font-semibold text-slate-950">{value}</div><div className="mt-1 text-xs text-slate-500">{note}</div></Card>
        ))}
      </section>
      <section className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_520px]">
        <Card>
          <CardHeader className="flex-wrap"><CardTitle>Workflow 资产表</CardTitle><Button variant="primary" size="sm">+ New Workflow</Button></CardHeader>
          <CardContent>
            <div className="mb-3 flex flex-wrap gap-2"><div className="flex h-10 min-w-[260px] flex-1 items-center gap-2 rounded-xl border border-slate-200 px-3 text-sm text-slate-400"><Search className="h-4 w-4" />搜索工作流名称、描述、标签...</div><Button size="sm">Provider: android_adb</Button><Button size="sm">Platform: All</Button><Button size="sm">Status: All</Button></div>
            <div className="overflow-x-auto rounded-xl border border-slate-100">
              <table className="min-w-[940px] w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="px-3 py-3">Workflow</th><th>Schema</th><th>Provider</th><th>Platform</th><th>Steps</th><th>成功率</th><th>最近运行</th><th>状态</th><th>操作</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {workflowAssets.map((item, index) => (
                    <tr key={item.name} className={index === 0 ? "bg-blue-50/50" : ""}>
                      <td className="px-3 py-3"><div className="font-semibold text-slate-900">{item.name}</div><div className="text-xs text-slate-500">可复用 workflow.json</div></td><td>{item.schema}</td><td>{item.provider}</td><td>{item.platform}</td><td>{item.steps}</td><td className="text-emerald-600">{item.success}</td><td>{item.lastRun}</td><td><Badge tone={item.status === "draft" ? "orange" : "green"}>{item.status}</Badge></td>
                      <td><div className="flex gap-1"><Button size="icon" variant="primary"><Play className="h-4 w-4" /></Button><Button size="icon"><Code2 className="h-4 w-4" /></Button><Button size="icon"><History className="h-4 w-4" /></Button></div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><CardTitle>淘宝搜索商品流程 <Badge tone="green">ready</Badge></CardTitle><div className="mt-1 text-xs text-slate-500">Provider android_adb · Schema 1.1.3 · 17 steps</div></div><Button size="icon"><Download className="h-4 w-4" /></Button></CardHeader>
          <CardContent><div className="mb-3 flex gap-2 text-xs"><Badge tone="blue">Workflow JSON</Badge><Badge>Manifest</Badge><Badge>Metadata</Badge></div><pre className="max-h-[420px] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-6 text-slate-100"><code>{workflowJson}</code></pre><div className="mt-3 flex items-center justify-between"><span className="text-sm text-emerald-600">Schema Valid · Last validated 19:31:20</span><Button variant="primary" size="sm">Validate</Button></div></CardContent>
        </Card>
      </section>
      <Card><CardHeader><CardTitle>运行记录 / 版本记录</CardTitle></CardHeader><CardContent className="grid grid-cols-1 gap-4 2xl:grid-cols-2"><div className="overflow-x-auto"><table className="min-w-[620px] w-full text-left text-sm"><thead className="text-xs text-slate-500"><tr><th>Run ID</th><th>By</th><th>Env</th><th>Steps</th><th>Result</th><th>Rate</th><th>Duration</th></tr></thead><tbody className="divide-y divide-slate-100">{workflowRuns.map((run) => <tr key={run.run}><td className="py-3 font-medium text-blue-600">{run.run}</td><td>{run.by}</td><td>{run.env}</td><td>{run.steps}</td><td><Badge tone={run.result === "partial" ? "orange" : "green"}>{run.result}</Badge></td><td>{run.rate}</td><td>{run.duration}</td></tr>)}</tbody></table></div><div className="space-y-3">{["v3 · Add screenshot after search results","v2 · Adjust search_input selector","v1 · Initial version"].map((item) => <div key={item} className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-sm">{item}</div>)}</div></CardContent></Card>
    </div>
  );
}
