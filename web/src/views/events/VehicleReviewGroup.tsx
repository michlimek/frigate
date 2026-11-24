import { baseUrl } from "@/api/baseUrl";
import { useIsAdmin } from "@/hooks/use-is-admin";
import type { ReviewSegment } from "@/types/review";
import type { SearchResult } from "@/types/search";
import {
  groupVehicleReviews,
  groupVehicleSearchResults,
  isFinishedCarReview,
  type VehicleGroup,
  type VehicleReviewLink,
} from "@/utils/vehicleReviewGroups";
import axios from "axios";
import { type ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import useSWR, { useSWRConfig } from "swr";

const GROUP_KEY = "vehicle-review-groups";

function useVehicleLinks(ids: string[]) {
  const key = useMemo(() => [...new Set(ids)].sort(), [ids]);
  const { data } = useSWR<VehicleReviewLink[]>(
    key.length ? [GROUP_KEY, key] : null,
    async () => {
      const batches: string[][] = [];
      for (let offset = 0; offset < key.length; offset += 2000) {
        batches.push(key.slice(offset, offset + 2000));
      }
      const result: VehicleReviewLink[] = [];
      for (const eventIds of batches) {
        const response = await axios.post<VehicleReviewLink[]>(
          "vehicle_visits/groups",
          { event_ids: eventIds },
        );
        result.push(...response.data);
      }
      return result;
    },
    { revalidateOnFocus: false, dedupingInterval: 60000 },
  );
  return data;
}

export function useVehicleReviewGroups(items: ReviewSegment[] | null) {
  const ids = useMemo(
    () => (items ?? []).filter(isFinishedCarReview).flatMap((item) => item.data.detections),
    [items],
  );
  const links = useVehicleLinks(ids);
  return useMemo(() => groupVehicleReviews(items ?? [], links ?? []), [items, links]);
}

export function useVehicleSearchGroups(items: SearchResult[], enabled = true) {
  const ids = useMemo(
    () => enabled ? items.filter((item) => item.label === "car" && item.end_time != null).map((item) => item.id) : [],
    [items, enabled],
  );
  const links = useVehicleLinks(ids);
  return useMemo(
    () => groupVehicleSearchResults(items, enabled ? links ?? [] : []),
    [items, links, enabled],
  );
}

type Correction = "merge" | "split" | "close";

export function VehicleGroupActions({
  eventIds,
  actions,
  onCorrected,
}: {
  eventIds: string[];
  actions: Correction[];
  onCorrected?: () => void;
}) {
  const { t } = useTranslation(["common"]);
  const isAdmin = useIsAdmin();
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);

  if (!isAdmin || !eventIds.length || eventIds.length > 200) return null;

  const correct = async (action: Correction) => {
    if (!window.confirm(t("vehicleVisits.correctConfirm"))) return;
    setBusy(true);
    try {
      await axios.post("vehicle_visits/correct", {
        action,
        event_ids: eventIds,
      });
      await mutate((key) => Array.isArray(key) && key[0] === GROUP_KEY);
      toast.success(t("vehicleVisits.correctSuccess"));
      onCorrected?.();
    } catch {
      toast.error(t("vehicleVisits.correctError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap gap-1">
      {actions.map((action) => (
        <button
          key={action}
          className="rounded border px-2 py-1 text-xs disabled:opacity-50"
          disabled={busy || (action === "merge" && eventIds.length < 2)}
          onClick={() => void correct(action)}
        >
          {action === "merge"
            ? t("vehicleVisits.merge")
            : action === "split"
              ? t("vehicleVisits.split")
              : t("vehicleVisits.close")}
        </button>
      ))}
    </div>
  );
}

export function VehicleReviewGroupCard<T extends {
  id: string;
  camera: string;
  start_time: number;
  end_time?: number;
}>({
  group,
  renderItem,
}: {
  group: VehicleGroup<T>;
  renderItem: (item: T) => ReactNode;
}) {
  const { t } = useTranslation(["common"]);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);
  const clips = group.clipEventIds;
  const index = playingId === null ? -1 : clips.indexOf(playingId);
  const start = Math.min(...group.items.map((item) => item.start_time));
  const end = Math.max(...group.items.map((item) => item.end_time ?? item.start_time));
  const representative = group.eventIds[0];
  const time = (timestamp: number) => new Date(timestamp * 1000).toLocaleString();

  const next = () => {
    setFailedId(null);
    setPlayingId(clips[index + 1] ?? null);
  };

  return (
    <article className="overflow-hidden rounded-lg border bg-background_alt p-2">
      <div className="flex items-center gap-2">
        <img
          loading="lazy"
          className="h-20 w-28 rounded object-cover"
          src={`${baseUrl}api/events/${encodeURIComponent(representative)}/thumbnail.webp`}
          alt={t("vehicleVisits.photo")}
        />
        <div className="min-w-0">
          <div className="font-semibold">{t("vehicleVisits.visit")}</div>
          <div className="text-xs">{time(start)} – {time(end)}</div>
          <div className="text-xs text-secondary-foreground">
            {group.items[0].camera} ·{" "}
            {t("vehicleVisits.eventCount", { count: clips.length })}
          </div>
          {group.closed && <div className="text-xs">{t("vehicleVisits.closed")}</div>}
        </div>
      </div>
      {clips.length > 0 && (
        <button
          className="my-2 rounded border px-2 py-1 text-sm"
          onClick={() => {
            setFailedId(null);
            setPlayingId(index >= 0 ? null : clips[0]);
          }}
        >
          {index >= 0 ? t("vehicleVisits.stop") : t("vehicleVisits.playAll")}
        </button>
      )}
      {index >= 0 && playingId !== null && (
        <>
          <video
            key={playingId}
            className="w-full rounded bg-black"
            controls
            autoPlay
            src={`${baseUrl}api/events/${encodeURIComponent(playingId)}/clip.mp4`}
            onError={() => setFailedId(playingId)}
            onEnded={next}
          />
          <p className="text-xs">
            {t("vehicleVisits.playing", { index: index + 1, total: clips.length })}
          </p>
          {failedId === playingId && (
            <div role="alert" className="text-xs">
              {t("vehicleVisits.error")}
              <button className="ml-2 underline" onClick={next}>{t("vehicleVisits.skipClip")}</button>
            </div>
          )}
          <div className="flex flex-wrap gap-1">
            {clips.map((id, i) => (
              <button
                key={id}
                className="rounded border px-2 py-1 text-xs"
                aria-pressed={id === playingId}
                aria-label={t("vehicleVisits.playing", { index: i + 1, total: clips.length })}
                onClick={() => { setFailedId(null); setPlayingId(id); }}
              >
                {i + 1}
              </button>
            ))}
          </div>
        </>
      )}
      {!group.closed && <VehicleGroupActions eventIds={group.eventIds} actions={["close"]} />}
      <details className="mt-2">
        <summary className="cursor-pointer text-sm">{t("vehicleVisits.sourceEvents")}</summary>
        <div className="mt-2 grid gap-2">{group.items.map(renderItem)}</div>
        <div className="mt-2 space-y-1">
          {group.eventIds.map((id) => (
            <div key={id} className="flex items-center justify-between gap-1 text-xs">
              <span>{time(Number(id.split("-")[0]))}</span>
              <VehicleGroupActions eventIds={[id]} actions={["split"]} />
            </div>
          ))}
        </div>
      </details>
    </article>
  );
}
