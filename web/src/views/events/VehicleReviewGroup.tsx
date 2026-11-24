import { baseUrl } from "@/api/baseUrl";
import type { ReviewSegment } from "@/types/review";
import {
  groupVehicleReviews,
  type VehicleReviewGroup,
  type VehicleReviewLink,
} from "@/utils/vehicleReviewGroups";
import axios from "axios";
import { type ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import useSWR from "swr";

type ReviewRange = { after: number; before: number };

export function useVehicleReviewGroups(
  items: ReviewSegment[] | null,
  timeRange: ReviewRange,
) {
  const cameras = useMemo(
    () =>
      [
        ...new Set(
          (items ?? [])
            .filter((item) =>
              item.data.objects.some(
                (label) => label === "car" || label === "car-verified",
              ),
            )
            .map((item) => item.camera),
        ),
      ].sort(),
    [items],
  );
  const hours = Math.min(
    720,
    Math.max(1, Math.ceil((Date.now() / 1000 - timeRange.after) / 3600)),
  );
  const recent = timeRange.after >= Date.now() / 1000 - 48 * 3600;
  const { data: persisted } = useSWR<VehicleReviewLink[]>(
    cameras.length
      ? ["vehicle_visits", { camera: "all", hours, limit: 250 }]
      : null,
    {
      refreshInterval: 30000,
      revalidateOnFocus: false,
    },
  );
  const { data: previews } = useSWR<VehicleReviewLink[]>(
    cameras.length && recent ? ["vehicle-review-history", cameras] : null,
    async () => {
      const results = await Promise.all(
        cameras.map((camera) =>
          axios.get<VehicleReviewLink[]>("vehicle_visits/preview", {
            params: { camera, hours: 48, limit: 300 },
          }),
        ),
      );
      return results.flatMap((result) => result.data);
    },
    { revalidateOnFocus: false, dedupingInterval: 60000 },
  );

  return useMemo(
    () =>
      groupVehicleReviews(
        items ?? [],
        persisted ?? [],
        persisted ? previews : [],
      ),
    [items, persisted, previews],
  );
}

export function VehicleReviewGroupCard({
  group,
  renderItem,
}: {
  group: VehicleReviewGroup;
  renderItem: (item: ReviewSegment) => ReactNode;
}) {
  const { t } = useTranslation(["common"]);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);
  const index = playingId === null ? -1 : group.eventIds.indexOf(playingId);
  const start = Math.min(...group.items.map((item) => item.start_time));
  const end = Math.max(
    ...group.items.map((item) => item.end_time ?? item.start_time),
  );
  const representative = group.eventIds[0];
  const time = (timestamp: number) => new Date(timestamp * 1000).toLocaleString();

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
          <div className="text-xs">
            {time(start)} – {time(end)}
          </div>
          <div className="text-xs text-secondary-foreground">
            {group.items[0].camera} ·{" "}
            {t("vehicleVisits.eventCount", { count: group.eventIds.length })}
          </div>
        </div>
      </div>
      <button
        className="my-2 rounded border px-2 py-1 text-sm"
        onClick={() => {
          setFailedId(null);
          setPlayingId(index >= 0 ? null : representative);
        }}
      >
        {index >= 0 ? t("vehicleVisits.stop") : t("vehicleVisits.playAll")}
      </button>
      {index >= 0 && playingId !== null && (
        <>
          <video
            key={playingId}
            className="w-full rounded bg-black"
            controls
            autoPlay
            src={`${baseUrl}api/events/${encodeURIComponent(playingId)}/clip.mp4`}
            onError={() => setFailedId(playingId)}
            onEnded={() => {
              setFailedId(null);
              setPlayingId(group.eventIds[index + 1] ?? null);
            }}
          />
          <p className="text-xs">
            {t("vehicleVisits.playing", {
              index: index + 1,
              total: group.eventIds.length,
            })}
          </p>
          {failedId === playingId && (
            <p role="alert" className="text-xs">{t("vehicleVisits.error")}</p>
          )}
          <div className="flex flex-wrap gap-1">
            {group.eventIds.map((id, i) => (
              <button
                key={id}
                className="rounded border px-2 py-1 text-xs"
                aria-pressed={id === playingId}
                aria-label={t("vehicleVisits.playing", {
                  index: i + 1,
                  total: group.eventIds.length,
                })}
                onClick={() => {
                  setFailedId(null);
                  setPlayingId(id);
                }}
              >
                {i + 1}
              </button>
            ))}
          </div>
        </>
      )}
      <details className="mt-2">
        <summary className="cursor-pointer text-sm">{t("vehicleVisits.sourceEvents")}</summary>
        <div className="mt-2 grid gap-2">{group.items.map(renderItem)}</div>
      </details>
    </article>
  );
}
