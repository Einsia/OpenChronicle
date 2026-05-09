import { ShieldAlert, ShieldCheck } from "lucide-react";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { approvals } from "../../mock/rpaMultiPageMock";

type BadgeTone = "blue" | "green" | "orange" | "red" | "slate";

function riskTone(risk: string): BadgeTone {
  return risk === "L3" ? "red" : risk === "L2" ? "orange" : "green";
}

export function SafetyApprovalPage() {
  const current = approvals[0];

  return (
    <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[330px_minmax(0,1fr)_360px]">
      <Card><CardHeader><CardTitle>审批队列</CardTitle><Badge tone="red">8</Badge></CardHeader><CardContent className="space-y-3"><div className="flex flex-wrap gap-2"><Badge tone="blue">全部</Badge><Badge>L1</Badge><Badge tone="orange">L2</Badge><Badge tone="red">L3</Badge></div>{approvals.map((item,index)=><div key={item.action} className={`rounded-xl border p-3 ${index===0?"border-blue-200 bg-blue-50":"border-slate-100"}`}><div className="flex items-center justify-between"><b>{item.action}</b><Badge tone={riskTone(item.risk)}>{item.risk}</Badge></div><div className="mt-1 text-xs text-slate-500">{item.device}</div><div className="text-xs text-slate-500">{item.resource}</div><div className="mt-1 text-xs text-slate-400">{item.time}</div></div>)}</CardContent></Card>
      <Card><CardHeader><div><CardTitle>动作详情 <Badge tone="red">L3 高风险</Badge></CardTitle><div className="mt-1 text-xs text-slate-500">Request ID: REQ-20240518-000123</div></div></CardHeader><CardContent className="space-y-4"><div className="grid grid-cols-2 gap-3 text-sm xl:grid-cols-5"><div><span className="text-slate-500">Provider</span><b className="block">android_adb</b></div><div><span className="text-slate-500">Device</span><b className="block">{current.device}</b></div><div><span className="text-slate-500">Workflow</span><b className="block">E-commerce Bot</b></div><div><span className="text-slate-500">Requested By</span><b className="block">robot@provider</b></div><div><span className="text-slate-500">Time</span><b className="block">19:31:20</b></div></div><div className="grid grid-cols-1 gap-4 xl:grid-cols-2"><section className="rounded-xl border border-slate-100 p-3 text-sm"><b>触发原因</b><p className="mt-2 text-slate-500">Workflow step “Install App” requires installing external APK on device.</p><div className="mt-3"><b>策略命中</b><ul className="mt-2 space-y-1 text-red-600"><li>Policy: Block 3rd-party APK Install</li><li>Policy: Unknown App Source</li></ul></div></section><section><div className="mb-2 font-semibold">Action Payload JSON</div><pre className="rounded-2xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">{`{
  "provider":"android_adb",
  "action":"install_apk",
  "parameters":{
    "apk_path":"/sdcard/Download/com.example.apk",
    "grant_permissions":true
  }
}`}</pre></section></div><div><div className="mb-2 font-semibold">执行前截图</div><div className="flex h-56 items-center justify-center rounded-2xl bg-slate-900 text-slate-300">Android home screenshot</div></div><div className="flex flex-wrap gap-2"><Button variant="success"><ShieldCheck className="h-4 w-4" />批准</Button><Button variant="danger">拒绝</Button><Button>加入白名单</Button><Button>加入黑名单</Button></div></CardContent></Card>
      <div className="space-y-4"><Card><CardHeader><CardTitle>风险解释</CardTitle></CardHeader><CardContent><div className="mx-auto flex h-28 w-28 items-center justify-center rounded-full border-[12px] border-red-200 text-center text-2xl font-bold text-red-600">92</div><div className="mt-4 grid gap-2 text-sm"><div className="flex justify-between"><span>Impact</span><b className="text-red-600">High</b></div><div className="flex justify-between"><span>Likelihood</span><b className="text-red-600">High</b></div><div className="flex justify-between"><span>Detectability</span><b className="text-amber-600">Low</b></div></div></CardContent></Card><Card><CardHeader><CardTitle>策略命中</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">{["Block 3rd-party APK Install","Unknown App Source","Payment Amount Limit"].map((item)=><div key={item} className="rounded-xl bg-red-50 p-3 text-red-700"><ShieldAlert className="mr-2 inline h-4 w-4" />{item}</div>)}</CardContent></Card></div>
      <Card className="2xl:col-span-3"><CardHeader><CardTitle>审批历史 / Policy Hit Timeline</CardTitle></CardHeader><CardContent className="grid grid-cols-1 gap-4 xl:grid-cols-2"><div className="space-y-2">{["Read Clipboard · Approved · Business justified","Read Contacts · Rejected · Privacy risk","Payment · Approved · Verified workflow"].map((row)=><div key={row} className="rounded-xl bg-slate-50 p-3 text-sm">{row}</div>)}</div><div className="space-y-2">{["19:31 Policy: Block 3rd-party APK Install","19:28 Policy: Payment Amount Limit","19:21 Policy: Contact Access Restriction"].map((row)=><div key={row} className="rounded-xl bg-slate-50 p-3 text-sm">{row}</div>)}</div></CardContent></Card>
    </div>
  );
}
