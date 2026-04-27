import type { ReactNode } from "react";

import { Save, Settings2 } from "lucide-react";

import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { settingsSections } from "../../mock/rpaMultiPageMock";

function Segmented({ options, active }: { options: string[]; active: string }) {
  return (
    <div className="grid rounded-xl border border-slate-200 bg-slate-50 p-1" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
      {options.map((option) => <button key={option} className={`h-9 rounded-lg text-sm font-medium ${option === active ? "bg-white text-blue-700 shadow-sm" : "text-slate-500"}`}>{option}</button>)}
    </div>
  );
}

function Toggle({ on = true }: { on?: boolean }) {
  return <span className={`inline-flex h-6 w-11 items-center rounded-full p-0.5 ${on ? "bg-emerald-500" : "bg-slate-300"}`}><i className={`h-5 w-5 rounded-full bg-white transition ${on ? "translate-x-5" : "translate-x-0"}`} /></span>;
}

export function SettingsPage() {
  return (
    <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[280px_minmax(0,1fr)]">
      <Card><CardContent className="space-y-2 p-4">{settingsSections.map((section,index)=><button key={section} className={`flex h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium ${index===0?"bg-blue-50 text-blue-700":"text-slate-600 hover:bg-slate-50"}`}><Settings2 className="h-4 w-4" />{section}</button>)}</CardContent></Card>
      <Card><CardHeader><div><CardTitle>Provider Configuration</CardTitle><div className="mt-1 text-xs text-slate-500">Configure default behaviors and global policies for providers and execution.</div></div></CardHeader><CardContent className="divide-y divide-slate-100 p-0"><SettingRow title="Default Provider" desc="New workflows will use this provider by default."><select className="h-10 w-full rounded-xl border border-slate-200 px-3 text-sm"><option>android_adb (Android ADB)</option><option>windows_uia</option></select></SettingRow><SettingRow title="Default Screenshot Strategy" desc="Controls how screenshots are captured during execution."><Segmented options={["none","keyframe","full"]} active="keyframe" /></SettingRow><SettingRow title="OCR Engine" desc="OCR is used for text recognition in screenshots."><Segmented options={["disabled","paddleocr","other"]} active="disabled" /></SettingRow><SettingRow title="Default Safety Level" desc="Default risk level applied to new actions and workflows."><Segmented options={["low","medium","high"]} active="medium" /></SettingRow><SettingRow title="Auto-approve Low Risk Actions" desc="Automatically approve actions classified as low risk."><Toggle /></SettingRow><SettingRow title="Require Approval for L2+ Risk" desc="Require manual approval for Medium and High risk actions."><Toggle /></SettingRow><SettingRow title="Trace Retention" desc="How long to retain execution traces and artifacts."><Segmented options={["7天","30天","永久"]} active="30天" /></SettingRow><SettingRow title="Workflow Schema Version" desc="The default schema version used for new workflows."><select className="h-10 w-full rounded-xl border border-slate-200 px-3 text-sm"><option>1.0</option></select></SettingRow><SettingRow title="Enable Provider Health Check" desc="Periodically check provider connectivity and status."><Toggle /></SettingRow><SettingRow title="Mock Mode (Global)" desc="Force all providers into mock mode. No real device actions will be executed."><Toggle on={false} /></SettingRow><div className="flex flex-wrap items-center justify-between gap-3 p-4"><Button variant="primary"><Save className="h-4 w-4" />Save Changes</Button><div className="flex gap-2"><Button>Reset to Defaults</Button><Button>Export Config</Button></div></div></CardContent></Card>
    </div>
  );
}

function SettingRow({ title, desc, children }: { title: string; desc: string; children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-3 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,480px)]"><div><div className="font-semibold text-slate-900">{title}</div><div className="mt-1 text-sm text-slate-500">{desc}</div></div><div>{children}</div></div>;
}
