import { Code2, Globe, Monitor, Smartphone } from "lucide-react";

import { providerSwitchers } from "../../mock/rpaHarnessMock";
import { cn } from "../../lib/utils";

const icons = [Smartphone, Monitor, Globe, Code2];

interface ProviderSwitcherProps {
  activeProvider: string;
  onProviderChange: (provider: string) => void;
}

export function ProviderSwitcher({ activeProvider, onProviderChange }: ProviderSwitcherProps) {
  return (
    <div className="flex h-10 w-[184px] shrink-0 rounded-xl border border-slate-200 bg-white p-1 2xl:w-[536px]">
      {providerSwitchers.map((item, index) => {
        const Icon = icons[index];
        const active = activeProvider === item.provider;
        return (
          <button
            key={item.provider}
            className={cn(
              "flex min-w-0 flex-1 items-center justify-center gap-2 rounded-lg px-2 text-xs font-medium transition 2xl:px-3",
              active ? "bg-blue-50 text-blue-700 ring-1 ring-blue-200" : "text-slate-600 hover:bg-slate-50"
            )}
            onClick={() => onProviderChange(item.provider)}
            title={item.label}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="hidden truncate 2xl:inline">{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}
