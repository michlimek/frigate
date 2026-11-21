"""Durable mapping between Frigate car events and conservative vehicle visits."""

import logging
from time import time

from frigate.models import VehicleVisit, VehicleVisitEvent
from frigate.vehicle_visits.inspection import inspect_event
from frigate.vehicle_visits.matching import (
    VehicleVisit as MatchVisit,
    image_distance,
    intersection_over_union,
    match_reason,
)

logger = logging.getLogger(__name__)

MAX_VISIT_GAP = 12 * 3600
MAX_SAMPLES = 10


def _samples(visit: VehicleVisit) -> list[dict]:
    """Read valid appearance references without altering the Peewee model."""
    rows = list(visit.samples or [])
    if not rows and visit.reference_hash and visit.reference_box:
        rows.append({
            "hash": visit.reference_hash,
            "box": visit.reference_box,
            "event_id": visit.id,
        })
    return rows


def _matching_signatures(visit: VehicleVisit, observation) -> tuple[str, int, float] | None:
    """Look at bounded same-visit viewpoints, not rolling unrelated matches."""
    matches = []
    for sample in _samples(visit):
        try:
            ref_hash = int(sample["hash"], 16)
            ref_box = tuple(sample["box"])
        except (ValueError, TypeError, KeyError):
            continue
        candidate = MatchVisit(
            visit_id=visit.id,
            camera=visit.camera,
            start_time=visit.start_time,
            end_time=visit.last_seen,
            reference_hash=ref_hash,
            reference_box=ref_box,
            license_plate=visit.license_plate,
        )
        reason = match_reason(candidate, observation)
        if reason:
            dist = image_distance(ref_hash, observation.image_hash)
            overlap = intersection_over_union(ref_box, observation.box)
            if dist is not None:
                matches.append((reason, dist, overlap))
    if not matches:
        return None
    # Prefer the closest visual reference over an arbitrary latest frame.
    return min(matches, key=lambda m: (m[1], -m[2]))


def _update_sample(visit: VehicleVisit, observation) -> bool:
    """Extend photo coverage only for a Frigate ID already linked to the visit."""
    if observation.image_hash is None or observation.box is None:
        return False
    new_hash = f"{observation.image_hash:016x}"
    rows = _samples(visit)
    for sample in rows:
        try:
            distance = image_distance(int(sample["hash"], 16), observation.image_hash)
            overlap = intersection_over_union(tuple(sample["box"]), observation.box)
            if distance is not None and distance <= 3 and overlap >= 0.8:
                return False
        except (ValueError, TypeError, KeyError):
            continue
    rows.append({
        "hash": new_hash,
        "box": list(observation.box),
        "event_id": observation.event_id,
    })
    # Keep the original anchor. Drop intermediate signatures before newest.
    if len(rows) > MAX_SAMPLES:
        rows = [rows[0], *rows[-(MAX_SAMPLES - 1):]]
    visit.samples = rows
    if not visit.reference_hash:
        visit.reference_hash = new_hash
        visit.reference_box = list(observation.box)
    return True


def link_event_to_visit(event) -> tuple[str, str]:
    """Persist an event-to-visit link. Safe to call for repeated event updates.

    All original Frigate Event and ReviewSegment rows are retained. A photo
    match is necessary for new-ID reidentification; time alone never merges
    independent car tracks.
    """
    if event.label != "car":
        raise ValueError("Only car events can be assigned to a vehicle visit")

    observation = inspect_event(event)
    previous = VehicleVisitEvent.get_or_none(VehicleVisitEvent.event_id == event.id)
    if previous is not None:
        visit = VehicleVisit.get_or_none(VehicleVisit.id == previous.visit_id)
        if visit is not None:
            changed = _update_sample(visit, observation)
            if observation.end_time > visit.last_seen:
                visit.last_seen = observation.end_time
                changed = True
            if observation.license_plate and not visit.license_plate:
                visit.license_plate = observation.license_plate
                changed = True
            if changed:
                visit.save()
            return visit.id, previous.match_reason

    candidates = list(
        VehicleVisit.select()
        .where(
            (VehicleVisit.camera == observation.camera)
            & (VehicleVisit.last_seen >= observation.start_time - MAX_VISIT_GAP)
            & (VehicleVisit.start_time <= observation.start_time)
        )
        .order_by(VehicleVisit.last_seen.desc())
        .limit(160)
    )
    matches: list[tuple[str, int, float, VehicleVisit]] = []
    for visit in candidates:
        match = _matching_signatures(visit, observation)
        if match:
            reason, dist, overlap = match
            matches.append((reason, dist, overlap, visit))

    # If multiple visits appear identical, do not silently attach a new car to
    # one of them. Preserve a separate record for human review.
    if len(matches) == 1:
        reason, _, _, visit = matches[0]
        _update_sample(visit, observation)
        if observation.end_time > visit.last_seen:
            visit.last_seen = observation.end_time
        if observation.license_plate and not visit.license_plate:
            visit.license_plate = observation.license_plate
        visit.save()
    else:
        reason = "first_detection" if not matches else "ambiguous_match"
        visit, _ = VehicleVisit.get_or_create(
            id=event.id,
            defaults={
                "camera": observation.camera,
                "start_time": observation.start_time,
                "last_seen": observation.end_time,
                "reference_hash": (
                    f"{observation.image_hash:016x}"
                    if observation.image_hash is not None else None
                ),
                "reference_box": list(observation.box) if observation.box else None,
                "license_plate": observation.license_plate,
                "samples": [],
            },
        )
        _update_sample(visit, observation)
        visit.save()

    VehicleVisitEvent.insert(
        event_id=event.id,
        visit_id=visit.id,
        match_reason=reason,
        start_time=observation.start_time,
    ).on_conflict_replace().execute()
    logger.debug(
        "Vehicle event %s assigned to visit %s (%s)",
        event.id, visit.id, reason,
    )
    return visit.id, reason


def linked_events_for_visit(visit_id: str):
    """Return all persistent source events for a visit in chronological order."""
    return (
        VehicleVisitEvent.select()
        .where(VehicleVisitEvent.visit_id == visit_id)
        .order_by(VehicleVisitEvent.start_time.asc())
    )
