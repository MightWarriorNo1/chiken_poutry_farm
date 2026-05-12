import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "./api";
import { AlertsTab } from "./components/AlertsTab";
import { CamerasTab } from "./components/CamerasTab";
import { DemoTab } from "./components/DemoTab";
import { OverviewTab } from "./components/OverviewTab";
import { SensorsTab } from "./components/SensorsTab";
import { SourcesTab } from "./components/SourcesTab";
import { StatusBar } from "./components/StatusBar";
import { Tabs } from "./components/Tabs";

type TabId =
  | "overview"
  | "cameras"
  | "sources"
  | "sensors"
  | "alerts"
  | "demo";

export function App() {
  const [tab, setTab] = useState<TabId>("overview");

  // Used to populate the tab counts in one place; React Query dedupes the
  // fetch with the tabs' own queries.
  const status = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 10_000,
  });

  // Lightweight poll so the "Demo" tab can show a running indicator without
  // clicking into it. Cheap — 5s cadence on a single ~250 B endpoint.
  const demoStatus = useQuery({
    queryKey: ["demo", "status"],
    queryFn: api.demoStatus,
    refetchInterval: 5_000,
  });
  const adhocStatus = useQuery({
    queryKey: ["adhoc", "status"],
    queryFn: api.adhocStatus,
    refetchInterval: 5_000,
  });

  return (
    <div className="flex min-h-full flex-col">
      <StatusBar />
      <Tabs
        tabs={[
          { id: "overview", label: "Overview" },
          {
            id: "cameras",
            label: "Cameras",
            count: status.data?.camera_count,
          },
          {
            id: "sources",
            label: adhocStatus.data?.running ? "Sources ●" : "Sources",
          },
          {
            id: "sensors",
            label: "Sensors",
            count: status.data?.sensor_count,
          },
          {
            id: "alerts",
            label: "Alerts",
            count: status.data?.open_alert_count,
          },
          {
            id: "demo",
            label: demoStatus.data?.running ? "Demo ●" : "Demo",
          },
        ]}
        active={tab}
        onChange={setTab}
      />
      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">
        {tab === "overview" && <OverviewTab />}
        {tab === "cameras" && <CamerasTab />}
        {tab === "sources" && <SourcesTab />}
        {tab === "sensors" && <SensorsTab />}
        {tab === "alerts" && <AlertsTab />}
        {tab === "demo" && <DemoTab />}
      </main>
      <footer className="border-t border-ink-800 bg-ink-950 px-6 py-3 text-center text-xs text-slate-600">
        Prosper PoultryVision AI · on-device dashboard · read-only
      </footer>
    </div>
  );
}
