import { Download, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "../../lib/utils";
import type { RPATraceStep } from "../../types/rpa";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface TimelineLogProps {
  rows: RPATraceStep[];
  selectedStepId: string;
  onSelect: (step: RPATraceStep) => void;
}

export function TimelineLog({ rows, selectedStepId, onSelect }: TimelineLogProps) {
  const [provider, setProvider] = useState("all");
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () =>
      rows.filter((row) => {
        const providerMatch = provider === "all" || row.provider === provider;
        const queryMatch = `${row.stepId} ${row.actionName} ${row.pageState} ${row.provider}`.toLowerCase().includes(query.toLowerCase());
        return providerMatch && queryMatch;
      }),
    [provider, query, rows]
  );

  return (
    <Card>
      <CardHeader className="min-w-0 flex-wrap">
        <CardTitle className="min-w-0 truncate">时间线与日志（32 步）</CardTitle>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <select className="h-8 rounded-lg border border-slate-200 px-2 text-xs" value={provider} onChange={(event) => setProvider(event.target.value)}>
            <option value="all">全部 Provider</option>
            <option value="android_adb">android_adb</option>
            <option value="windows_uia">windows_uia</option>
            <option value="api_worker">api_worker</option>
          </select>
          <div className="flex h-8 min-w-[160px] flex-1 items-center gap-2 rounded-lg border border-slate-200 px-2 text-xs text-slate-400">
            <Search className="h-3.5 w-3.5 shrink-0" />
            <input className="min-w-0 flex-1 outline-none" placeholder="筛选动作、元素、结果..." value={query} onChange={(event) => setQuery(event.target.value)} />
          </div>
          <Button size="sm"><Download className="h-3.5 w-3.5" />导出</Button>
        </div>
      </CardHeader>
      <CardContent className="min-w-0 pt-0">
        <div className="overflow-x-auto">
          <table className="min-w-[760px] w-full text-left text-xs">
            <thead className="text-slate-500">
              <tr className="border-b border-slate-100">
                {["步骤", "时间", "Provider", "动作", "页面状态 / 元素", "结果", "耗时"].map((head) => (
                  <th key={head} className="py-2 font-medium">{head}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const active = selectedStepId === row.stepId;
                const result = String(row.result.status);
                return (
                  <tr
                    key={`${row.stepId}-${row.provider}`}
                    className={cn("cursor-pointer border-b border-slate-50 last:border-0", active ? "bg-blue-50 text-blue-700" : "hover:bg-slate-50")}
                    onClick={() => onSelect(row)}
                  >
                    <td className="py-2 font-semibold">▶ {row.stepId}</td>
                    <td>{row.timestamp}</td>
                    <td>{row.provider}</td>
                    <td>{row.actionName}</td>
                    <td>{row.pageState}</td>
                    <td><Badge tone={result === "success" ? "green" : result === "failed" ? "red" : "orange"}>{result}</Badge></td>
                    <td>{row.duration}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex justify-center gap-1 text-xs">
          {[1, 2, 3, 4].map((page) => (
            <button key={page} className={cn("h-7 w-7 rounded-lg border", page === 1 ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-500")}>{page}</button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
