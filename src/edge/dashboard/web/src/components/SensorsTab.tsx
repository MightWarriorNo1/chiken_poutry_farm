import { useQueries, useQuery } from "@tanstack/react-query";
import { Cloud, Droplet, Gauge, Thermometer, Wind } from "lucide-react";

import { api } from "../api";
import { fmtNumber, fmtUnit, relativeTime } from "../format";
import type { SensorView } from "../types";
import { Empty } from "./Empty";
import { Sparkline } from "./Sparkline";

export function SensorsTab() {
  const sensors = useQuery({
    queryKey: ["sensors"],
    queryFn: api.sensors,
    refetchInterval: 5_000,
  });

  const series = useQueries({
    queries: (sensors.data ?? []).map((s) => ({
      queryKey: ["sensorSeries", s.sensor_id],
      queryFn: () => api.sensorSeries(s.sensor_id),
      refetchInterval: 10_000,
    })),
  });

  if (!sensors.data) {
    return <div className="text-sm text-slate-500">Loading sensors…</div>;
  }
  if (sensors.data.length === 0) {
    return (
      <Empty
        icon={<Thermometer className="h-6 w-6" />}
        title="No sensor readings yet"
        description="Sensor readings haven't arrived. Check that simulator/mqtt is publishing."
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {sensors.data.map((s, i) => (
        <SensorCard
          key={s.sensor_id}
          sensor={s}
          points={series[i]?.data?.points ?? []}
        />
      ))}
    </div>
  );
}

interface CardProps {
  sensor: SensorView;
  points: { t: string; values: Record<string, number> }[];
}

function SensorCard({ sensor, points }: CardProps) {
  const Icon = iconFor(sensor.sensor_type);
  const tone =
    sensor.in_range === false
      ? "bad"
      : sensor.in_range === true
        ? "ok"
        : "muted";

  const accent = {
    ok: "text-emerald-300",
    bad: "text-rose-300",
    muted: "text-slate-300",
  }[tone];

  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <Icon className="h-4 w-4 text-sky-400" />
            {sensor.sensor_id}
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            {sensor.sensor_type}
            {sensor.shed_id ? ` · shed ${sensor.shed_id}` : ""}
            {sensor.zone_id ? ` · zone ${sensor.zone_id}` : ""}
          </div>
        </div>
        <RangeBadge sensor={sensor} />
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <div className={`text-3xl font-semibold tabular-nums ${accent}`}>
          {fmtNumber(sensor.value, 1)}
        </div>
        <div className="text-sm text-slate-500">{fmtUnit(sensor.unit)}</div>
      </div>

      <div className="mt-1 flex justify-between text-xs text-slate-500">
        <span>
          {sensor.threshold_min !== null && sensor.threshold_min !== undefined
            ? `min ${sensor.threshold_min}`
            : "no min"}
          {" · "}
          {sensor.threshold_max !== null && sensor.threshold_max !== undefined
            ? `max ${sensor.threshold_max}`
            : "no max"}
        </span>
        <span>{relativeTime(sensor.recorded_at)}</span>
      </div>

      <div className="mt-2">
        <Sparkline
          points={points}
          valueKey="value"
          color={
            tone === "bad" ? "#fb7185" : tone === "ok" ? "#34d399" : "#94a3b8"
          }
        />
      </div>
    </div>
  );
}

function RangeBadge({ sensor }: { sensor: SensorView }) {
  if (sensor.in_range === true) return <span className="badge badge-ok">in range</span>;
  if (sensor.in_range === false) return <span className="badge badge-bad">out of range</span>;
  return <span className="badge badge-muted">no threshold</span>;
}

function iconFor(t: string) {
  switch (t) {
    case "temperature":
      return Thermometer;
    case "humidity":
      return Droplet;
    case "ammonia":
    case "co2":
      return Cloud;
    case "water_flow":
    case "water_pressure":
      return Wind;
    default:
      return Gauge;
  }
}
