import { useMemo, useState } from "react";

import { formatJson } from "../../lib/utils";
import type { GeneratedSkill, SkillOutputFormat } from "../../types/rpa";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

interface SkillOutputVersionProps {
  skills: GeneratedSkill[];
}

export function SkillOutputVersion({ skills }: SkillOutputVersionProps) {
  const [format, setFormat] = useState<SkillOutputFormat>("YAML");
  const preview = useMemo(() => {
    if (format === "JSON") {
      return formatJson({
        name: "taobao_search_product",
        schema_version: "1.0",
        provider: "android_adb",
        source: "workflow.json",
        safety_check: true,
        unknown_action: "reject"
      });
    }
    return `name: taobao_search_product
description: 使用 Taobao 搜索商品并写入 trace
schema_version: "1.0"
provider: android_adb
latest_version: v1.2.0
safety:
  safety_check: true
  unknown_action: reject`;
  }, [format]);

  return (
    <Card className="h-full">
      <CardHeader className="min-w-0">
        <CardTitle className="min-w-0 truncate">Skill 输出与版本</CardTitle>
        <div className="shrink-0 rounded-xl border border-slate-200 p-1">
          {(["YAML", "JSON"] as const).map((item) => (
            <button
              key={item}
              className={`h-7 rounded-lg px-3 text-xs font-semibold ${format === item ? "bg-blue-600 text-white" : "text-slate-500"}`}
              onClick={() => setFormat(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="grid min-w-0 grid-cols-1 gap-4 min-[1500px]:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div className="min-w-0 space-y-3">
          {[
            ["Skill 名称", "taobao_search_product"],
            ["描述", "使用 Taobao 搜索商品并生成结果"],
            ["Schema Version", "1.0"],
            ["Provider", "android_adb"],
            ["最新版本", "v1.2.0"]
          ].map(([label, value]) => (
            <label key={label} className="grid grid-cols-[92px_minmax(0,1fr)] items-center gap-2 text-xs text-slate-500">
              {label}
              <input className="h-8 min-w-0 rounded-lg border border-slate-200 px-2 text-slate-800" defaultValue={value} />
            </label>
          ))}
          <pre className="max-h-36 min-w-0 overflow-auto rounded-xl bg-slate-950 p-3 font-mono text-[11px] leading-5 text-slate-100">{preview}</pre>
        </div>
        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between gap-2 text-xs font-semibold text-slate-700">
            版本历史
            <button className="shrink-0 text-blue-600">查看全部</button>
          </div>
          <div className="space-y-2">
            {["v1.2.0", "v1.1.0", "v1.0.0", "v0.9.0"].map((version, index) => (
              <div key={version} className="grid grid-cols-[64px_70px_minmax(0,1fr)] rounded-xl border border-slate-200 px-3 py-2 text-xs">
                <span className="font-semibold">{version}</span>
                <Badge tone={index === 3 ? "slate" : "green"}>{index === 3 ? "草稿" : "已发布"}</Badge>
                <span className="truncate text-right text-slate-500">2024-05-{16 - index}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 text-xs font-semibold text-slate-700">最近生成的 Skill</div>
          <div className="mt-2 grid grid-cols-1 gap-2 min-[1500px]:grid-cols-3">
            {skills.map((skill) => (
              <div key={`${skill.name}-${skill.version}`} className="min-w-0 rounded-xl border border-slate-200 p-3 text-xs">
                <div className="truncate font-mono font-semibold text-slate-900">{skill.name}</div>
                <div className="mt-1 text-slate-500">{skill.version}</div>
                <div className="mt-2 truncate text-blue-600">{skill.provider}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-1 gap-2 min-[1500px]:grid-cols-2">
            <Button variant="primary">发布 Skill</Button>
            <Button>导出 JSON</Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
