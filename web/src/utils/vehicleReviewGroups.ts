import type { ReviewSegment } from "@/types/review";
import type { SearchResult } from "@/types/search";

export type VehicleReviewLink = {
  camera: string;
  visit_id: string;
  event_ids: string[];
  clip_event_ids?: string[];
  closed?: boolean;
};

export type VehicleGroup<T> = {
  key: string;
  items: T[];
  eventIds: string[];
  clipEventIds: string[];
  vehicle: boolean;
  closed: boolean;
};

export type VehicleReviewGroup = VehicleGroup<ReviewSegment>;

export function isFinishedCarReview(item: ReviewSegment): boolean {
  return (
    item.end_time != null &&
    item.data.detections.length > 0 &&
    item.data.audio.length === 0 &&
    item.data.objects.length > 0 &&
    item.data.objects.every(
      (label) => label === "car" || label === "car-verified",
    )
  );
}

const eventKey = (camera: string, id: string) => JSON.stringify([camera, id]);
type Identity = { key: string; clips: Set<string>; closed: boolean };

function linkIndex(links: VehicleReviewLink[]) {
  const index = new Map<string, Identity | null>();
  for (const visit of links) {
    const identity = {
      key: JSON.stringify([visit.camera, visit.visit_id]),
      clips: new Set(visit.clip_event_ids ?? visit.event_ids),
      closed: visit.closed ?? false,
    };
    for (const id of visit.event_ids) {
      const key = eventKey(visit.camera, id);
      const existing = index.get(key);
      if (existing === undefined || existing?.key === identity.key) {
        index.set(key, identity);
      } else {
        // Contradictory links must not hide a source event.
        index.set(key, null);
      }
    }
  }
  return index;
}

type GroupItem = {
  id: string;
  camera: string;
  start_time: number;
  end_time?: number;
};

function groupItems<T extends GroupItem>(
  items: T[],
  links: VehicleReviewLink[],
  eligibleIds: (item: T) => string[],
  discriminator: (item: T) => string,
): VehicleGroup<T>[] {
  const index = linkIndex(links);
  const groups = new Map<string, VehicleGroup<T>>();
  for (const item of items) {
    const ids = eligibleIds(item);
    const identity = ids.length ? index.get(eventKey(item.camera, ids[0])) : null;
    const matched =
      identity &&
      ids.every((id) => index.get(eventKey(item.camera, id))?.key === identity.key);
    const key = matched
      ? JSON.stringify([identity.key, discriminator(item)])
      : JSON.stringify(["segment", item.id]);
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        items: [],
        eventIds: [],
        clipEventIds: [],
        vehicle: Boolean(matched),
        closed: matched ? identity.closed : false,
      };
      groups.set(key, group);
    }
    group.items.push(item);
    if (matched) {
      group.eventIds.push(...ids);
      group.clipEventIds.push(...ids.filter((id) => index.get(eventKey(item.camera, id))?.clips.has(id)));
    }
  }
  const sortIds = (ids: string[]) =>
    [...new Set(ids)].sort((a, b) => {
      const difference = Number(a.split("-")[0]) - Number(b.split("-")[0]);
      return Number.isFinite(difference) ? difference : 0;
    });
  for (const group of groups.values()) {
    group.eventIds = sortIds(group.eventIds);
    group.clipEventIds = sortIds(group.clipEventIds);
  }
  return [...groups.values()];
}

export function groupVehicleReviews(
  items: ReviewSegment[],
  links: VehicleReviewLink[],
): VehicleReviewGroup[] {
  return groupItems(
    items,
    links,
    (item) => isFinishedCarReview(item) ? item.data.detections : [],
    (item) => item.severity,
  );
}

export function groupVehicleSearchResults(
  items: SearchResult[],
  links: VehicleReviewLink[],
): VehicleGroup<SearchResult>[] {
  return groupItems(
    items,
    links,
    (item) => item.label === "car" && item.end_time != null ? [item.id] : [],
    () => "",
  );
}
