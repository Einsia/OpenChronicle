import { Camera, Code2, ListTree, MousePointer2, Play, Smartphone } from "lucide-react";

import { previewByProvider, providerSwitchers } from "../../mock/rpaHarnessMock";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import type { ProviderPreview } from "../../types/rpa";

interface DeviceLiveViewProps {
  activeProvider: string;
  onProviderChange: (provider: string) => void;
  onCaptureKeyframe: () => void;
  onReadTree: () => void;
  onRunStep: () => void;
}

export function DeviceLiveView({ activeProvider, onProviderChange, onCaptureKeyframe, onReadTree, onRunStep }: DeviceLiveViewProps) {
  const preview = previewByProvider[activeProvider] ?? previewByProvider.android_adb;

  return (
    <Card className="h-full">
      <CardHeader className="min-w-0">
        <CardTitle className="min-w-0 truncate">设备实时画面 / Device Live View</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0 space-y-4">
        <div className="grid grid-cols-2 gap-2 min-[1500px]:grid-cols-4">
          {providerSwitchers.map((item) => (
            <button
              key={item.provider}
              className={cn(
                "h-9 rounded-xl border text-xs font-medium transition",
                activeProvider === item.provider ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-600 hover:bg-slate-50"
              )}
              onClick={() => onProviderChange(item.provider)}
            >
              {item.label.split(" ")[0]}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-500 min-[1500px]:grid-cols-5">
          {Object.entries(preview.metadata).slice(0, 5).map(([label, value]) => (
            <div key={label}>
              <div>{label}</div>
              <div className="mt-1 truncate font-semibold text-slate-800">{value}</div>
            </div>
          ))}
        </div>
        <PreviewCanvas preview={preview} />
        <div className="grid grid-cols-2 gap-2 min-[1500px]:grid-cols-5">
          <Button size="sm" onClick={onCaptureKeyframe}><Camera className="h-4 w-4" />截图</Button>
          <Button size="sm" onClick={onReadTree}><ListTree className="h-4 w-4" />读取树</Button>
          <Button size="sm" className="text-blue-700"><MousePointer2 className="h-4 w-4" />点击模式</Button>
          <Button size="sm" onClick={onRunStep}><Play className="h-4 w-4" />单步执行</Button>
          <Button size="sm" variant="danger"><span className="h-2 w-2 rounded-full bg-red-500" />录制中 00:12:47</Button>
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-slate-600">其他会话（3）</div>
          <div className="grid grid-cols-1 gap-2 min-[1500px]:grid-cols-3">
            {["Windows 桌面", "Browser 会话", "API Worker"].map((name, index) => (
              <div key={name} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs">
                <div className="font-semibold text-slate-800">{name}</div>
                <div className="mt-1 flex items-center gap-1 text-emerald-600">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  在线
                </div>
                <div className="mt-2 h-8 rounded bg-gradient-to-r from-slate-200 to-blue-100" />
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function PreviewCanvas({ preview }: { preview: ProviderPreview }) {
  if (preview.platform === "android") {
    return (
      <div className="flex justify-center rounded-2xl bg-slate-50 p-4 subtle-grid">
        <div className="h-[310px] w-[190px] rounded-[28px] border-[7px] border-slate-900 bg-white shadow-xl">
          <div className="flex h-7 items-center justify-between border-b border-slate-100 px-3 text-[10px]">
            <span>10:24</span>
            <span>78%</span>
          </div>
          <div className="flex h-10 items-center justify-center gap-8 border-b border-slate-100 text-sm font-semibold">
            <span className="text-slate-500">关注</span>
            <span className="text-orange-600">推荐</span>
          </div>
          <div className="m-3 flex h-8 items-center rounded-full border border-orange-200 bg-orange-50 px-3 text-[11px] text-slate-500">连衣裙夏季</div>
          <div className="grid grid-cols-4 gap-3 px-4 py-2">
            {["天猫", "今日", "饿了么", "百亿", "超市", "充值", "领券", "分类"].map((item) => (
              <div key={item} className="text-center text-[10px] text-slate-600">
                <div className="mx-auto mb-1 h-8 w-8 rounded-xl bg-orange-500/90" />
                {item}
              </div>
            ))}
          </div>
          <div className="mx-3 mt-3 h-20 rounded-xl bg-gradient-to-r from-orange-100 to-red-100" />
        </div>
      </div>
    );
  }

  if (preview.platform === "windows") {
    return (
      <div className="rounded-2xl bg-slate-50 p-4 subtle-grid">
        <div className="overflow-hidden rounded-xl border border-slate-300 bg-white shadow-card">
          <div className="flex h-8 items-center gap-2 border-b border-slate-200 bg-slate-100 px-3 text-xs font-semibold">
            <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
            <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
            <span className="ml-2">Report Studio - 月度导出</span>
          </div>
          <div className="grid h-[300px] grid-cols-[120px_minmax(0,1fr)]">
            <div className="border-r border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">报表 / 任务 / 导出</div>
            <div className="p-4">
              <div className="mb-3 h-8 w-48 rounded bg-blue-50" />
              <div className="grid grid-cols-2 gap-2 min-[1500px]:grid-cols-4">
                {Array.from({ length: 16 }).map((_, index) => <div key={index} className="h-8 rounded border border-slate-200 bg-white" />)}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (preview.platform === "browser") {
    return (
      <div className="rounded-2xl bg-slate-50 p-4 subtle-grid">
        <div className="overflow-hidden rounded-xl border border-slate-300 bg-white shadow-card">
          <div className="flex h-9 items-center gap-2 border-b border-slate-200 px-3">
            <div className="h-5 flex-1 rounded-full bg-slate-100 px-3 text-[11px] leading-5 text-slate-500">https://console.openchronicle.dev/login</div>
          </div>
          <div className="flex h-[299px] items-center justify-center bg-gradient-to-b from-blue-50 to-white">
            <div className="w-72 rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
              <div className="mb-4 h-7 w-36 rounded bg-blue-100" />
              <div className="mb-3 h-9 rounded border border-slate-200" />
              <div className="mb-3 h-9 rounded border border-slate-200" />
              <div className="h-9 rounded bg-blue-600" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-slate-950 p-4 font-mono text-xs text-slate-100">
      <div className="mb-3 flex items-center gap-2 text-emerald-300"><Code2 className="h-4 w-4" />POST /api/orders/search</div>
      <div className="grid h-[320px] grid-cols-1 gap-3 min-[1500px]:grid-cols-2">
        <pre className="overflow-auto rounded-xl bg-slate-900 p-3">{`{
  "keyword": "连衣裙夏季",
  "page": 1,
  "safety_check": true
}`}</pre>
        <pre className="overflow-auto rounded-xl bg-slate-900 p-3">{`HTTP/1.1 200 OK
schema_version: 1.0

{
  "items": 42,
  "write_trace": true,
  "fallback_area": "response.items"
}`}</pre>
      </div>
    </div>
  );
}
