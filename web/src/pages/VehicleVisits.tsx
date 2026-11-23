import { baseUrl } from "@/api/baseUrl";
import { useIsAdmin } from "@/hooks/use-is-admin";
import axios from "axios";
import { useAllowedCameras } from "@/hooks/use-allowed-cameras";
import { createRecordingReviewUrl } from "@/utils/recordingReviewUrl";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import useSWR from "swr";

type VisitEvent = {
  event_id: string;
  start_time: number;
  end_time: number | null;
  match_reason: string;
  thumbnail_url: string;
};
type VehicleVisit = {
  visit_id: string;
  camera: string;
  start_time: number;
  last_seen: number;
  event_count: number;
  events: VisitEvent[];
  grouping_mode: string;
};

function formattedDate(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString();
}

function visitClip(visit: VehicleVisit, index: number): string {
  const event = visit.events[index];
  return `${baseUrl}api/events/${encodeURIComponent(event.event_id)}/clip.mp4`;
}

export default function VehicleVisits() {
  const { t } = useTranslation(["common"]);
  const cameras = useAllowedCameras();
  const isAdmin = useIsAdmin();
  const [backfillBusy, setBackfillBusy] = useState(false);
  const [backfillMessage, setBackfillMessage] = useState<string | null>(null);
  const [chosenCamera, setChosenCamera] = useState<string>("obrotowa");
  const camera = cameras.includes(chosenCamera) ? chosenCamera : cameras[0];
  const [playback, setPlayback] = useState<{ visitId: string; index: number } | null>(null);
  const query = useMemo(
    () => camera ? ["vehicle_visits", { camera, hours: 48, limit: 150 }] : null,
    [camera],
  );
  const { data, error, isLoading, mutate } = useSWR<VehicleVisit[]>(query, {
    refreshInterval: 30000,
  });

  const backfill = async () => {
    if (!camera || !window.confirm(t("vehicleVisits.backfillConfirm"))) {
      return;
    }
    setBackfillBusy(true);
    try {
      const response = await axios.post<{
        processed: number;
        failed: number;
        more_possible: boolean;
      }>("vehicle_visits/backfill", null, { params: { camera, hours: 48, limit: 250 } });
      setBackfillMessage(
        t("vehicleVisits.backfillResult", { processed: response.data.processed })
        + " " + t("vehicleVisits.backfillFailures", { failed: response.data.failed })
        + (response.data.more_possible ? " " + t("vehicleVisits.backfillMore") : ""),
      );
      await mutate();
    } catch {
      setBackfillMessage(t("vehicleVisits.backfillError"));
    } finally {
      setBackfillBusy(false);
    }
  };

  return (
    <main className="scrollbar-container h-full overflow-y-auto bg-background p-4 md:p-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{t("vehicleVisits.title")}</h1>
          <p className="text-sm text-secondary-foreground">
            {t("vehicleVisits.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm" htmlFor="visit-camera">
            {t("vehicleVisits.camera")}
          </label>
          <select
            className="rounded-md border bg-background_alt p-2 text-sm"
            id="visit-camera"
            value={camera ?? ""}
            onChange={(e) => { setChosenCamera(e.target.value); setPlayback(null); }}
          >
            {cameras.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <button className="rounded-md border px-3 py-2 text-sm" onClick={() => void mutate()}>
            {t("vehicleVisits.refresh")}
          </button>
          {isAdmin && <button disabled={backfillBusy || !camera} className="rounded-md border px-3 py-2 text-sm disabled:opacity-50" onClick={() => void backfill()}>
            {backfillBusy ? t("vehicleVisits.backfillBusy") : t("vehicleVisits.backfill")}
          </button>}
        </div>
      </div>
      {backfillMessage && <p className="mb-3 text-sm">{backfillMessage}</p>}
      {isLoading && <p>{t("vehicleVisits.loading")}</p>}
      {error && <p role="alert">{t("vehicleVisits.error")}</p>}
      {!isLoading && !error && !data?.length && <p>{t("vehicleVisits.empty")}</p>}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {data?.map((visit) => {
          const playing = playback?.visitId === visit.visit_id;
          const selected = playing ? (playback?.index ?? 0) : 0;
          const event = visit.events[selected];
          const preview = visit.events[0];
          return (
            <article key={visit.visit_id} className="overflow-hidden rounded-xl border bg-background_alt">
              <div className="flex gap-3 p-3">
                <img
                  loading="lazy"
                  className="h-28 w-36 flex-none rounded object-cover"
                  src={`${baseUrl}api/events/${encodeURIComponent(preview.event_id)}/thumbnail.webp`}
                  alt={t("vehicleVisits.photo")}
                />
                <div className="min-w-0 flex-1">
                  <h2 className="font-semibold">{t("vehicleVisits.visit")} {formattedDate(visit.start_time)}</h2>
                  <p className="text-sm text-secondary-foreground">
                    {visit.camera} · {t("vehicleVisits.eventCount", { count: visit.event_count })}
                  </p>
                  <p className="text-xs text-secondary-foreground">
                    {t("vehicleVisits.lastSeen")}: {formattedDate(visit.last_seen)}
                  </p>
                  <p className="break-all text-xs text-secondary-foreground">
                    {t("vehicleVisits.id")}: {visit.visit_id}
                  </p>
                </div>
              </div>
              <div className="px-3 pb-3">
                {playing && event && (
                  <div>
                    <video
                      key={event.event_id}
                      className="w-full rounded-lg bg-black"
                      controls
                      autoPlay
                      src={visitClip(visit, selected)}
                      onEnded={() => setPlayback((previous) =>
                        previous?.visitId === visit.visit_id && previous.index + 1 < visit.events.length
                          ? { visitId: visit.visit_id, index: previous.index + 1 }
                          : null
                      )}
                    />
                    <p className="mt-2 text-xs text-secondary-foreground">
                      {t("vehicleVisits.playing", { index: selected + 1, total: visit.event_count })}
                    </p>
                  </div>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <button
                    className="rounded-md bg-selected px-3 py-2 text-sm text-white"
                    onClick={() => setPlayback(playing ? null : { visitId: visit.visit_id, index: 0 })}
                  >
                    {playing ? t("vehicleVisits.stop") : t("vehicleVisits.playAll")}
                  </button>
                  <details className="w-full">
                    <summary className="cursor-pointer text-sm">{t("vehicleVisits.sourceEvents")}</summary>
                    <ol className="mt-2 space-y-2">
                      {visit.events.map((item, index) => (
                        <li key={item.event_id} className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-xs">
                          <span>{index + 1}. {formattedDate(item.start_time)} ({item.match_reason})</span>
                          <div className="flex gap-3">
                            <button className="underline" onClick={() => setPlayback({ visitId: visit.visit_id, index })}>
                              {t("vehicleVisits.play")}
                            </button>
                            <a className="underline" href={createRecordingReviewUrl("/review", { camera: visit.camera, timestamp: item.start_time })}>
                              {t("vehicleVisits.openInReview")}
                            </a>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </details>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </main>
  );
}
