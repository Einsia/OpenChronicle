import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Clock, Radio, ShieldCheck, Smartphone } from "lucide-react";

import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { executionTrend, overviewKpis, pendingActions, providerHealthRows, recentFailures } from "../../mock/rpaMultiPageMock";

const toneClass: Record<string, string> = {
  blue: "bg-blue-50 text-blue-700 ring-blue-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  orange: "bg-amber-50 text-amber-700 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200"
};

const stateDot: Record<string, string> = {
  healthy: "bg-emerald-500",
  degraded: "bg-amber-500",
  unhealthy: "bg-red-500",
  offline: "bg-slate-300"
};

export function OverviewDashboard() {
  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        {overviewKpis.map((item, index) => {
          const Icon = [Radio, Smartphone, Activity, Clock, CheckCircle2, ShieldCheck][index] ?? Activity;
          return (
            <Card key={item.title} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-slate-500">{item.title}</div>
                  <div className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">{item.value}</div>
                  <div className="mt-2 text-xs text-emerald-600">{item.note}</div>
                </div>
                <div className={`rounded-2xl p-3 ring-1 ${toneClass[item.tone]}`}>
                  <Icon className="h-5 w-5" />
                </div>
              </div>
            </Card>
          );
        })}
      </section>

      <section className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Provider 健康矩阵</CardTitle>
            <div className="flex gap-3 text-xs text-slate-500">
              <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-emerald-500" />Healthy</span>
              <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-amber-500" />Degraded</span>
              <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-red-500" />Unhealthy</span>
            </div>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <div className="min-w-[560px] rounded-xl border border-slate-100">
              <div className="grid grid-cols-[1.2fr_repeat(5,0.7fr)] border-b border-slate-100 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-500">
                <span>Provider</span><span>-24h</span><span>-18h</span><span>-12h</span><span>-6h</span><span>Now</span>
              </div>
              {providerHealthRows.map((row) => (
                <div key={row.provider} className="grid grid-cols-[1.2fr_repeat(5,0.7fr)] items-center border-b border-slate-100 px-3 py-3 text-sm last:border-b-0">
                  <span className="truncate font-medium text-slate-700">{row.provider}</span>
                  {row.states.map((state, index) => <span key={`${row.provider}-${index}`} className={`h-3 w-3 rounded-full ${stateDot[state]}`} />)}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>近 7 日执行趋势</CardTitle>
            <Badge tone="slate">Daily</Badge>
          </CardHeader>
          <CardContent>
            <div className="h-[300px] rounded-2xl border border-slate-100 bg-gradient-to-b from-slate-50 to-white p-4">
              <div className="flex h-full items-end gap-3">
                {executionTrend.map((item) => {
                  const successHeight = Math.max(28, item.success / 12);
                  const failureHeight = Math.max(8, item.failure / 2.5);
                  return (
                    <div key={item.day} className="flex min-w-0 flex-1 flex-col items-center gap-2">
                      <div className="flex h-[220px] w-full items-end justify-center gap-1">
                        <div className="w-1/2 max-w-[34px] rounded-t-xl bg-emerald-500/80" style={{ height: successHeight }} title={`${item.success}`} />
                        <div className="w-1/3 max-w-[22px] rounded-t-xl bg-red-400/80" style={{ height: failureHeight }} title={`${item.failure}`} />
                      </div>
                      <div className="text-xs text-slate-500">{item.day}</div>
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-sm">
              <div className="rounded-xl bg-emerald-50 p-3 text-emerald-700">Success 13,157</div>
              <div className="rounded-xl bg-red-50 p-3 text-red-700">Failure 511</div>
              <div className="rounded-xl bg-blue-50 p-3 text-blue-700">Success Rate 96.2%</div>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader><CardTitle>最近失败任务</CardTitle><button className="text-xs font-semibold text-blue-600">查看全部</button></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="min-w-[680px] w-full text-left text-sm">
              <thead className="text-xs text-slate-500"><tr><th className="py-2">Task ID</th><th>Provider</th><th>失败原因</th><th>风险</th><th>时间</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {recentFailures.map((row) => <tr key={row.id}><td className="py-3 font-medium text-blue-600">{row.id}</td><td>{row.provider}</td><td>{row.reason}</td><td><Badge tone={row.risk === "L3" ? "red" : row.risk === "L2" ? "orange" : "green"}>{row.risk}</Badge></td><td>{row.time}</td></tr>)}
              </tbody>
            </table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>待处理事项</CardTitle><AlertTriangle className="h-4 w-4 text-amber-500" /></CardHeader>
          <CardContent className="space-y-3">
            {pendingActions.map((item) => <div key={item.title} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3"><div className={`rounded-xl p-2 ring-1 ${toneClass[item.tone]}`}><AlertTriangle className="h-4 w-4" /></div><div className="min-w-0 flex-1"><div className="font-medium text-slate-900">{item.title}</div><div className="text-xs text-slate-500">{item.desc}</div></div><div className="text-2xl font-semibold text-slate-950">{item.count}</div><ArrowRight className="h-4 w-4 text-slate-400" /></div>)}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
