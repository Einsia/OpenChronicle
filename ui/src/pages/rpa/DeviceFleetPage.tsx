import { MoreVertical, Radio, RefreshCw, Search, Smartphone } from "lucide-react";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { anomalyLogs, fleetDevices, fleetSummary, heartbeatStream } from "../../mock/rpaMultiPageMock";

type BadgeTone = "blue" | "green" | "orange" | "red" | "slate";

function riskTone(risk: string): BadgeTone {
  if (risk === "L3") return "red";
  if (risk === "L2") return "orange";
  return "green";
}

export function DeviceFleetPage() {
  const selected = fleetDevices[0];

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-4">
        {fleetSummary.map((item, index) => (
          <Card key={item.title} className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-slate-500">{item.title}</div>
                <div className="mt-2 text-3xl font-semibold text-slate-950">{item.value}</div>
                <div className="mt-1 text-xs text-slate-500">{item.note}</div>
              </div>
              <div className="rounded-2xl bg-blue-50 p-3 text-blue-700 ring-1 ring-blue-100">
                {index === 0 ? <Radio className="h-6 w-6" /> : <Smartphone className="h-6 w-6" />}
              </div>
            </div>
          </Card>
        ))}
      </section>

      <section className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader className="flex-wrap">
            <div className="flex min-w-0 flex-1 flex-wrap gap-2">
              {[["Android Phones", "24"], ["Windows Desktops", "11"], ["Browser Sessions", "14"], ["API Workers", "6"], ["All Devices", "55"]].map(([tab, count], index) => (
                <button key={tab} className={`rounded-xl px-3 py-2 text-sm font-semibold ${index === 0 ? "bg-blue-50 text-blue-700 ring-1 ring-blue-100" : "text-slate-500 hover:bg-slate-50"}`}>{tab} <span className="ml-1 text-xs">{count}</span></button>
              ))}
            </div>
            <Button size="sm"><RefreshCw className="h-4 w-4" />刷新</Button>
          </CardHeader>
          <CardContent>
            <div className="mb-3 flex flex-wrap gap-2">
              <div className="flex h-10 min-w-[240px] flex-1 items-center gap-2 rounded-xl border border-slate-200 px-3 text-sm text-slate-400"><Search className="h-4 w-4" />搜索设备 ID / 目标 / 标签</div>
              <Button size="sm">Filters</Button><Button size="sm">Status: All</Button>
            </div>
            <div className="overflow-x-auto rounded-xl border border-slate-100">
              <table className="min-w-[980px] w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="px-3 py-3">设备ID</th><th>Provider</th><th>平台</th><th>状态</th><th>当前目标</th><th>当前任务</th><th>风险</th><th>最近心跳</th><th>操作</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {fleetDevices.map((device) => (
                    <tr key={device.id} className={device.id === selected.id ? "bg-blue-50/50" : ""}>
                      <td className="px-3 py-3 font-semibold text-blue-600">{device.id}</td><td>{device.provider}</td><td>{device.platform}</td>
                      <td><span className={`inline-flex items-center gap-1 ${device.status === "offline" ? "text-slate-400" : device.status === "busy" ? "text-amber-600" : "text-emerald-600"}`}><i className="h-2 w-2 rounded-full bg-current" />{device.status}</span></td>
                      <td>{device.target}</td><td>{device.task}</td><td><Badge tone={riskTone(device.risk)}>{device.risk}</Badge></td><td className="text-emerald-600">{device.heartbeat}</td><td><MoreVertical className="h-4 w-4 text-slate-400" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>选中设备详情</CardTitle><Badge tone="green">online</Badge></CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="flex gap-3"><div className="flex h-24 w-16 items-center justify-center rounded-xl bg-slate-900 text-white">Phone</div><div><div className="font-semibold text-slate-950">{selected.id}</div><div className="mt-2 text-slate-500">Android 12 · SDK 31</div><div className="text-slate-500">1080 × 2400 · 420dpi</div><div className="text-slate-500">Provider: {selected.provider}</div></div></div>
            <div className="grid grid-cols-2 gap-2 text-xs">{["production", "ecommerce", "cn-region", "mock-ready"].map((tag) => <span key={tag} className="rounded-full bg-slate-100 px-2 py-1 text-center text-slate-600">{tag}</span>)}</div>
            <div className="rounded-xl border border-slate-100 p-3"><div className="font-semibold">Active Session</div><div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-500"><span>Workflow</span><b className="text-slate-700">淘宝搜索商品流程</b><span>Uptime</span><b className="text-slate-700">00:14:32</b><span>Current Step</span><b className="text-slate-700">Step 02 · tap search</b></div></div>
            <div className="rounded-xl border border-slate-100 p-3"><div className="font-semibold">Last Screenshot</div><div className="mt-3 flex h-24 items-center justify-center rounded-xl bg-gradient-to-br from-orange-50 to-blue-50 text-xs text-slate-500">Taobao keyframe preview</div></div>
            <div className="grid grid-cols-2 gap-2"><Button variant="primary">Connect</Button><Button variant="danger">Disconnect</Button></div>
            <Button className="w-full">打开实时调试</Button>
          </CardContent>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
        <Card><CardHeader><CardTitle>最近 Heartbeat</CardTitle></CardHeader><CardContent className="space-y-2 text-xs text-slate-600">{heartbeatStream.map((line) => <div key={line} className="rounded-xl bg-slate-50 p-3">{line}</div>)}</CardContent></Card>
        <Card><CardHeader><CardTitle>异常日志</CardTitle></CardHeader><CardContent className="space-y-2 text-xs">{anomalyLogs.map((item) => <div key={item.text} className="flex items-center justify-between rounded-xl bg-slate-50 p-3"><span><Badge tone={riskTone(item.level)}>{item.level}</Badge> {item.text}</span><span className="text-slate-400">{item.time}</span></div>)}</CardContent></Card>
      </section>
    </div>
  );
}
