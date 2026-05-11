import { useQuery } from "@tanstack/react-query";
import { Bird, CircleAlert, Gauge, Scale, Thermometer } from "lucide-react";

import { api } from "../api";
import { fmtInt, fmtNumber, fmtPct, fmtUnit, severityClass } from "../format";
import { Empty } from "./Empty";

export function OverviewTab() {
  const cameras = useQuery({
    queryKey: ["cameras"],
    queryFn: api.cameras,
    refetchInterval: 5_000,
  });
  const sensors = useQuery({
    queryKey: ["sensors"],
    queryFn: api.sensors,
    refetchInterval: 5_000,
  });
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.alerts(10),
    refetchInterval: 10_000,
  });

  // Aggregate flock-wide metrics across cameras (single shed in POC, but
  // averaging is robust to multi-cam farms later).
  const camList = cameras.data ?? [];
  const sensorList = sensors.data ?? [];
  const totalBirds = camList.reduce((s, c) => s + (c.bird_count ?? 0), 0);
  const avgHuddle = avg(camList.map((c) => c.huddling_score));
  const avgWeight = avg(camList.map((c) => c.estimated_avg_weight_g));
  const temp = sensorList.find((s) => s.sensor_type === "temperature");
  const humidity = sensorList.find((s) => s.sensor_type === "humidity");

  return (
    <div className="space-y-6">
      <section>
        <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-slate-500">
          Flock at a glance
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            icon={<Bird className="h-4 w-4" />}
            label="Birds visible"
            value={fmtInt(totalBirds)}
            sub={`across ${camList.length} camera${camList.length === 1 ? "" : "s"}`}
          />
          <StatCard
            icon={<Scale className="h-4 w-4" />}
            label="Avg estimated weight"
            value={`${fmtNumber(avgWeight, 0)} g`}
            sub="AI estimate"
          />
          <StatCard
            icon={<Gauge className="h-4 w-4" />}
            label="Huddling score"
            value={fmtPct(avgHuddle, 0)}
            sub={(avgHuddle ?? 0) > 0.5 ? "elevated" : "normal"}
            tone={(avgHuddle ?? 0) > 0.7 ? "bad" : (avgHuddle ?? 0) > 0.5 ? "warn" : "ok"}
          />
          <StatCard
            icon={<Thermometer className="h-4 w-4" />}
            label="Shed temperature"
            value={
              temp?.value !== null && temp?.value !== undefined
                ? `${fmtNumber(temp.value, 1)} ${fmtUnit(temp.unit)}`
                : "—"
            }
            sub={
              humidity?.value !== null && humidity?.value !== undefined
                ? `humidity ${fmtNumber(humidity.value, 0)}%`
                : "no humidity sensor"
            }
            tone={temp?.in_range === false ? "warn" : "ok"}
          />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-slate-500">
          Recent alerts
        </h2>
        {alerts.data && alerts.data.length > 0 ? (
          <div className="card divide-y divide-ink-700 p-0">
            {alerts.data.slice(0, 5).map((a) => (
              <div
                key={a.event_id}
                className="flex items-center justify-between gap-4 p-3 first:rounded-t-xl last:rounded-b-xl"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`badge ${severityClass(a.severity)}`}>
                      {a.severity}
                    </span>
                    <span className="text-sm font-medium text-slate-200">
                      {a.alert_type}
                    </span>
                  </div>
                  <div className="mt-1 truncate text-xs text-slate-400">
                    {a.message}
                  </div>
                </div>
                <div className="shrink-0 text-xs text-slate-500 tabular-nums">
                  {new Date(a.raised_at).toLocaleTimeString()}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            icon={<CircleAlert className="h-6 w-6" />}
            title="No alerts"
            description="The edge hasn't raised any conditions worth flagging yet."
          />
        )}
      </section>
    </div>
  );
}

interface StatProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  tone?: "ok" | "warn" | "bad";
}

function StatCard({ icon, label, value, sub, tone = "ok" }: StatProps) {
  const accent = {
    ok: "text-sky-400",
    warn: "text-amber-400",
    bad: "text-rose-400",
  }[tone];
  return (
    <div className="card">
      <div className="card-title flex items-center gap-2">
        <span className={accent}>{icon}</span>
        {label}
      </div>
      <div className="stat mt-2">{value}</div>
      {sub && <div className="stat-sub mt-1">{sub}</div>}
    </div>
  );
}

function avg(values: (number | null | undefined)[]): number | null {
  const xs = values.filter(
    (v): v is number => v !== null && v !== undefined && !Number.isNaN(v),
  );
  if (xs.length === 0) return null;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}
