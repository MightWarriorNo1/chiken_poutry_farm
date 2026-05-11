import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { LiveEventView } from "./types";

interface LiveFeed {
  connected: boolean;
  lastEventAt: Date | null;
}

/**
 * Subscribe to the SSE stream and invalidate React Query caches as events
 * arrive. We don't patch caches surgically per event type — invalidating a
 * small list is cheap and the alternative (per-event reducers) is a lot of
 * code for little win at PoC volumes.
 *
 * The hook returns `connected` + `lastEventAt` so the header can show a
 * "live · X seconds ago" indicator.
 */
export function useLiveFeed(): LiveFeed {
  const qc = useQueryClient();
  const [state, setState] = useState<LiveFeed>({
    connected: false,
    lastEventAt: null,
  });

  useEffect(() => {
    const es = new EventSource("/events");

    es.addEventListener("hello", () => {
      setState((s) => ({ ...s, connected: true }));
    });

    const invalidations: Record<string, string[]> = {
      bird_detection: ["cameras"],
      weight_estimate: ["cameras"],
      huddling_score: ["cameras"],
      sensor_reading: ["sensors"],
      alert: ["alerts", "status"],
      device_heartbeat: ["status"],
      manual_weight_sample: ["manualWeights"],
    };

    const onMessage = (ev: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(ev.data) as LiveEventView;
        setState({ connected: true, lastEventAt: new Date(parsed.at) });
      } catch {
        /* ignore */
      }
      const keys = invalidations[ev.type] ?? [];
      for (const key of keys) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    };

    Object.keys(invalidations).forEach((t) =>
      es.addEventListener(t, onMessage as EventListener),
    );

    es.onerror = () => {
      // EventSource auto-reconnects; flip the flag while it's down.
      setState((s) => ({ ...s, connected: false }));
    };

    return () => es.close();
  }, [qc]);

  return state;
}
