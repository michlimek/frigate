"""Authenticated vehicle visits backed by persistent event links."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from frigate.api.auth import (
    allow_any_authenticated,
    get_allowed_cameras_for_filter,
    require_role,
)
from frigate.models import Event, VehicleVisit, VehicleVisitEvent
from frigate.vehicle_visits.inspection import event_timestamp, inspect_event
from frigate.vehicle_visits.matching import group_vehicle_events
from frigate.vehicle_visits.store import (
    correct_vehicle_events,
    link_event_to_visit,
    linked_events_for_visit,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["vehicle-visits"])


@router.get("/vehicle_visits", dependencies=[Depends(allow_any_authenticated())])
def vehicle_visits(
    camera: str = "all",
    hours: int = Query(default=48, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=250),
    allowed_cameras: list[str] = Depends(get_allowed_cameras_for_filter),
):
    """Return one logical visit with all still-retained source videos."""
    if camera != "all" and camera not in allowed_cameras:
        return JSONResponse(content=[], status_code=403)
    cameras = [camera] if camera != "all" else allowed_cameras
    if not cameras:
        return []

    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).timestamp()
    visits = list(
        VehicleVisit.select()
        .where((VehicleVisit.camera << cameras) & (VehicleVisit.last_seen >= cutoff))
        .order_by(VehicleVisit.last_seen.desc())
        .limit(limit)
    )
    result = []
    for visit in visits:
        links = list(linked_events_for_visit(visit.id))
        event_ids = [item.event_id for item in links]
        if not event_ids:
            continue
        events = {
            item.id: item
            for item in Event.select(
                Event.id, Event.camera, Event.start_time, Event.end_time
            ).where((Event.id << event_ids) & (Event.camera == visit.camera))
        }
        sources = []
        for link in links:
            event = events.get(link.event_id)
            if event is None:
                continue
            sources.append(
                {
                    "event_id": link.event_id,
                    "start_time": event_timestamp(event.start_time),
                    "end_time": (
                        event_timestamp(event.end_time)
                        if event.end_time is not None
                        else None
                    ),
                    "match_reason": link.match_reason,
                    "thumbnail_url": (
                        f"/api/events/{quote(link.event_id, safe='')}/thumbnail.webp"
                    ),
                }
            )
        if not sources:
            continue
        result.append(
            {
                "visit_id": visit.id,
                "camera": visit.camera,
                "start_time": visit.start_time,
                "last_seen": visit.last_seen,
                "event_count": len(sources),
                "event_ids": [item["event_id"] for item in sources],
                "events": sources,
                "first_thumbnail_url": sources[0]["thumbnail_url"],
                "grouping_mode": "persistent_conservative",
            }
        )
    return result


@router.get("/vehicle_visits/lookup", dependencies=[Depends(allow_any_authenticated())])
def lookup_vehicle_visit(
    camera: str,
    event_id: str,
    allowed_cameras: list[str] = Depends(get_allowed_cameras_for_filter),
):
    """Resolve a Frigate event ID to its persistent visit ID for HA clients."""
    if camera not in allowed_cameras:
        return JSONResponse(content={}, status_code=403)
    event = Event.get_or_none((Event.id == event_id) & (Event.camera == camera))
    if event is None:
        return JSONResponse(content={}, status_code=404)
    link = VehicleVisitEvent.get_or_none(VehicleVisitEvent.event_id == event_id)
    if link is None:
        return JSONResponse(content={}, status_code=404)
    visit = VehicleVisit.get_or_none(
        (VehicleVisit.id == link.visit_id) & (VehicleVisit.camera == camera)
    )
    if visit is None:
        return JSONResponse(content={}, status_code=404)
    first = linked_events_for_visit(visit.id).first()
    return {
        "event_id": event_id,
        "visit_id": visit.id,
        "camera": camera,
        "match_reason": link.match_reason,
        "is_first_event": first is not None and first.event_id == event_id,
        "visit_start_time": visit.start_time,
    }


@router.post(
    "/vehicle_visits/backfill",
    dependencies=[Depends(require_role(["admin"]))],
)
def backfill_vehicle_visits(
    camera: str,
    hours: int = Query(default=48, ge=1, le=720),
    limit: int = Query(default=250, ge=1, le=500),
    allowed_cameras: list[str] = Depends(get_allowed_cameras_for_filter),
):
    """Import a bounded batch of retained historical car events in time order.

    This explicitly triggered operation never edits original Frigate events.
    Calling it again processes the next batch of unlinked events.
    """
    if camera not in allowed_cameras:
        return JSONResponse(content={}, status_code=403)
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).timestamp()
    rows = list(
        Event.select()
        .where(
            (Event.camera == camera)
            & (Event.label == "car")
            & (Event.start_time >= cutoff)
            & (Event.id.not_in(VehicleVisitEvent.select(VehicleVisitEvent.event_id)))
        )
        .order_by(Event.start_time.asc())
        .limit(limit)
    )
    imported = 0
    failures = 0
    for event in rows:
        try:
            link_event_to_visit(event)
            imported += 1
        except Exception:
            # Continue with other historical rows and report partial failure.
            logger.exception("Failed to import vehicle event %s", event.id)
            failures += 1
    return {
        "camera": camera,
        "processed": imported,
        "failed": failures,
        "more_possible": len(rows) == limit,
    }


class VehicleGroupRequest(BaseModel):
    event_ids: list[str] = Field(min_length=1, max_length=2000)


class VehicleCorrectionRequest(BaseModel):
    action: Literal["merge", "split", "close"]
    event_ids: list[str] = Field(min_length=1, max_length=200)


@router.post(
    "/vehicle_visits/groups",
    dependencies=[Depends(allow_any_authenticated())],
)
def groups_for_events(
    body: VehicleGroupRequest,
    allowed_cameras: list[str] = Depends(get_allowed_cameras_for_filter),
):
    """Resolve exactly the retained finished cars requested by Review or Explore.

    Persisted links are authoritative. Unlinked history is grouped read-only
    without a wall-clock cutoff, and without joining across durable identities.
    """
    ids = list(dict.fromkeys(body.event_ids))
    grouped: dict[tuple[str, str], dict] = {}
    unlinked = []
    for start in range(0, len(ids), 200):
        chunk = ids[start : start + 200]
        events = list(
            Event.select()
            .where(
                (Event.id << chunk)
                & (Event.camera << allowed_cameras)
                & (Event.label == "car")
                & Event.end_time.is_null(False)
            )
            .order_by(Event.start_time.asc())
        )
        links = {}
        # The mapping is joined explicitly because visit_id is not a foreign key.
        for row in (
            VehicleVisitEvent.select(
                VehicleVisitEvent.event_id,
                VehicleVisitEvent.visit_id,
                VehicleVisit.camera,
                VehicleVisit.closed_at,
            )
            .join(VehicleVisit, on=(VehicleVisitEvent.visit_id == VehicleVisit.id))
            .where(
                (VehicleVisitEvent.event_id << [event.id for event in events])
                & (VehicleVisit.camera << allowed_cameras)
            )
            .dicts()
        ):
            links[row["event_id"]] = (
                row["visit_id"],
                row["camera"],
                row["closed_at"],
            )
        for event in events:
            link = links.get(event.id)
            if link is None:
                unlinked.append(event)
                continue
            visit_id, camera, closed_at = link
            if camera != event.camera:
                continue
            group = grouped.setdefault(
                (camera, visit_id),
                {
                    "camera": camera,
                    "visit_id": visit_id,
                    "event_ids": [],
                    "clip_event_ids": [],
                    "closed": closed_at is not None,
                },
            )
            group["event_ids"].append(event.id)
            if event.has_clip:
                group["clip_event_ids"].append(event.id)

    clips = {event.id for event in unlinked if event.has_clip}
    for group in group_vehicle_events([inspect_event(event) for event in unlinked]):
        preview_id = f"preview-{group.visit_id}"
        grouped[(group.camera, preview_id)] = {
            "camera": group.camera,
            "visit_id": preview_id,
            "event_ids": group.events,
            "clip_event_ids": [
                event_id for event_id in group.events if event_id in clips
            ],
            "closed": False,
        }
    return list(grouped.values())


@router.post(
    "/vehicle_visits/correct",
    dependencies=[Depends(require_role(["admin"]))],
)
def correct_vehicle_group(
    body: VehicleCorrectionRequest,
    allowed_cameras: list[str] = Depends(get_allowed_cameras_for_filter),
):
    """Manually join, separate or confirm departure for finished car events."""
    ids = list(dict.fromkeys(body.event_ids))
    events = list(
        Event.select().where((Event.id << ids) & (Event.camera << allowed_cameras))
    )
    if len(events) != len(ids):
        return JSONResponse(
            status_code=404, content={"message": "Source event unavailable"}
        )
    try:
        visit_id = correct_vehicle_events(events, body.action)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"message": str(exc)})
    return {"visit_id": visit_id, "action": body.action}
