"""Conservative grouping of object detections into vehicle visits.

This is a read-only preview. Original Frigate events and media remain intact.
"""

from dataclasses import dataclass, field
from math import isfinite


@dataclass(frozen=True)
class VehicleObservation:
    event_id: str
    camera: str
    start_time: float
    end_time: float
    box: tuple[float, float, float, float] | None = None
    image_hash: int | None = None
    license_plate: str | None = None


@dataclass
class VehicleVisit:
    visit_id: str
    camera: str
    start_time: float
    end_time: float
    events: list[str] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)
    reference_box: tuple[float, float, float, float] | None = None
    reference_hash: int | None = None
    license_plate: str | None = None

    def add(self, event: VehicleObservation, reason: str) -> None:
        self.start_time = min(self.start_time, event.start_time)
        self.end_time = max(self.end_time, event.end_time)
        self.events.append(event.event_id)
        self.matches.append(reason)
        if self.reference_hash is None and event.image_hash is not None:
            self.reference_hash = event.image_hash
        if self.reference_box is None and event.box is not None:
            self.reference_box = event.box
        if event.license_plate:
            self.license_plate = event.license_plate


def intersection_over_union(
    left: tuple[float, float, float, float] | None,
    right: tuple[float, float, float, float] | None,
) -> float:
    """Return normalized box overlap, or zero when boxes are unusable."""
    if left is None or right is None:
        return 0.0
    if not all(isfinite(value) for value in (*left, *right)):
        return 0.0
    if left[0] >= left[2] or left[1] >= left[3]:
        return 0.0
    if right[0] >= right[2] or right[1] >= right[3]:
        return 0.0
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = width * height
    a1 = (left[2] - left[0]) * (left[3] - left[1])
    a2 = (right[2] - right[0]) * (right[3] - right[1])
    return intersection / (a1 + a2 - intersection) if a1 + a2 > intersection else 0.0


def image_distance(left: int | None, right: int | None) -> int | None:
    """Count differing bits in two 64-bit perceptual fingerprints."""
    if left is None or right is None:
        return None
    if left < 0 or right < 0 or left.bit_length() > 64 or right.bit_length() > 64:
        return None
    return (left ^ right).bit_count()


def match_reason(visit: VehicleVisit, event: VehicleObservation) -> str | None:
    """Join only when visual and spatial evidence are mutually consistent.

    Bounding-box overlap is meaningful only for comparable camera viewpoints.
    This preview deliberately does not attempt cross-preset visual re-ID.
    """
    if visit.camera != event.camera or event.start_time < visit.start_time:
        return None
    gap = max(0.0, event.start_time - visit.end_time)
    if gap > 12 * 3600:
        return None
    if visit.license_plate and event.license_plate:
        if visit.license_plate != event.license_plate:
            return None
    overlap = intersection_over_union(visit.reference_box, event.box)
    distance = image_distance(visit.reference_hash, event.image_hash)
    if distance is None:
        return None
    if overlap >= 0.85 and distance <= 2:
        return "stationary_visual_match"
    if gap <= 120 and overlap >= 0.60 and distance <= 5:
        return "recent_visual_match"
    if (
        visit.license_plate
        and event.license_plate == visit.license_plate
        and gap <= 120
        and overlap >= 0.35
        and distance <= 10
    ):
        return "plate_and_visual_match"
    return None


def group_vehicle_events(events: list[VehicleObservation]) -> list[VehicleVisit]:
    """Group existing events without modifying their identity or recordings."""
    groups: list[VehicleVisit] = []
    seen_ids: set[str] = set()
    for event in sorted(events, key=lambda item: (item.start_time, item.event_id)):
        if event.event_id in seen_ids:
            continue
        seen_ids.add(event.event_id)
        matches = []
        for group in reversed(groups):
            reason = match_reason(group, event)
            if reason:
                matches.append((group, reason))
        # Like the durable matcher, never choose arbitrarily between candidates.
        if len(matches) != 1:
            group = VehicleVisit(
                visit_id=event.event_id,
                camera=event.camera,
                start_time=event.start_time,
                end_time=event.end_time,
            )
            group.add(event, "first_detection")
            groups.append(group)
        else:
            group, reason = matches[0]
            group.add(event, reason)
    return groups
