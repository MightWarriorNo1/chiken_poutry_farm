import { useQuery } from "@tanstack/react-query";
import { Activity, CircleAlert, Cpu, HardDrive, MemoryStick, Radio } from "lucide-react";

import { api } from "../api";
import { fmtInt, fmtNumber, relativeTime } from "../format";
import { useLiveFeed } from "../useLiveFeed";

export function StatusBar() {
  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 10_000,
  });
  const live = useLiveFeed();

  const statusBadge = (() => {
    switch (status?.status) {
      case "healthy":
        return "badge-ok";
      case "degraded":
        return "badge-warn";
      case "error":
        return "badge-bad";
      default:
        return "badge-muted";
    }
  })();

  return (
    <header className="border-b border-ink-800 bg-ink-900/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-3">
        <div className="flex items-center gap-3">
          <Activity className="h-5 w-5 text-sky-400" />
          <div>
            <div className="text-sm font-semibold text-slate-100">
              Prosper EdgeBox
            </div>
            <div className="text-xs text-slate-500 tabular-nums">
              {status?.device_id ?? "—"} · v{status?.software_version ?? "0.0.0"}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className={`badge ${statusBadge}`}>
            {status?.status ?? "unknown"}
          </span>

          <StatChip
            icon={<Cpu className="h-3.5 w-3.5" />}
            label="CPU"
            value={fmtNumber(status?.cpu_pct, 0)}
            unit="%"
          />
          <StatChip
            icon={<MemoryStick className="h-3.5 w-3.5" />}
            label="Mem"
            value={fmtNumber(status?.memory_pct, 0)}
            unit="%"
          />
          <StatChip
            icon={<HardDrive className="h-3.5 w-3.5" />}
            label="Disk"
            value={fmtNumber(status?.storage_pct, 0)}
            unit="%"
          />
          <StatChip
            icon={<CircleAlert className="h-3.5 w-3.5" />}
            label="Outbox"
            value={fmtInt(status?.outbox_pending)}
          />

          <div
            className={`flex items-center gap-1.5 ${
              live.connected ? "text-emerald-300" : "text-slate-500"
            }`}
            title={
              live.lastEventAt
                ? `last event ${relativeTime(live.lastEventAt.toISOString())}`
                : "no events yet"
            }
          >
            <Radio
              className={`h-3.5 w-3.5 ${live.connected ? "animate-pulse" : ""}`}
            />
            <span>{live.connected ? "live" : "offline"}</span>
          </div>
        </div>
      </div>
    </header>
  );
}

interface ChipProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  unit?: string;
}

function StatChip({ icon, label, value, unit }: ChipProps) {
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-ink-700 bg-ink-800 px-2 py-1 text-slate-300">
      <span className="text-slate-500">{icon}</span>
      <span className="text-slate-500">{label}</span>
      <span className="font-medium tabular-nums text-slate-100">
        {value}
        {unit ?? ""}
      </span>
    </div>
  );
}
