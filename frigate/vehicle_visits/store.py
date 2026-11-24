"""Durable mapping between Frigate car events and conservative vehicle visits."""

import logging
from threading import RLock
from uuid import uuid4

from frigate.models import Event, VehicleVisit, VehicleVisitEvent
from frigate.vehicle_visits.inspection import inspect_event
from frigate.vehicle_visits.matching import VehicleVisit as MatchVisit
from frigate.vehicle_visits.matching import (
    group_vehicle_events,
    image_distance,
    intersection_over_union,
    match_reason,
)

logger = logging.getLogger(__name__)

MAX_VISIT_GAP = 12 * 3600
MAX_SAMPLES = 10
_visit_lock = RLock()


def _samples(visit: VehicleVisit) -> list[dict]:
    """Read valid appearance references without altering the Peewee model."""
    rows = list(visit.samples or [])
    if not rows and visit.reference_hash and visit.reference_box:
        rows.append(
            {
                "hash": visit.reference_hash,
                "box": visit.reference_box,
                "event_id": visit.id,
            }
        )
    return rows


def _matching_signatures(
    visit: VehicleVisit, observation
) -> tuple[str, int, float] | None:
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
    rows.append(
        {
            "hash": new_hash,
            "box": list(observation.box),
            "event_id": observation.event_id,
        }
    )
    # Keep the original anchor. Drop intermediate signatures before newest.
    if len(rows) > MAX_SAMPLES:
        rows = [rows[0], *rows[-(MAX_SAMPLES - 1) :]]
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
    with _visit_lock:
        return _link_event_to_visit(event)


def _link_event_to_visit(event) -> tuple[str, str]:
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
            & VehicleVisit.closed_at.is_null()
        )
        .where(
            VehicleVisit.id.in_(VehicleVisitEvent.select(VehicleVisitEvent.visit_id))
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
        # Frigate uses SqliteVecQueueDatabase, whose atomic() method is
        # unsupported. Peewee get_or_create() implicitly starts a transaction
        # for new rows and fails before inserting any visit.
        # INSERT OR IGNORE is atomic at the SQLite statement level and works
        # with the queued writer; the completed write is visible on read.
        VehicleVisit.insert(
            id=event.id,
            camera=observation.camera,
            start_time=observation.start_time,
            last_seen=observation.end_time,
            reference_hash=(
                f"{observation.image_hash:016x}"
                if observation.image_hash is not None
                else None
            ),
            reference_box=list(observation.box) if observation.box else None,
            license_plate=observation.license_plate,
            samples=[],
        ).on_conflict_ignore().execute()
        visit = VehicleVisit.get_by_id(event.id)
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
        event.id,
        visit.id,
        reason,
    )
    return visit.id, reason


def linked_events_for_visit(visit_id: str):
    """Return all persistent source events for a visit in chronological order."""
    return (
        VehicleVisitEvent.select()
        .where(VehicleVisitEvent.visit_id == visit_id)
        .order_by(VehicleVisitEvent.start_time.asc())
    )


def _set_observations(visit: VehicleVisit, observations: list) -> None:
    """Rebuild the appearance anchors from the retained members of a group."""
    visit.start_time = min(item.start_time for item in observations)
    visit.last_seen = max(item.end_time for item in observations)
    visit.reference_hash = None
    visit.reference_box = None
    visit.samples = []
    plates = {item.license_plate for item in observations if item.license_plate}
    visit.license_plate = next(iter(plates)) if len(plates) == 1 else None
    for observation in observations:
        _update_sample(visit, observation)


def correct_vehicle_events(events: list[Event], action: str) -> str:
    """Move selected ended car events together, or explicitly close one group.

    Writes are serialized with live linking. The event-link move itself is one
    queued SQL statement; no recording, Event, or ReviewSegment is rewritten.
    """
    if action not in {"merge", "split", "close"}:
        raise ValueError("Unknown vehicle group action")
    if (
        not events
        or len({event.camera for event in events}) != 1
        or any(event.label != "car" or event.end_time is None for event in events)
    ):
        raise ValueError("Select finished car events from one camera")
    if action == "merge" and len(events) < 2:
        raise ValueError("Select at least two car events to merge")
    ids = [event.id for event in events]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate event IDs")

    with _visit_lock:
        previous = list(
            VehicleVisitEvent.select().where(VehicleVisitEvent.event_id << ids)
        )
        old_ids = {link.visit_id for link in previous}
        if action == "close" and old_ids:
            if len(old_ids) != 1 or len(previous) != len(ids):
                raise ValueError("Select one complete vehicle identity to close")
            visit = VehicleVisit.get_by_id(next(iter(old_ids)))
            visit.closed_at = visit.last_seen
            visit.save(only=[VehicleVisit.closed_at])
            return visit.id

        observations = sorted(
            (inspect_event(event) for event in events),
            key=lambda item: (item.start_time, item.event_id),
        )
        if action == "close" and len(group_vehicle_events(observations)) != 1:
            raise ValueError("Select one vehicle identity to close")

        # Preserve the anchor for an already-correct group.
        if action == "merge" and len(old_ids) == 1 and len(previous) == len(ids):
            return next(iter(old_ids))

        # Compute replacement metadata before moving any links. Expired source
        # events remain untouched; their old visit can no longer match if it
        # has no retained observations.
        old_visits = list(VehicleVisit.select().where(VehicleVisit.id << old_ids))
        was_closed = len(previous) == len(ids) and bool(old_visits) and all(
            old.closed_at is not None for old in old_visits
        )
        for old in old_visits:
            remaining = list(
                Event.select()
                .join(
                    VehicleVisitEvent,
                    on=(Event.id == VehicleVisitEvent.event_id),
                )
                .where(
                    (VehicleVisitEvent.visit_id == old.id)
                    & (Event.id.not_in(ids))
                    & (Event.camera == old.camera)
                )
                .order_by(Event.start_time.asc())
            )
            if remaining:
                _set_observations(old, [inspect_event(event) for event in remaining])
            else:
                old.closed_at = old.last_seen

        visit_id = f"manual-{uuid4().hex[:22]}"
        visit = VehicleVisit(
            id=visit_id,
            camera=events[0].camera,
            start_time=observations[0].start_time,
            last_seen=observations[0].end_time,
        )
        _set_observations(visit, observations)
        if action == "close" or was_closed:
            visit.closed_at = visit.last_seen
        visit.save(force_insert=True)
        # The entire reassignment is atomic at the single-statement level.
        VehicleVisitEvent.insert_many(
            [
                {
                    "event_id": observation.event_id,
                    "visit_id": visit_id,
                    "match_reason": f"manual_{action}",
                    "start_time": observation.start_time,
                }
                for observation in observations
            ]
        ).on_conflict_replace().execute()
        for old in old_visits:
            old.save()
        return visit_id
