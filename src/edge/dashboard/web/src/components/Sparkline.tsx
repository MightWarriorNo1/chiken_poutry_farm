import { useMemo } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";

import type { TimePoint } from "../types";

interface Props {
  points: TimePoint[];
  valueKey: string;
  color?: string;
  height?: number;
  tooltipFormatter?: (n: number) => string;
}

/**
 * Minimal sparkline: no axes, no grid, no legend. The chart is decorative
 * context for the big stat above it — the user reads the stat, the spark
 * shows them whether it's stable, climbing, or panicking.
 */
export function Sparkline({
  points,
  valueKey,
  color = "#60a5fa",
  height = 48,
  tooltipFormatter,
}: Props) {
  const data = useMemo(
    () =>
      points.map((p) => ({
        t: new Date(p.t).getTime(),
        v: p.values[valueKey] ?? 0,
      })),
    [points, valueKey],
  );

  if (data.length === 0) {
    return (
      <div
        className="flex items-center text-xs text-slate-600"
        style={{ height }}
      >
        no samples yet
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Tooltip
          contentStyle={{
            background: "#11161c",
            border: "1px solid #252e39",
            borderRadius: 6,
            fontSize: 12,
            padding: "4px 8px",
          }}
          labelFormatter={(t) => new Date(t as number).toLocaleTimeString()}
          formatter={(v) => [
            tooltipFormatter ? tooltipFormatter(Number(v)) : v,
            "",
          ]}
        />
        <Line
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
