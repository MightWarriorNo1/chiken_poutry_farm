// Lightweight formatters. All accept `null | undefined` so callers don't
// need to guard at every call site.

export function fmtNumber(
  v: number | null | undefined,
  digits = 1,
): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Math.round(v).toLocaleString();
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

const RTF = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSec = Math.round((then - Date.now()) / 1000);
  const absSec = Math.abs(diffSec);
  if (absSec < 60) return RTF.format(diffSec, "second");
  if (absSec < 3600) return RTF.format(Math.round(diffSec / 60), "minute");
  if (absSec < 86400) return RTF.format(Math.round(diffSec / 3600), "hour");
  return RTF.format(Math.round(diffSec / 86400), "day");
}

export function fmtUnit(unit: string | null | undefined): string {
  switch (unit) {
    case "celsius":
      return "°C";
    case "percent":
      return "%";
    case "ppm":
      return "ppm";
    case "lpm":
      return "L/min";
    case "kpa":
      return "kPa";
    default:
      return unit ?? "";
  }
}

export function severityClass(severity: string): string {
  switch (severity) {
    case "critical":
      return "badge-bad";
    case "high":
      return "badge-bad";
    case "medium":
      return "badge-warn";
    case "low":
      return "badge-info";
    default:
      return "badge-muted";
  }
}
