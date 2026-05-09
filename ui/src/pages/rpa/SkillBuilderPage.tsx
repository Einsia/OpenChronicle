import { CheckCircle2, GitBranch, Play, Save, UploadCloud } from "lucide-react";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { skillGroups, skillSources } from "../../mock/rpaMultiPageMock";

const yaml = `name: taobao_search_product
version: 1.0.0
description: 在淘宝搜索商品并浏览结果
provider: android_adb
mode: mock
capabilities:
  - tap
  - input_text
  - scroll
  - wait
input_parameters:
  search_input:
    type: string
    description: 搜索关键词
    required: true
  category:
    type: string
    required: false`;

export function SkillBuilderPage() {
  return (
    <div className="space-y-4">
      <Card className="p-4"><div className="grid grid-cols-1 gap-3 md:grid-cols-4">{[["1 Trace","选择执行轨迹"],["2 Workflow","抽取并压缩流程"],["3 Skill","生成可复用技能"],["4 Reuse","发布与复用"]].map(([title,desc],index)=><div key={title} className="flex items-center gap-3"><div className={`flex h-10 w-10 items-center justify-center rounded-full ${index===0?"bg-blue-600 text-white":"bg-slate-100 text-slate-500"}`}>{index+1}</div><div><div className="font-semibold text-slate-900">{title}</div><div className="text-xs text-slate-500">{desc}</div></div></div>)}</div></Card>
      <section className="grid grid-cols-1 gap-4 2xl:grid-cols-[300px_minmax(0,1fr)_460px]">
        <Card><CardHeader><CardTitle>来源选择</CardTitle></CardHeader><CardContent className="space-y-3"><div className="grid grid-cols-2 gap-2"><Button variant="primary">Trace (128)</Button><Button>Workflow (34)</Button></div>{skillSources.map((item,index)=><div key={item.id} className={`rounded-xl border p-3 ${index===0?"border-blue-200 bg-blue-50":"border-slate-100"}`}><div className="flex items-center justify-between"><div className="font-semibold text-slate-900">{item.title}</div><Badge tone={item.status==="partial"?"orange":"green"}>{item.status}</Badge></div><div className="mt-1 text-xs text-slate-500">{item.id}</div><div className="text-xs text-slate-500">{item.provider}</div></div>)}</CardContent></Card>
        <Card><CardHeader><CardTitle>参数抽取与步骤压缩</CardTitle><Badge tone="blue">128 steps detected</Badge></CardHeader><CardContent className="space-y-5"><section><div className="mb-3 flex items-center gap-2 font-semibold"><CheckCircle2 className="h-4 w-4 text-blue-600" />Input Parameter Extraction</div><div className="grid grid-cols-1 gap-2 md:grid-cols-2">{["search_input · string · 手机充电器","sort_type · string · 综合","category · string · 全部","brand_filter · string · 全部","page_index · integer · 1","max_price · number · 未设置"].map((param)=><div key={param} className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-sm">{param}</div>)}</div></section><section><div className="mb-3 flex items-center gap-2 font-semibold"><GitBranch className="h-4 w-4 text-blue-600" />Step Grouping & Normalization</div><div className="space-y-2">{skillGroups.map((group)=><div key={group.id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3 text-sm"><Badge tone="blue">{group.id}</Badge><span className="min-w-0 flex-1 truncate">{group.name}</span><span className="text-slate-500">{group.from} → {group.to}</span><span className="font-semibold text-emerald-600">-{group.saved}</span></div>)}</div></section><section><div className="mb-2 font-semibold">Compression Controls</div><div className="h-2 rounded-full bg-slate-100"><div className="h-2 w-[78%] rounded-full bg-blue-600" /></div><div className="mt-2 text-sm text-slate-500">当前压缩率 78% · Aggressive</div></section></CardContent></Card>
        <Card><CardHeader><CardTitle>Skill YAML / JSON 预览</CardTitle><div className="flex gap-1"><Badge tone="blue">YAML</Badge><Badge>JSON</Badge></div></CardHeader><CardContent><pre className="max-h-[430px] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-6 text-slate-100"><code>{yaml}</code></pre><div className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><div className="text-slate-500">技能名称</div><b>taobao_search_product</b></div><div><div className="text-slate-500">版本</div><b>1.0.0 draft</b></div><div><div className="text-slate-500">兼容设备</div><b>12 / 18 在线</b></div><div><div className="text-slate-500">成功率</div><b>98.2%</b></div></div></CardContent></Card>
      </section>
      <section className="grid grid-cols-1 gap-4 2xl:grid-cols-[1fr_1fr_420px]"><Card><CardHeader><CardTitle>测试运行结果</CardTitle><Badge tone="green">成功</Badge></CardHeader><CardContent><div className="grid grid-cols-4 gap-2 text-center"><div><b>00:24.31</b><div className="text-xs text-slate-500">执行时长</div></div><div><b>10/10</b><div className="text-xs text-slate-500">步骤执行</div></div><div><b>100%</b><div className="text-xs text-slate-500">成功率</div></div><div><b>0</b><div className="text-xs text-slate-500">错误数</div></div></div></CardContent></Card><Card><CardHeader><CardTitle>版本时间线</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><div className="rounded-xl bg-blue-50 p-3">v1.0.0 draft · 初始版本生成</div><div className="rounded-xl bg-slate-50 p-3">v0.3.0 · 调整分组策略</div><div className="rounded-xl bg-slate-50 p-3">v0.2.0 · 从 Trace 生成草稿</div></CardContent></Card><Card><CardHeader><CardTitle>Actions</CardTitle></CardHeader><CardContent className="grid gap-3"><Button variant="primary"><Play className="h-4 w-4" />Test Run</Button><Button><Save className="h-4 w-4" />Save Draft</Button><Button variant="success"><UploadCloud className="h-4 w-4" />Publish Skill</Button></CardContent></Card></section>
    </div>
  );
}
