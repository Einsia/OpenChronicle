import { Activity, ClipboardCheck, ShieldCheck, Smartphone, Target, Users } from "lucide-react";
import { Line, LineChart, ResponsiveContainer } from "recharts";

import { Card } from "../ui/card";
import type { KpiMetric } from "../../types/rpa";
import { cn } from "../../lib/utils";

const icons = [Users, Smartphone, ShieldCheck, Target, ClipboardCheck, Activity];

const toneClass = {
  blue: "bg-blue-50 text-blue-600",
  green: "bg-emerald-50 text-emerald-600",
  orange: "bg-amber-50 text-amber-600",
  red: "bg-red-50 text-red-600"
};

const strokeClass = {
  blue: "#2563EB",
  green: "#16A34A",
  orange: "#F59E0B",
  red: "#EF4444"
};

interface KpiCardProps {
  metric: KpiMetric;
  index: number;
}

export function KpiCard({ metric, index }: KpiCardProps) {
  const Icon = icons[index % icons.length];

  return (
    <Card className="min-h-[98px] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex gap-3">
          <div className={cn("flex h-10 w-10 items-center justify-center rounded-xl", toneClass[metric.tone])}>
            <Icon className="h-5 w-5" />
          </div>
          <div>
            <div className="text-xs text-slate-500">{metric.title}</div>
            <div className="mt-1 text-2xl font-semibold tracking-normal text-slate-950">{metric.value}</div>
            <div className={cn("mt-1 text-xs", metric.tone === "orange" ? "text-amber-600" : "text-emerald-600")}>{metric.subtitle}</div>
          </div>
        </div>
        <div className="h-16 w-28">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={metric.data}>
              <Line type="monotone" dataKey="value" stroke={strokeClass[metric.tone]} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Card>
  );
}
