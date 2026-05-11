import { useQuery } from "@tanstack/react-query";
import { CircleAlert, ShieldCheck } from "lucide-react";

import { api } from "../api";
import { relativeTime, severityClass } from "../format";
import { Empty } from "./Empty";

export function AlertsTab() {
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.alerts(200),
    refetchInterval: 5_000,
  });

  if (!alerts.data) {
    return <div className="text-sm text-slate-500">Loading alerts…</div>;
  }
  if (alerts.data.length === 0) {
    return (
      <Empty
        icon={<ShieldCheck className="h-6 w-6 text-emerald-400" />}
        title="All clear"
        description="No alerts currently in the local rolling window."
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
      <table className="w-full text-left text-sm">
        <thead className="bg-ink-800 text-xs uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-4 py-2 font-medium">Severity</th>
            <th className="px-4 py-2 font-medium">Type</th>
            <th className="px-4 py-2 font-medium">Message</th>
            <th className="px-4 py-2 font-medium">Source</th>
            <th className="px-4 py-2 font-medium">Raised</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {alerts.data.map((a) => (
            <tr key={a.event_id} className="hover:bg-ink-800/40">
              <td className="px-4 py-2 align-top">
                <span className={`badge ${severityClass(a.severity)}`}>
                  {a.severity}
                </span>
              </td>
              <td className="whitespace-nowrap px-4 py-2 align-top font-mono text-xs text-slate-300">
                {a.alert_type}
              </td>
              <td className="px-4 py-2 align-top text-slate-200">
                <div>{a.message}</div>
                <div className="mt-0.5 text-xs text-slate-500">
                  {[
                    a.camera_id && `cam ${a.camera_id}`,
                    a.sensor_id && `sensor ${a.sensor_id}`,
                    a.shed_id && `shed ${a.shed_id}`,
                    a.zone_id && `zone ${a.zone_id}`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </td>
              <td className="whitespace-nowrap px-4 py-2 align-top text-xs text-slate-400">
                <SourceBadge source={a.source} />
              </td>
              <td className="whitespace-nowrap px-4 py-2 align-top text-xs text-slate-400 tabular-nums">
                <div>{relativeTime(a.raised_at)}</div>
                <div className="text-slate-600">
                  {new Date(a.raised_at).toLocaleTimeString()}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center gap-2 border-t border-ink-800 px-4 py-2 text-xs text-slate-500">
        <CircleAlert className="h-3.5 w-3.5" />
        Showing {alerts.data.length} most-recent alerts (rolling local window).
      </div>
    </div>
  );
}

function SourceBadge({ source }: { source: string }) {
  const tone = {
    ai: "badge-info",
    sensor: "badge-warn",
    camera: "badge-info",
    device: "badge-muted",
  }[source] ?? "badge-muted";
  return <span className={`badge ${tone}`}>{source}</span>;
}
