"""Authenticated preview of conservative PTZ vehicle-visit grouping."""

import binascii
import logging
from datetime import UTC, datetime, timedelta

import cv2
import numpy as np
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from frigate.api.auth import allow_any_authenticated, get_allowed_cameras_for_filter
from frigate.models import Event
from frigate.util.file import get_event_thumbnail_bytes
from frigate.vehicle_visits.matching import VehicleObservation, group_vehicle_events

logger = logging.getLogger(__name__)
router = APIRouter(tags=["vehicle-visits"])


def _image_hash(image_bytes: bytes | None) -> int | None:
    """Return a simple 64-bit perceptual hash, rejecting textureless images."""
    if not image_bytes:
        return None
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    small = cv2.resize(image, (9, 8), interpolation=cv2.INTER_AREA)
    differences = (small[:, 1:] > small[:, :-1]).reshape(-1)
    bits = sum(int(bit) << i for i, bit in enumerate(differences))
    if not 5 <= bits.bit_count() <= 59:
        return None
    return bits


def _timestamp(value) -> float:
    """Accept Frigate's epoch timestamps and Peewee datetime values."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.timestamp()
    return float(value)


def _normalized_box(value) -> tuple[float, float, float, float] | None:
    """Return a relative box if Frigate's stored event box is valid."""
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    try:
        box = tuple(float(n) for n in value)
    except (ValueError, TypeError):
        return None
    if not all(0.0 <= n <= 1.0 for n in box):
        return None
    return box if box[0] < box[2] and box[1] < box[3] else None


@router.get(
    "/vehicle_visits/preview",
    dependencies=[Depends(allow_any_authenticated())],
)
async def vehicle_visits_preview(
    camera: str,
    allowed_cameras: list[str] = Depends(get_allowed_cameras_for_filter),
    limit: int = Query(default=200, ge=1, le=300),
    hours: int = Query(default=24, ge=1, le=48),
):
    """Group likely repeat sightings without changing events, reviews or recordings.

    This endpoint avoids matching on temporal proximity alone. Uncertain cases
    remain separate pending stronger appearance evidence or manual review.
    """
    if camera not in allowed_cameras:
        return JSONResponse(content=[], status_code=403)

    after = (datetime.now(UTC) - timedelta(hours=hours)).timestamp()
    rows = list(
        Event.select(
            Event.id,
            Event.camera,
            Event.start_time,
            Event.end_time,
            Event.data,
            Event.thumbnail,
            Event.sub_label,
        )
        .where(
            (Event.camera == camera)
            & (Event.label == "car")
            & (Event.start_time >= after)
        )
        .order_by(Event.start_time.desc())
        .limit(limit)
    )
    observations = []
    for event in rows:
        data = event.data if isinstance(event.data, dict) else {}
        plate = data.get("recognized_license_plate")
        try:
            photo = get_event_thumbnail_bytes(event)
        except (ValueError, binascii.Error):
            logger.debug("Invalid vehicle thumbnail for %s", event.id)
            photo = None
        observations.append(
            VehicleObservation(
                event_id=event.id,
                camera=event.camera,
                start_time=_timestamp(event.start_time),
                end_time=_timestamp(event.end_time)
                if event.end_time is not None
                else datetime.now(UTC).timestamp(),
                box=_normalized_box(data.get("box")),
                image_hash=_image_hash(photo),
                license_plate=str(plate).strip().upper() if plate else None,
            )
        )
    visits = group_vehicle_events(observations)
    return JSONResponse(
        content=[
            {
                "visit_id": visit.visit_id,
                "camera": visit.camera,
                "start_time": visit.start_time,
                "end_time": visit.end_time,
                "event_ids": visit.events,
                "match_reasons": visit.matches,
                "event_count": len(visit.events),
                "grouping_mode": "conservative_preview",
            }
            for visit in reversed(visits)
        ]
    )
