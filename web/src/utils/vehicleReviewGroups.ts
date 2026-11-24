import type { ReviewSegment } from "@/types/review";

export type VehicleReviewLink = {
  camera: string;
  visit_id: string;
  event_ids: string[];
};

export type VehicleReviewGroup = {
  key: string;
  items: ReviewSegment[];
  eventIds: string[];
};

export function groupVehicleReviews(
  items: ReviewSegment[],
  persisted: VehicleReviewLink[],
  previews: VehicleReviewLink[] = [],
): VehicleReviewGroup[] {
  const links = new Map<string, string>();
  const eventKey = (camera: string, id: string) => JSON.stringify([camera, id]);
  for (const visit of persisted) {
    for (const id of visit.event_ids) {
      const key = eventKey(visit.camera, id);
      const value = JSON.stringify([visit.camera, "persisted", visit.visit_id]);
      const previous = links.get(key);
      links.set(key, previous === undefined || previous === value ? value : "");
    }
  }
  for (const visit of previews) {
    // Preview may supplement unlinked history, but must not override durable links.
    if (visit.event_ids.some((id) => links.has(eventKey(visit.camera, id)))) {
      continue;
    }
    for (const id of visit.event_ids) {
      links.set(
        eventKey(visit.camera, id),
        JSON.stringify([visit.camera, "preview", visit.visit_id]),
      );
    }
  }

  const groups = new Map<string, VehicleReviewGroup>();
  for (const item of items) {
    const ids = item.data.detections;
    const carOnly =
      item.end_time != null &&
      ids.length > 0 &&
      item.data.audio.length === 0 &&
      item.data.objects.length > 0 &&
      item.data.objects.every(
        (label) => label === "car" || label === "car-verified",
      );
    const visit = carOnly ? links.get(eventKey(item.camera, ids[0])) : undefined;
    const eligible =
      visit &&
      ids.every((id) => links.get(eventKey(item.camera, id)) === visit);
    const key = eligible
      ? JSON.stringify([visit, item.severity])
      : JSON.stringify(["segment", item.id]);
    let group = groups.get(key);
    if (!group) {
      group = { key, items: [], eventIds: [] };
      groups.set(key, group);
    }
    group.items.push(item);
  }
  for (const group of groups.values()) {
    const chronological = [...group.items].sort(
      (a, b) => a.start_time - b.start_time,
    );
    group.eventIds = [
      ...new Set(chronological.flatMap((item) => item.data.detections)),
    ].sort((a, b) => {
      // Frigate event IDs begin with their epoch timestamp.
      const difference = Number(a.split("-")[0]) - Number(b.split("-")[0]);
      return Number.isFinite(difference) ? difference : 0;
    });
  }
  return [...groups.values()];
}
