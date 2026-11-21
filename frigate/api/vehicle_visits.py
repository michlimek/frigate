"""Authenticated vehicle visits backed by persistent event links."""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from frigate.api.auth import (
    allow_any_authenticated,
    get_allowed_cameras_for_filter,
)
from frigate.models import Event, VehicleVisit, VehicleVisitEvent
from frigate.vehicle_visits.inspection import event_timestamp
from frigate.vehicle_visits.store import linked_events_for_visit

router = APIRouter(tags=["vehicle-visits"])


@router.get("/vehicle_visits", dependencies=[Depends(allow_any_authenticated())])
async def vehicle_visits(
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
        .where(
            (VehicleVisit.camera << cameras)
            & (VehicleVisit.last_seen >= cutoff)
        )
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
            ).where(
                (Event.id << event_ids) & (Event.camera == visit.camera)
            )
        }
        sources = []
        for link in links:
            event = events.get(link.event_id)
            if event is None:
                continue
            sources.append({
                "event_id": link.event_id,
                "start_time": event_timestamp(event.start_time),
                "end_time": (
                    event_timestamp(event.end_time)
                    if event.end_time is not None else None
                ),
                "match_reason": link.match_reason,
                "thumbnail_url": (
                    f"/api/events/{quote(link.event_id, safe='')}/thumbnail.webp"
                ),
            })
        if not sources:
            continue
        result.append({
            "visit_id": visit.id,
            "camera": visit.camera,
            "start_time": visit.start_time,
            "last_seen": visit.last_seen,
            "event_count": len(sources),
            "event_ids": [item["event_id"] for item in sources],
            "events": sources,
            "first_thumbnail_url": sources[0]["thumbnail_url"],
            "grouping_mode": "persistent_conservative",
        })
    return result


@router.get(
    "/vehicle_visits/lookup", dependencies=[Depends(allow_any_authenticated())]
)
async def lookup_vehicle_visit(
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
    link = VehicleVisitEvent.get_or_none(
        VehicleVisitEvent.event_id == event_id
    )
    if link is None:
        return JSONResponse(content={}, status_code=404)
    visit = VehicleVisit.get_or_none(
        (VehicleVisit.id == link.visit_id)
        & (VehicleVisit.camera == camera)
    )
    if visit is None:
        return JSONResponse(content={}, status_code=404)
    return {
        "event_id": event_id,
        "visit_id": visit.id,
        "camera": camera,
        "match_reason": link.match_reason,
        "is_first_event": event_id == visit.id,
        "visit_start_time": visit.start_time,
    }
