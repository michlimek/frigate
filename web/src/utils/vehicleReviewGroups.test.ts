import type { ReviewSegment } from "@/types/review";
import type { SearchResult } from "@/types/search";
import { describe, expect, it } from "vitest";
import { groupVehicleReviews, groupVehicleSearchResults } from "./vehicleReviewGroups";

const item = (id: string, detection: string, camera = "ptz"): ReviewSegment => ({
  id,
  camera,
  severity: "alert",
  start_time: 100,
  end_time: 110,
  thumb_path: "",
  has_been_reviewed: false,
  data: {
    audio: [],
    detections: [detection],
    objects: ["car"],
    zones: [],
    significant_motion_areas: [],
  },
});
const link = { camera: "ptz", visit_id: "visit", event_ids: ["100-a", "200-b"] };

describe("groupVehicleReviews", () => {
  it("groups matching car-only reviews and preserves original IDs", () => {
    const a = item("r1", "100-a");
    const b = item("r2", "200-b");
    const groups = groupVehicleReviews([b, a], [link]);
    expect(groups).toHaveLength(1);
    expect(groups[0].items).toEqual([b, a]);
    expect(groups[0].eventIds).toEqual(["100-a", "200-b"]);
  });

  it("leaves mixed, different camera, active and unmatched reviews separate", () => {
    const a = item("r1", "100-a");
    const b = item("r2", "200-b");
    b.data.objects.push("person");
    const c = item("r3", "200-b", "other");
    const d = { ...item("r4", "200-b"), end_time: undefined };
    const e = item("r5", "unknown");
    expect(groupVehicleReviews([a, b, c, d, e], [link])).toHaveLength(5);
  });

  it("does not hide events with conflicting identities", () => {
    const a = item("r1", "100-a");
    const b = item("r2", "200-b");
    const split = { ...link, event_ids: ["100-a"] };
    const conflicting = { ...link, visit_id: "conflicting" };
    expect(groupVehicleReviews([a, b], [split, conflicting])).toHaveLength(2);
    expect(groupVehicleReviews([a, b], [link])).toHaveLength(1);
  });

  it("leaves reviews containing two vehicle identities separate", () => {
    const a = item("r1", "100-a");
    const b = item("r2", "200-b");
    b.data.detections.push("300-c");
    const other = { ...link, visit_id: "other", event_ids: ["300-c"] };
    expect(groupVehicleReviews([a, b], [link, other])).toHaveLength(2);
  });

  it("keeps alert and detection reviews separate", () => {
    const a = item("r1", "100-a");
    const b = { ...item("r2", "200-b"), severity: "detection" as const };
    expect(groupVehicleReviews([a, b], [link])).toHaveLength(2);
  });
});


describe("groupVehicleSearchResults", () => {
  it("groups only finished car detections and excludes missing clips from playback", () => {
    const result = (id: string, label = "car") =>
      ({ id, label, camera: "ptz", start_time: 100, end_time: 110 }) as SearchResult;
    const a = result("100-a");
    const b = result("200-b");
    const c = result("300-c", "person");
    const groups = groupVehicleSearchResults([b, c, a], [{
      ...link,
      clip_event_ids: ["200-b"],
      closed: true,
    }]);
    expect(groups).toHaveLength(2);
    expect(groups[0].eventIds).toEqual(["100-a", "200-b"]);
    expect(groups[0].clipEventIds).toEqual(["200-b"]);
    expect(groups[0].closed).toBe(true);
    expect(groups[1].items).toEqual([c]);
  });
});
