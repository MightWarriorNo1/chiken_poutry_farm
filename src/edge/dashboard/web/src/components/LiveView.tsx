import { Camera, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api";

interface Props {
  cameraId: string;
  onClose: () => void;
}

/**
 * Modal showing a single camera's live (annotated) MJPEG feed.
 *
 * The browser renders multipart/x-mixed-replace natively when set as the
 * `src` of an `<img>` tag — no JS decoding needed. We do hold a cache-busting
 * key so re-opening the same camera triggers a fresh connection rather than
 * resurrecting the closed one from the browser's image cache.
 */
export function LiveView({ cameraId, onClose }: Props) {
  const [streamKey] = useState(() => Date.now());
  const [errored, setErrored] = useState(false);

  // Esc closes the modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const streamSrc = `${api.cameraStreamUrl(cameraId)}?t=${streamKey}`;

  return (
    <div
      role="dialog"
      aria-label={`Live feed for ${cameraId}`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <div
        className="relative flex max-h-full max-w-5xl flex-col overflow-hidden rounded-lg border border-ink-700 bg-ink-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <Camera className="h-4 w-4 text-sky-400" />
            Live · {cameraId}
            <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-300">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
              MJPEG
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-ink-800 hover:text-slate-100"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="bg-black">
          {errored ? (
            <div className="flex h-64 items-center justify-center px-8 text-center text-sm text-slate-400">
              <div>
                <div className="font-semibold text-slate-200">
                  No live feed yet
                </div>
                <div className="mt-1">
                  The camera pipeline hasn't produced any annotated frames. This
                  usually means the frame source can't open, or no frames have
                  been processed yet. Check{" "}
                  <code className="text-slate-300">prosper-edge</code> logs.
                </div>
              </div>
            </div>
          ) : (
            <img
              src={streamSrc}
              alt={`Live feed from ${cameraId}`}
              className="block max-h-[80vh] w-auto"
              onError={() => setErrored(true)}
            />
          )}
        </div>
        <div className="border-t border-ink-700 px-4 py-2 text-[11px] text-slate-500">
          Frames are annotated with bird centroids + a metrics HUD. Read-only.
          Press <kbd className="rounded bg-ink-800 px-1">Esc</kbd> to close.
        </div>
      </div>
    </div>
  );
}
